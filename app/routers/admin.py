"""Admin routes (Phase 4): login, moderation queue, grievance triage.

Every route except `/admin/login` depends on `get_current_admin` (see
app.core.deps) — a missing/invalid/non-admin bearer token is a 401, a
deactivated admin account is a 403. There is no admin self-signup route;
`AdminUser` rows are seeded directly, same posture as `EmployerAccount`.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_admin
from app.core.jwt import create_admin_token
from app.core.security import verify_password
from app.models.admin import AdminUser
from app.models.audit import ModerationAuditLogEntry
from app.models.enums import (
    ModeratedItemType,
    ModerationAction,
    ModerationStatus,
    ReviewStatus,
    VerificationTier,
)
from app.models.grievance import GrievanceComplaint
from app.models.layoff import LayoffEvent
from app.models.moderation import ModerationQueueItem
from app.models.review import Review
from app.models.user import User
from app.providers.document import delete_ephemeral_file
from app.schemas.admin import (
    AdminLoginIn,
    AdminLoginOut,
    DocumentModerationActionOut,
    DocumentQueueEntry,
    ModerationActionOut,
    ModerationQueueEntry,
    ModerationRejectIn,
    PaginatedDocumentQueue,
    PaginatedModerationQueue,
)
from app.schemas.grievance import GrievanceComplaintAdminRead, PaginatedGrievances

router = APIRouter(prefix="/admin", tags=["admin"])

_MAX_PAGE_SIZE = 100


def _now() -> datetime:
    return datetime.now(UTC)


@router.post("/login", response_model=AdminLoginOut)
async def admin_login(body: AdminLoginIn, db: AsyncSession = Depends(get_db)) -> AdminLoginOut:
    admin = (
        await db.execute(select(AdminUser).where(AdminUser.email == body.email.strip().lower()))
    ).scalar_one_or_none()

    # Constant-shape failure whether the email doesn't exist or the
    # password is wrong, and whether the account is inactive — don't leak
    # which case it was.
    if (
        admin is None
        or not admin.is_active
        or not verify_password(body.password, admin.password_hash)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    return AdminLoginOut(access_token=create_admin_token(admin.id), admin_id=admin.id)


# --------------------------------------------------------------------------
# Moderation queue
# --------------------------------------------------------------------------


@router.get("/moderation-queue", response_model=PaginatedModerationQueue)
async def get_moderation_queue(
    limit: int = Query(default=20, ge=1, le=_MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> PaginatedModerationQueue:
    """PENDING reviews and layoff-events, flagged items first, then oldest first.

    Merges two tables into one sorted feed in Python rather than a SQL
    UNION: the two source tables have different columns (only Review has
    `prose`, only LayoffEvent's department is nullable) and the total
    PENDING volume this product handles doesn't justify a UNION's added
    complexity here. Revisit if the queue grows large enough for this
    in-memory merge+sort to matter.
    """
    reviews = (
        (await db.execute(select(Review).where(Review.status == ReviewStatus.pending)))
        .scalars()
        .all()
    )
    events = (
        (await db.execute(select(LayoffEvent).where(LayoffEvent.status == ReviewStatus.pending)))
        .scalars()
        .all()
    )

    entries = [
        ModerationQueueEntry(
            item_type=ModeratedItemType.review,
            item_id=r.id,
            company_id=r.company_id,
            flagged_reason=r.flagged_reason,
            status=r.status,
            preview_text=r.prose,
            created_at=r.created_at,
        )
        for r in reviews
    ] + [
        ModerationQueueEntry(
            item_type=ModeratedItemType.layoff_event,
            item_id=e.id,
            company_id=e.company_id,
            flagged_reason=e.flagged_reason,
            status=e.status,
            preview_text=e.department,
            created_at=e.created_at,
        )
        for e in events
    ]

    # Flagged first (flagged_reason is not None), then oldest created_at
    # first within each group — "sorted by flagged_reason first (if
    # present) then created_at" per the brief.
    entries.sort(key=lambda entry: (entry.flagged_reason is None, entry.created_at))

    total = len(entries)
    page = entries[offset : offset + limit]

    return PaginatedModerationQueue(items=page, total=total, limit=limit, offset=offset)


async def _load_item(db: AsyncSession, item_type: ModeratedItemType, item_id: uuid.UUID):
    model = Review if item_type == ModeratedItemType.review else LayoffEvent
    item = (await db.execute(select(model).where(model.id == item_id))).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"{item_type.value} not found"
        )
    if item.status != ReviewStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{item_type.value} is not pending moderation (status={item.status.value})",
        )
    return item


@router.post("/moderation-queue/{item_type}/{item_id}/approve", response_model=ModerationActionOut)
async def approve_moderation_item(
    item_type: ModeratedItemType,
    item_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ModerationActionOut:
    item = await _load_item(db, item_type, item_id)
    item.status = ReviewStatus.published

    db.add(
        ModerationAuditLogEntry(
            id=uuid.uuid4(),
            actor_admin_id=admin.id,
            item_type=item_type,
            item_id=item_id,
            action=ModerationAction.approve,
            reason=None,
            created_at=_now(),
        )
    )
    await db.commit()

    return ModerationActionOut(
        item_type=item_type,
        item_id=item_id,
        status=ReviewStatus.published,
        action=ModerationAction.approve,
    )


@router.post("/moderation-queue/{item_type}/{item_id}/reject", response_model=ModerationActionOut)
async def reject_moderation_item(
    item_type: ModeratedItemType,
    item_id: uuid.UUID,
    body: ModerationRejectIn,
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ModerationActionOut:
    item = await _load_item(db, item_type, item_id)
    item.status = ReviewStatus.rejected

    db.add(
        ModerationAuditLogEntry(
            id=uuid.uuid4(),
            actor_admin_id=admin.id,
            item_type=item_type,
            item_id=item_id,
            action=ModerationAction.reject,
            reason=body.reason,
            created_at=_now(),
        )
    )
    await db.commit()

    return ModerationActionOut(
        item_type=item_type,
        item_id=item_id,
        status=ReviewStatus.rejected,
        action=ModerationAction.reject,
    )


# --------------------------------------------------------------------------
# Tier-3 document moderation queue
# --------------------------------------------------------------------------
#
# Closes a gap left open in the initial Phase 4 pass: `ModerationQueueItem`
# (Phase 1) had no admin route to actually approve/reject an uploaded
# document. Kept as its own set of routes rather than folded into
# `/moderation-queue` above — see the schema module docstring in
# app.schemas.admin for why the shapes don't unify cleanly — but follows
# the identical `get_current_admin` + audit-log pattern.


@router.get("/document-queue", response_model=PaginatedDocumentQueue)
async def get_document_queue(
    limit: int = Query(default=20, ge=1, le=_MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> PaginatedDocumentQueue:
    base_filter = ModerationQueueItem.status == ModerationStatus.pending

    total = (
        await db.execute(select(func.count()).select_from(ModerationQueueItem).where(base_filter))
    ).scalar_one()

    result = await db.execute(
        select(ModerationQueueItem)
        .where(base_filter)
        .order_by(ModerationQueueItem.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    items = result.scalars().all()

    return PaginatedDocumentQueue(
        items=[
            DocumentQueueEntry(
                id=i.id,
                user_id=i.user_id,
                doc_type=i.doc_type,
                status=i.status,
                created_at=i.created_at,
            )
            for i in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


async def _load_document_item(db: AsyncSession, item_id: uuid.UUID) -> ModerationQueueItem:
    item = (
        await db.execute(select(ModerationQueueItem).where(ModerationQueueItem.id == item_id))
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="document queue item not found"
        )
    if item.status != ModerationStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"document queue item is not pending moderation (status={item.status.value})",
        )
    return item


@router.post("/document-queue/{item_id}/approve", response_model=DocumentModerationActionOut)
async def approve_document(
    item_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> DocumentModerationActionOut:
    item = await _load_document_item(db, item_id)

    user = (await db.execute(select(User).where(User.id == item.user_id))).scalar_one_or_none()
    if user is None:
        # Shouldn't happen (FK is ON DELETE CASCADE), but don't silently
        # publish a decision with nothing to apply it to.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="associated user not found"
        )

    # Tier 3 = the top of the verification ladder (VerificationTier.document
    # — see app.models.enums). require_tier(VerificationTier.document)
    # gates on this exact column, so bumping it here is what actually
    # unlocks Tier-3 routes for the user.
    user.verification_tier = VerificationTier.document
    item.status = ModerationStatus.approved
    item.reviewed_at = _now()

    # Hash-and-delete per the Phase 1 ephemeral-storage contract: the
    # plaintext document has done its job (a human reviewer looked at it
    # via `ephemeral_path`) and must not linger past the decision.
    if item.ephemeral_path is not None:
        delete_ephemeral_file(item.ephemeral_path)
        item.ephemeral_path = None

    db.add(
        ModerationAuditLogEntry(
            id=uuid.uuid4(),
            actor_admin_id=admin.id,
            item_type=ModeratedItemType.document,
            item_id=item_id,
            action=ModerationAction.approve,
            reason=None,
            created_at=_now(),
        )
    )
    await db.commit()

    return DocumentModerationActionOut(
        id=item_id,
        user_id=user.id,
        status=ModerationStatus.approved,
        action=ModerationAction.approve,
    )


@router.post("/document-queue/{item_id}/reject", response_model=DocumentModerationActionOut)
async def reject_document(
    item_id: uuid.UUID,
    body: ModerationRejectIn,
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> DocumentModerationActionOut:
    item = await _load_document_item(db, item_id)

    item.status = ModerationStatus.rejected
    item.reviewed_at = _now()

    # Same hash-and-delete discipline as approval — a rejected document
    # gets no special retention either.
    if item.ephemeral_path is not None:
        delete_ephemeral_file(item.ephemeral_path)
        item.ephemeral_path = None

    db.add(
        ModerationAuditLogEntry(
            id=uuid.uuid4(),
            actor_admin_id=admin.id,
            item_type=ModeratedItemType.document,
            item_id=item_id,
            action=ModerationAction.reject,
            reason=body.reason,
            created_at=_now(),
        )
    )
    await db.commit()

    return DocumentModerationActionOut(
        id=item_id,
        user_id=item.user_id,
        status=ModerationStatus.rejected,
        action=ModerationAction.reject,
    )


# --------------------------------------------------------------------------
# Grievance triage
# --------------------------------------------------------------------------


@router.get("/grievances", response_model=PaginatedGrievances)
async def list_grievances(
    limit: int = Query(default=20, ge=1, le=_MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> PaginatedGrievances:
    total_count = (
        await db.execute(select(func.count()).select_from(GrievanceComplaint))
    ).scalar_one()

    result = await db.execute(
        select(GrievanceComplaint)
        .order_by(GrievanceComplaint.sla_deadline.asc())
        .limit(limit)
        .offset(offset)
    )
    complaints = result.scalars().all()

    now = _now()
    items = [
        GrievanceComplaintAdminRead(
            id=c.id,
            complainant_contact=c.complainant_contact,
            subject=c.subject,
            description=c.description,
            related_item_type=c.related_item_type,
            related_item_id=c.related_item_id,
            status=c.status,
            sla_deadline=c.sla_deadline,
            created_at=c.created_at,
            past_deadline=c.sla_deadline < now,
        )
        for c in complaints
    ]

    return PaginatedGrievances(items=items, total=total_count, limit=limit, offset=offset)
