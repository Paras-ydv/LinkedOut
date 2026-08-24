"""Layoff events.

Only the SELF_REPORTED path is exposed publicly in this phase. NEWS-sourced
entries (curated/ingested by an admin/internal process) have no public
endpoint yet — `submitted_by_user_id` stays NULL for those and they'd be
inserted directly (or via an internal-only route added in a later phase),
never through `POST /layoff-events`.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_tier
from app.core.moderation_filter import scan_for_flagged_content
from app.models.company import Company
from app.models.enums import LayoffSourceType, ReviewStatus, VerificationTier
from app.models.layoff import LayoffEvent
from app.models.user import User
from app.schemas.layoff import (
    LayoffEventCreate,
    LayoffEventCreateOut,
    LayoffEventRead,
    PaginatedLayoffEvents,
)

router = APIRouter(prefix="/layoff-events", tags=["layoff-events"])

_MAX_PAGE_SIZE = 100


def _now() -> datetime:
    return datetime.now(UTC)


@router.post("", response_model=LayoffEventCreateOut, status_code=status.HTTP_201_CREATED)
async def submit_layoff_event(
    body: LayoffEventCreate,
    user: User = Depends(require_tier(VerificationTier.email)),
    db: AsyncSession = Depends(get_db),
) -> LayoffEventCreateOut:
    company = (
        await db.execute(select(Company.id).where(Company.id == body.company_id))
    ).scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="company not found")

    # Same Phase 4 pre-publication name filter as Review — see
    # app.routers.reviews.submit_review for the full note.
    flagged_reason = scan_for_flagged_content(body.department)

    event = LayoffEvent(
        id=uuid.uuid4(),
        company_id=body.company_id,
        event_date=body.event_date,
        department=body.department,
        estimated_headcount=body.estimated_headcount,
        source_type=LayoffSourceType.self_reported,
        source_url=None,  # source_url only applies to NEWS-sourced entries
        submitted_by_user_id=user.id,
        status=ReviewStatus.pending,
        flagged_reason=flagged_reason,
        created_at=_now(),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    return LayoffEventCreateOut(id=event.id, status=event.status)


@router.get("/company/{company_id}", response_model=PaginatedLayoffEvents)
async def list_company_layoff_events(
    company_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=_MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PaginatedLayoffEvents:
    base_filter = (
        LayoffEvent.company_id == company_id,
        LayoffEvent.status == ReviewStatus.published,
    )

    total = (
        await db.execute(select(func.count()).select_from(LayoffEvent).where(*base_filter))
    ).scalar_one()

    result = await db.execute(
        select(LayoffEvent)
        .where(*base_filter)
        .order_by(LayoffEvent.event_date.desc())
        .limit(limit)
        .offset(offset)
    )
    events = result.scalars().all()

    return PaginatedLayoffEvents(
        items=[LayoffEventRead.model_validate(e) for e in events],
        total=total,
        limit=limit,
        offset=offset,
    )
