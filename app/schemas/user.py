"""Pydantic schemas for User.

`phone_hash` is never included in any response schema — it's an internal
lookup key, not user-facing data, and exposing it would leak a stable
identifier tied to PII (even though it's a keyed hash).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import VerificationTier


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    verification_tier: VerificationTier
    created_at: datetime
