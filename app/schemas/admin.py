"""Pydantic schemas for admin auth and the moderation queue."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import (
    DocumentType,
    ModeratedItemType,
    ModerationAction,
    ModerationStatus,
    ReviewStatus,
)


class AdminLoginIn(BaseModel):
    email: str
    password: str = Field(..., min_length=1)


class AdminLoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    admin_id: uuid.UUID


class ModerationQueueEntry(BaseModel):
    """One PENDING review or layoff-event surfaced in the admin queue.

    Deliberately a flattened, item_type-tagged shape rather than two
    separate list endpoints — the queue's whole point (per the brief) is
    a single sorted view across both content types.
    """

    item_type: ModeratedItemType
    item_id: uuid.UUID
    company_id: uuid.UUID
    flagged_reason: str | None
    status: ReviewStatus
    # The free-text field most useful for a moderator's at-a-glance
    # triage: `prose` for a review, `department` for a layoff event.
    preview_text: str | None
    created_at: datetime


class PaginatedModerationQueue(BaseModel):
    items: list[ModerationQueueEntry]
    total: int
    limit: int
    offset: int


class ModerationRejectIn(BaseModel):
    reason: str = Field(..., min_length=1, description="Mandatory reason for rejection")


class ModerationActionOut(BaseModel):
    item_type: ModeratedItemType
    item_id: uuid.UUID
    status: ReviewStatus
    action: ModerationAction


# --------------------------------------------------------------------------
# Tier-3 document moderation queue
# --------------------------------------------------------------------------
#
# Kept as its own set of schemas rather than folded into
# `ModerationQueueEntry` above: `ModerationQueueItem` has a different
# shape (no `company_id`, its own `ModerationStatus` enum distinct from
# `ReviewStatus`, and no "preview text" — the content is a document, not
# free text) and a different admin action (bumping a user's verification
# tier, not publishing content), so forcing it into the review/layoff
# shape would mean a pile of always-null fields on one side or the other.


class DocumentQueueEntry(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    doc_type: DocumentType
    status: ModerationStatus
    created_at: datetime


class PaginatedDocumentQueue(BaseModel):
    items: list[DocumentQueueEntry]
    total: int
    limit: int
    offset: int


class DocumentModerationActionOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    status: ModerationStatus
    action: ModerationAction
