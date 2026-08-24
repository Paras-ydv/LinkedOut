"""Pydantic schemas for Company.

There is intentionally no `CompanyCreate` schema exposed on any public
router — companies are seeded, not user-created. This module only defines
read/response shapes for Phase 0.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import EmployeeSizeBucket


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    industry: str | None = None
    hq_location: str | None = None
    employee_size_bucket: EmployeeSizeBucket | None = None
    logo_url: str | None = None
    description: str | None = None
    created_at: datetime

    # Note: `corporate_email_domains` is deliberately excluded from the
    # public read schema — it's used server-side to match verified emails
    # to a company and isn't user-facing data.
