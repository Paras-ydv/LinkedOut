"""Pydantic schemas for employer accounts and responses."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.employer import RESPONSE_TEXT_MAX_LEN


class EmployerLoginIn(BaseModel):
    """Phase 2 employer login stub.

    Full employer signup/domain-verification is out of scope for this
    phase — this exchanges a corporate email for a session token only if
    a *pre-seeded, already-verified* `EmployerAccount` exists whose
    `domain_hash` matches. There is no self-serve way to create or verify
    an EmployerAccount yet.
    """

    email: str = Field(..., description="Corporate email at the employer's verified domain")


class EmployerLoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    employer_account_id: uuid.UUID
    company_id: uuid.UUID


class EmployerResponseCreate(BaseModel):
    response_text: str = Field(..., min_length=1, max_length=RESPONSE_TEXT_MAX_LEN)


class EmployerResponseRead(BaseModel):
    id: uuid.UUID
    review_id: uuid.UUID
    response_text: str
    created_at: datetime

    model_config = {"from_attributes": True}
