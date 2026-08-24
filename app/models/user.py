"""User model.

Hard constraint: this table stores NO plaintext PII. There is no `phone`,
`email`, or document column here — only `phone_hash`, produced by
`app.core.security.hash_phone` before this row is ever written. Verified
corporate email and document data (tiers 2/3) follow the same
verify-then-hash-then-discard pattern and are added to this model in a
later phase as additional hash columns, never as plaintext columns.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import VerificationTier


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # HMAC-SHA256 hash of the user's phone number (see app.core.security).
    # Never a plaintext phone number.
    phone_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    # HMAC-SHA256 hash of the verified corporate email's domain (e.g.
    # hash("acme.com")), set on Tier-2 verification. Never the email
    # itself, and never even the domain in plaintext — only used for
    # company-matching/analytics by comparing hashes. Not unique: many
    # users share a domain.
    email_domain_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    verification_tier: Mapped[VerificationTier] = mapped_column(
        SAEnum(VerificationTier, name="verification_tier", native_enum=True),
        nullable=False,
        default=VerificationTier.unverified,
        server_default=VerificationTier.unverified.value,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return f"<User id={self.id} tier={self.verification_tier}>"
