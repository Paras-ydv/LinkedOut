"""Pydantic schemas for grievance-officer intake (2026 IT Rules)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import GrievanceStatus, ModeratedItemType
from app.models.grievance import CONTACT_MAX_LEN, DESCRIPTION_MAX_LEN, SUBJECT_MAX_LEN


class GrievanceComplaintCreate(BaseModel):
    # A plain-str field with a minimal `@`-presence check rather than
    # Pydantic's `EmailStr`, which needs the `email-validator` extra —
    # not worth a new dependency for one field in a portfolio project.
    complainant_contact: str = Field(..., min_length=3, max_length=CONTACT_MAX_LEN)
    subject: str = Field(..., min_length=1, max_length=SUBJECT_MAX_LEN)
    description: str = Field(..., min_length=1, max_length=DESCRIPTION_MAX_LEN)
    related_item_type: ModeratedItemType | None = None
    related_item_id: uuid.UUID | None = None
    # Complainant-asserted flag: true routes the SLA to the 3-hour
    # court/government-matter track instead of the default 7-day track.
    # This is a self-report, not a verified classification — a human
    # reviewer (see GET /admin/grievances) still triages every complaint;
    # the point of the flag is only to get genuinely urgent matters to
    # the top of that queue fast.
    is_court_or_government_matter: bool = False

    @field_validator("complainant_contact")
    @classmethod
    def _looks_like_email(cls, v: str) -> str:
        if "@" not in v or v.startswith("@") or v.endswith("@"):
            raise ValueError("complainant_contact must be a valid email address")
        return v


class GrievanceComplaintOut(BaseModel):
    """Returned to the complainant right after submission."""

    id: uuid.UUID
    status: GrievanceStatus
    sla_deadline: datetime
    message: str = "complaint received and acknowledged"


class GrievanceComplaintAdminRead(BaseModel):
    id: uuid.UUID
    complainant_contact: str
    subject: str
    description: str
    related_item_type: ModeratedItemType | None
    related_item_id: uuid.UUID | None
    status: GrievanceStatus
    sla_deadline: datetime
    created_at: datetime
    past_deadline: bool

    model_config = {"from_attributes": True}


class PaginatedGrievances(BaseModel):
    items: list[GrievanceComplaintAdminRead]
    total: int
    limit: int
    offset: int
