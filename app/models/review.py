"""Review and Corroboration models (Phase 2: Core Review Flow).

`department` is free text, capped at 100 chars (see the Phase-2 design
note in the task write-up: a fixed enum was considered and rejected —
org structures vary too much across companies to force into one generic
list). Because it's free text, it needs to go through the same
pre-publication moderation/profanity scanning as `prose` once Phase 4
wires up the moderation queue — flagging that here since it's easy to
forget when only `prose` looks like "content".

`status` starts PENDING for every review and nothing in this phase ever
flips it — Phase 4 wires the moderation queue (including the
pre-publication name filter) that transitions PENDING -> PUBLISHED /
REJECTED. See the TODO in `app.routers.reviews.submit_review`.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean as SABoolean
from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import ExitReason, ReviewStatus, RoleLevel, TenureBucket

DEPARTMENT_MAX_LEN = 100
PROSE_MAX_LEN = 500
CORROBORATION_COMMENT_MAX_LEN = 200


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        # One review per user per company: stops a single account from
        # flooding one company's stats with repeat submissions.
        UniqueConstraint("user_id", "company_id", name="uq_reviews_user_company"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    exit_reason: Mapped[ExitReason] = mapped_column(
        SAEnum(
            ExitReason,
            name="exit_reason",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    tenure_bucket: Mapped[TenureBucket] = mapped_column(
        SAEnum(
            TenureBucket,
            name="tenure_bucket",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )

    # Free text, capped — see module docstring re: moderation scanning.
    department: Mapped[str] = mapped_column(String(DEPARTMENT_MAX_LEN), nullable=False)

    role_level: Mapped[RoleLevel] = mapped_column(
        SAEnum(
            RoleLevel,
            name="role_level",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    is_current_employee: Mapped[bool] = mapped_column(SABoolean, nullable=False)

    prose: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[ReviewStatus] = mapped_column(
        SAEnum(
            ReviewStatus,
            name="review_status",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ReviewStatus.pending,
        server_default=ReviewStatus.pending.value,
    )

    # Set by the Phase 4 pre-publication name-detection filter
    # (app.core.moderation_filter) when it flags this review for human
    # review. NULL means the filter passed clean — status is still PENDING
    # either way; a filter pass never auto-publishes (see
    # app.routers.reviews.submit_review). A non-NULL value routes this row
    # to the front of the moderation queue (see app.routers.admin).
    flagged_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return f"<Review id={self.id} company_id={self.company_id} status={self.status}>"


class Corroboration(Base):
    """A second user backing up someone else's review ("this matches my experience too").

    No user identity is ever exposed alongside a corroboration in API
    responses (see `GET /reviews/{id}/corroborations`) — only the
    (optional) comment text and an aggregate count.
    """

    __tablename__ = "corroborations"
    __table_args__ = (
        # One corroboration per user per review.
        UniqueConstraint("review_id", "user_id", name="uq_corroborations_review_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    comment: Mapped[str | None] = mapped_column(
        String(CORROBORATION_COMMENT_MAX_LEN), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return f"<Corroboration id={self.id} review_id={self.review_id}>"
