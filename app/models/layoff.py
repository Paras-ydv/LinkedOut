"""LayoffEvent model (Phase 2: Core Review Flow).

Same moderation-pattern (`status` starts PENDING, Phase 4 flips it) and
same free-text-department caveat as `Review` — see app.models.review.

`source_url` is only meaningful when `source_type == NEWS`; nothing
enforces that at the DB layer (a CHECK constraint would work but adds
migration complexity for a rule the router already enforces on write —
see app.routers.layoff_events). `submitted_by_user_id` is nullable for
the same reason: NEWS-sourced entries have no submitting user (that path
is admin/internal-only and not exposed as a public endpoint in this
phase).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import LayoffSourceType, ReviewStatus
from app.models.review import DEPARTMENT_MAX_LEN


class LayoffEvent(Base):
    __tablename__ = "layoff_events"
    __table_args__ = (
        # Same rationale as Review.__table_args__'s composite index — see
        # app.models.review and Phase 5's migration 0006.
        Index("ix_layoff_events_company_id_status", "company_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    event_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    department: Mapped[str | None] = mapped_column(String(DEPARTMENT_MAX_LEN), nullable=True)

    estimated_headcount: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source_type: Mapped[LayoffSourceType] = mapped_column(
        SAEnum(
            LayoffSourceType,
            name="layoff_source_type",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

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

    # Same Phase 4 name-detection filter as Review.flagged_reason — see
    # app.models.review for the full note.
    flagged_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return f"<LayoffEvent id={self.id} company_id={self.company_id} status={self.status}>"
