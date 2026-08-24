"""Phone OTP model (Tier 1).

Hard constraint: this table never stores a plaintext phone number or a
plaintext OTP. `phone_hash` is the same deterministic HMAC used on `User`
(so a row can be looked up/rate-limited without the plaintext phone).
`otp_hash` is a *keyed* hash of the OTP code itself (HMAC with the same
server pepper) — even though OTPs are short numeric codes, this keeps a
database-only attacker from reading valid codes out of the table directly;
they'd still need the pepper to brute-force the 10^6 code space, and the
3-attempt cap (enforced in the router, not here) is what actually makes
online guessing infeasible.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OTPCode(Base):
    __tablename__ = "otp_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # HMAC-SHA256 hash of the (normalized) phone number. Never plaintext.
    phone_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # HMAC-SHA256 hash of the OTP code. Never plaintext.
    otp_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return f"<OTPCode id={self.id} phone_hash={self.phone_hash[:8]}...>"


class EmailVerificationCode(Base):
    """Corporate email verification code (Tier 2).

    Same hash-only pattern as `OTPCode`. `user_id` links it to the user who
    is upgrading tiers (that user already holds a Tier-1 JWT by the time a
    row here is created — enforced by the router dependency, not this
    model). The plaintext email is never persisted anywhere, including
    here; only the eventual `domain_hash` written to `User` survives
    verification.
    """

    __tablename__ = "email_verification_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # HMAC-SHA256 hash of the full lower-cased email address. Used only to
    # verify the code was requested for the email being confirmed now;
    # never exposed, never joined against for lookups outside this flow.
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # HMAC-SHA256 hash of the email's domain (e.g. hash("acme.com")).
    # Copied onto `User.email_domain_hash` on successful verification for
    # company-matching/analytics.
    domain_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # HMAC-SHA256 hash of the verification code. Never plaintext.
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return f"<EmailVerificationCode id={self.id} user_id={self.user_id}>"
