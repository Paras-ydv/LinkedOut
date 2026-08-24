"""Public takedown log (Phase 4).

`GET /takedown-log` is genuinely public and unauthenticated — no bearer
token, no admin dependency, nothing. This is a deliberate trust feature:
anyone can verify the platform publishes a record of every formal
takedown request it receives and whether it complied. `POST
/admin/takedown-log` is the only way entries get created, and it's
admin-only (see app.core.deps.get_current_admin).
"""

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_admin
from app.models.admin import AdminUser
from app.models.takedown import TakedownLogEntry
from app.schemas.takedown import PaginatedTakedownLog, TakedownLogEntryCreate, TakedownLogEntryOut

router = APIRouter(tags=["takedown-log"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])

_MAX_PAGE_SIZE = 100


@router.get("/takedown-log", response_model=PaginatedTakedownLog)
async def list_takedown_log(
    limit: int = Query(default=20, ge=1, le=_MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PaginatedTakedownLog:
    # No `Depends(get_current_admin)` or any auth dependency anywhere in
    # this function — that's the point.
    total = (await db.execute(select(func.count()).select_from(TakedownLogEntry))).scalar_one()

    result = await db.execute(
        select(TakedownLogEntry)
        .order_by(TakedownLogEntry.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    entries = result.scalars().all()

    return PaginatedTakedownLog(
        items=[TakedownLogEntryOut.model_validate(e) for e in entries],
        total=total,
        limit=limit,
        offset=offset,
    )


@admin_router.post(
    "/takedown-log", response_model=TakedownLogEntryOut, status_code=status.HTTP_201_CREATED
)
async def create_takedown_log_entry(
    body: TakedownLogEntryCreate,
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> TakedownLogEntryOut:
    entry = TakedownLogEntry(
        id=uuid.uuid4(),
        item_type=body.item_type,
        item_id=body.item_id,
        requester_type=body.requester_type,
        requester_detail=body.requester_detail,
        complied=body.complied,
        reason=body.reason,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    return TakedownLogEntryOut.model_validate(entry)
