"""Core review flow: reviews, corroborations, and employer responses.

Publication: every review is created PENDING and stays PENDING here —
Phase 4 wires the moderation queue (including the pre-publication name
filter) that flips PENDING -> PUBLISHED/REJECTED. `GET` endpoints in this
module only ever return PUBLISHED rows to the public.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_employer_account, require_tier
from app.core.moderation_filter import scan_for_flagged_content
from app.models.company import Company
from app.models.employer import EmployerAccount, EmployerResponse
from app.models.enums import ReviewStatus, VerificationTier
from app.models.review import Corroboration, Review
from app.models.user import User
from app.schemas.employer import EmployerResponseCreate, EmployerResponseRead
from app.schemas.review import (
    CorroborationCreate,
    CorroborationCreateOut,
    CorroborationRead,
    PaginatedCorroborations,
    PaginatedReviews,
    ReviewCreate,
    ReviewCreateOut,
    ReviewRead,
)

router = APIRouter(prefix="/reviews", tags=["reviews"])

_MAX_PAGE_SIZE = 100


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------
# Reviews
# --------------------------------------------------------------------------


@router.post("", response_model=ReviewCreateOut, status_code=status.HTTP_201_CREATED)
async def submit_review(
    body: ReviewCreate,
    user: User = Depends(require_tier(VerificationTier.email)),
    db: AsyncSession = Depends(get_db),
) -> ReviewCreateOut:
    company = (
        await db.execute(select(Company.id).where(Company.id == body.company_id))
    ).scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="company not found")

    existing = (
        await db.execute(
            select(Review.id).where(Review.user_id == user.id, Review.company_id == body.company_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="you have already submitted a review for this company",
        )

    # Phase 4 pre-publication name filter: scans the free-text fields
    # (department + prose) for anything that looks like a person's name.
    # A hit never blocks or auto-rejects — it only sets `flagged_reason`,
    # which routes this row to the front of the moderation queue (see
    # app.routers.admin.get_moderation_queue). `status` is PENDING either
    # way; nothing here or anywhere in Phase 2 ever auto-publishes.
    flagged_reason = scan_for_flagged_content(body.department, body.prose)

    review = Review(
        id=uuid.uuid4(),
        user_id=user.id,
        company_id=body.company_id,
        exit_reason=body.exit_reason,
        tenure_bucket=body.tenure_bucket,
        department=body.department,
        role_level=body.role_level,
        is_current_employee=body.is_current_employee,
        prose=body.prose,
        status=ReviewStatus.pending,
        flagged_reason=flagged_reason,
        created_at=_now(),
    )
    db.add(review)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        # Race with a concurrent submission from the same user/company —
        # the unique constraint is the real guard; this just gives a clean
        # 409 instead of a raw IntegrityError leaking out.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="you have already submitted a review for this company",
        ) from exc
    await db.refresh(review)

    return ReviewCreateOut(id=review.id, status=review.status)


@router.get("/company/{company_id}", response_model=PaginatedReviews)
async def list_company_reviews(
    company_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=_MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PaginatedReviews:
    base_filter = (Review.company_id == company_id, Review.status == ReviewStatus.published)

    total = (
        await db.execute(select(func.count()).select_from(Review).where(*base_filter))
    ).scalar_one()

    result = await db.execute(
        select(Review)
        .where(*base_filter)
        .order_by(Review.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    reviews = result.scalars().all()

    return PaginatedReviews(
        items=[ReviewRead.model_validate(r) for r in reviews],
        total=total,
        limit=limit,
        offset=offset,
    )


# --------------------------------------------------------------------------
# Corroborations
# --------------------------------------------------------------------------


@router.post(
    "/{review_id}/corroborate",
    response_model=CorroborationCreateOut,
    status_code=status.HTTP_201_CREATED,
)
async def corroborate_review(
    review_id: uuid.UUID,
    body: CorroborationCreate,
    user: User = Depends(require_tier(VerificationTier.phone)),
    db: AsyncSession = Depends(get_db),
) -> CorroborationCreateOut:
    review = (
        await db.execute(select(Review.id, Review.user_id).where(Review.id == review_id))
    ).first()
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="review not found")

    if review.user_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="you cannot corroborate your own review"
        )

    existing = (
        await db.execute(
            select(Corroboration.id).where(
                Corroboration.review_id == review_id, Corroboration.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="you have already corroborated this review"
        )

    corroboration = Corroboration(
        id=uuid.uuid4(),
        review_id=review_id,
        user_id=user.id,
        comment=body.comment,
        created_at=_now(),
    )
    db.add(corroboration)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="you have already corroborated this review"
        ) from exc
    await db.refresh(corroboration)

    return CorroborationCreateOut(id=corroboration.id)


@router.get("/{review_id}/corroborations", response_model=PaginatedCorroborations)
async def list_corroborations(
    review_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=_MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PaginatedCorroborations:
    review_exists = (
        await db.execute(select(Review.id).where(Review.id == review_id))
    ).scalar_one_or_none()
    if review_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="review not found")

    count = (
        await db.execute(
            select(func.count())
            .select_from(Corroboration)
            .where(Corroboration.review_id == review_id)
        )
    ).scalar_one()

    result = await db.execute(
        select(Corroboration.comment, Corroboration.created_at)
        .where(Corroboration.review_id == review_id)
        .order_by(Corroboration.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    # No user identity selected/returned at all, per spec — only comment + timestamp.
    items = [CorroborationRead(comment=row.comment, created_at=row.created_at) for row in result]

    return PaginatedCorroborations(count=count, items=items, limit=limit, offset=offset)


# --------------------------------------------------------------------------
# Employer response
# --------------------------------------------------------------------------


@router.post(
    "/{review_id}/response",
    response_model=EmployerResponseRead,
    status_code=status.HTTP_201_CREATED,
)
async def respond_to_review(
    review_id: uuid.UUID,
    body: EmployerResponseCreate,
    employer_account: EmployerAccount = Depends(get_current_employer_account),
    db: AsyncSession = Depends(get_db),
) -> EmployerResponseRead:
    review = (
        await db.execute(select(Review.id, Review.company_id).where(Review.id == review_id))
    ).first()
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="review not found")

    # An employer can only respond to reviews about their own company.
    if review.company_id != employer_account.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you may only respond to reviews about your own company",
        )

    existing = (
        await db.execute(select(EmployerResponse.id).where(EmployerResponse.review_id == review_id))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="this review already has a response"
        )

    response = EmployerResponse(
        id=uuid.uuid4(),
        review_id=review_id,
        employer_account_id=employer_account.id,
        response_text=body.response_text,
        created_at=_now(),
    )
    db.add(response)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="this review already has a response"
        ) from exc
    await db.refresh(response)

    # No DELETE route exists for EmployerResponse anywhere in this phase —
    # once posted, it's permanent.
    return EmployerResponseRead.model_validate(response)
