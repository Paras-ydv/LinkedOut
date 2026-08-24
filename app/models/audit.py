"""ModerationAuditLogEntry model (Phase 4).

Internal audit trail of every approve/reject action an admin takes from
the moderation queue. Distinct from `TakedownLogEntry`
(app.models.takedown), which is the *public-facing* record of
formal takedown requests (court orders, government directions, etc.) —
this table is internal-only and has no public endpoint anywhere.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import ModeratedItemType, ModerationAction


class ModerationAuditLogEntry(Base):
    __tablename__ = "moderation_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    actor_admin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    item_type: Mapped[ModeratedItemType] = mapped_column(
        SAEnum(
            ModeratedItemType,
            name="moderated_item_type",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    action: Mapped[ModerationAction] = mapped_column(
        SAEnum(
            ModerationAction,
            name="moderation_action",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )

    # Mandatory for REJECT (enforced in the router, not the DB, matching
    # the rest of this codebase's pattern of app-level + unique-constraint
    # DB-level guards where cheap, and app-level-only where a CHECK would
    # need to be conditional on another column).
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return (
            f"<ModerationAuditLogEntry id={self.id} item_type={self.item_type} "
            f"item_id={self.item_id} action={self.action}>"
        )
