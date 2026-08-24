"""EmployerAccount and EmployerResponse models (Phase 2: Core Review Flow).

`EmployerAccount.domain_hash` follows the exact same HMAC-SHA256 pattern
as `User.email_domain_hash` (see app.core.security.hash_domain) — an
employer account is tied to a company via its verified corporate email
domain, hashed the same way, never stored in plaintext.

Full employer signup/domain-verification is out of scope for Phase 2 (see
app.routers.employer for the minimal login stub); `verified` exists now
so the real flow has somewhere to land later without a schema change.

No DELETE route exists for `EmployerResponse` anywhere in this phase —
responses are permanent once posted.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

RESPONSE_TEXT_MAX_LEN = 1000


class EmployerAccount(Base):
    __tablename__ = "employer_accounts"
    __table_args__ = (
        # One employer account per company.
        UniqueConstraint("company_id", name="uq_employer_accounts_company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # HMAC-SHA256 hash of the corporate email domain this account was
    # verified against (same construction/pepper as User.email_domain_hash
    # — see app.core.security.hash_domain). Never a plaintext domain.
    domain_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return (
            f"<EmployerAccount id={self.id} company_id={self.company_id} verified={self.verified}>"
        )


class EmployerResponse(Base):
    __tablename__ = "employer_responses"
    __table_args__ = (
        # One response per review.
        UniqueConstraint("review_id", name="uq_employer_responses_review_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employer_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employer_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    response_text: Mapped[str] = mapped_column(String(RESPONSE_TEXT_MAX_LEN), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return f"<EmployerResponse id={self.id} review_id={self.review_id}>"
