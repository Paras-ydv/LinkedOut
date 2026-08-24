"""AdminUser model (Phase 4: Moderation & Compliance).

Deliberately separate from `User`: an admin is an internal operator
account, not a verified-tier reviewer, so it carries none of the
phone/email/document verification-tier machinery. Auth is a simple
email + password-hash pair (see `app.core.security.hash_password` /
`verify_password`, PBKDF2-HMAC-SHA256 — stdlib only, no new dependency)
plus a dedicated JWT token type (`TokenType.admin`, see app.core.jwt),
mirroring the existing `EmployerAccount` pattern used in Phase 2.

There is no self-serve admin signup route in this phase — AdminUser rows
are seeded directly (same posture as EmployerAccount in Phase 2).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Plaintext admin email is fine to store here: this is a small internal
    # operator account, not anonymous-reviewer PII subject to the
    # hash-and-discard rule the rest of this project applies to
    # phone/corporate-email verification.
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)

    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return f"<AdminUser id={self.id} email={self.email!r}>"
