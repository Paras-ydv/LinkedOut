"""Pydantic schemas for reviews and corroborations."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ExitReason, ReviewStatus, RoleLevel, TenureBucket
from app.models.review import CORROBORATION_COMMENT_MAX_LEN, DEPARTMENT_MAX_LEN, PROSE_MAX_LEN


class ReviewCreate(BaseModel):
    company_id: uuid.UUID
    exit_reason: ExitReason
    tenure_bucket: TenureBucket
    department: str = Field(..., min_length=1, max_length=DEPARTMENT_MAX_LEN)
    role_level: RoleLevel
    is_current_employee: bool
    prose: str = Field(..., min_length=1, max_length=PROSE_MAX_LEN)


class ReviewRead(BaseModel):
    """Public shape of a review. No `user_id` — reviewer identity is never exposed."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    exit_reason: ExitReason
    tenure_bucket: TenureBucket
    department: str
    role_level: RoleLevel
    is_current_employee: bool
    prose: str
    status: ReviewStatus
    created_at: datetime


class ReviewCreateOut(BaseModel):
    """Response to the submitter right after posting — includes status so
    they know it's pending review, unlike the public list which only ever
    shows published reviews at all.
    """

    id: uuid.UUID
    status: ReviewStatus
    message: str = "review submitted and pending moderation"


class PaginatedReviews(BaseModel):
    items: list[ReviewRead]
    total: int
    limit: int
    offset: int


class CorroborationCreate(BaseModel):
    comment: str | None = Field(default=None, max_length=CORROBORATION_COMMENT_MAX_LEN)


class CorroborationCreateOut(BaseModel):
    id: uuid.UUID
    message: str = "corroboration recorded"


class CorroborationRead(BaseModel):
    """Comment only — no user identity, per spec."""

    comment: str | None
    created_at: datetime


class PaginatedCorroborations(BaseModel):
    count: int
    items: list[CorroborationRead]
    limit: int
    offset: int
