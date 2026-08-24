"""TakedownLogEntry model (Phase 4): the public trust/transparency log.

This is a differentiation feature, not an internal tool — see
`GET /takedown-log` in app.routers.takedown, which is genuinely public
and unauthenticated. It records that *a* takedown request of a given type
was made and whether it was complied with, without exposing anything that
could re-identify the underlying reviewer or the specific review content.

`requester_detail` is free text (e.g. a case number) but is explicitly
*not* the place for anything that could re-identify a reviewer — that's
an app-level discipline point (see the docstring on
`app.schemas.takedown.TakedownLogEntryCreate`), not something the DB
schema itself can enforce.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import ModeratedItemType, TakedownRequesterType

REQUESTER_DETAIL_MAX_LEN = 500
REASON_MAX_LEN = 1000


class TakedownLogEntry(Base):
    __tablename__ = "takedown_log_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

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

    requester_type: Mapped[TakedownRequesterType] = mapped_column(
        SAEnum(
            TakedownRequesterType,
            name="takedown_requester_type",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )

    requester_detail: Mapped[str | None] = mapped_column(
        String(REQUESTER_DETAIL_MAX_LEN), nullable=True
    )

    complied: Mapped[bool] = mapped_column(Boolean, nullable=False)

    reason: Mapped[str] = mapped_column(String(REASON_MAX_LEN), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return (
            f"<TakedownLogEntry id={self.id} item_type={self.item_type} "
            f"requester_type={self.requester_type} complied={self.complied}>"
        )
