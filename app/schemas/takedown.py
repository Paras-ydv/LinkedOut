"""Pydantic schemas for the public takedown log."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ModeratedItemType, TakedownRequesterType
from app.models.takedown import REASON_MAX_LEN, REQUESTER_DETAIL_MAX_LEN


class TakedownLogEntryCreate(BaseModel):
    """Admin-only creation of a takedown-log entry.

    `requester_detail` is free text (e.g. a case/order number) but must
    never contain anything that could re-identify the underlying
    reviewer — that's an operator-discipline requirement (documented
    here, not app-enforced, since "does this re-identify someone" isn't
    mechanically checkable), matching how `app.models.takedown` is
    documented.
    """

    item_type: ModeratedItemType
    item_id: uuid.UUID
    requester_type: TakedownRequesterType
    requester_detail: str | None = Field(default=None, max_length=REQUESTER_DETAIL_MAX_LEN)
    complied: bool
    reason: str = Field(..., min_length=1, max_length=REASON_MAX_LEN)


class TakedownLogEntryOut(BaseModel):
    id: uuid.UUID
    item_type: ModeratedItemType
    item_id: uuid.UUID
    requester_type: TakedownRequesterType
    requester_detail: str | None
    complied: bool
    reason: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedTakedownLog(BaseModel):
    items: list[TakedownLogEntryOut]
    total: int
    limit: int
    offset: int
