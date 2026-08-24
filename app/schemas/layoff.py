"""Pydantic schemas for layoff events."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import LayoffSourceType, ReviewStatus
from app.models.review import DEPARTMENT_MAX_LEN


class LayoffEventCreate(BaseModel):
    """Self-reported layoff event submission (POST /layoff-events).

    `source_type` is fixed to SELF_REPORTED for this public endpoint — see
    app.routers.layoff_events for the NEWS-sourced path, which has no
    public endpoint in this phase.
    """

    company_id: uuid.UUID
    event_date: datetime
    department: str | None = Field(default=None, max_length=DEPARTMENT_MAX_LEN)
    estimated_headcount: int | None = Field(default=None, ge=0)
    source_url: str | None = Field(default=None, max_length=1000)

    @field_validator("estimated_headcount")
    @classmethod
    def _non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("estimated_headcount must be >= 0")
        return v


class LayoffEventRead(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    event_date: datetime
    department: str | None
    estimated_headcount: int | None
    source_type: LayoffSourceType
    source_url: str | None
    status: ReviewStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class LayoffEventCreateOut(BaseModel):
    id: uuid.UUID
    status: ReviewStatus
    message: str = "layoff event submitted and pending moderation"


class PaginatedLayoffEvents(BaseModel):
    items: list[LayoffEventRead]
    total: int
    limit: int
    offset: int
