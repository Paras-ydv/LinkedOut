"""Tier 3 (document) moderation queue.

Hard constraint: the uploaded document itself is never written to
permanent storage in this table or anywhere else. `content_hash` is a
plain SHA-256 of the file bytes, used only for dedup (has this exact file
already been submitted?) — it does not need to be keyed/HMAC'd like PII
hashes, because a document's byte space is astronomically larger than a
phone number's, so there's no realistic rainbow-table/brute-force risk.

`ephemeral_path` points at a short-lived temp file (see
`app.providers.document`) that a human reviewer's tooling reads directly;
it is deleted the moment a review decision is made (approve or reject),
never left around.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import DocumentType, ModerationStatus


class ModerationQueueItem(Base):
    __tablename__ = "moderation_queue"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    doc_type: Mapped[DocumentType] = mapped_column(
        SAEnum(DocumentType, name="document_type", native_enum=True), nullable=False
    )

    # SHA-256 of the raw file bytes. Dedup key only — not PII-sensitive on
    # its own, but still never paired with the plaintext file at rest.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Path to the ephemeral temp file holding the plaintext document, or
    # NULL once it's been deleted (on approval/rejection, or by the
    # background reaper for anything left past its TTL). Never a permanent
    # disk/S3 path.
    ephemeral_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    status: Mapped[ModerationStatus] = mapped_column(
        SAEnum(ModerationStatus, name="moderation_status", native_enum=True),
        nullable=False,
        default=ModerationStatus.pending,
        server_default=ModerationStatus.pending.value,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return f"<ModerationQueueItem id={self.id} status={self.status}>"
