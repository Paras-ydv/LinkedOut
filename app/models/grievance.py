"""GrievanceComplaint model (Phase 4: 2026 IT Rules grievance-officer intake).

`complainant_contact` is stored in plaintext deliberately — per the task
brief, this is a legitimate business contact (someone formally lodging a
complaint expects to be reachable about it), not the anonymous-reviewer
PII the hash-and-discard rule elsewhere in this project protects.

`sla_deadline` is computed at creation time (see
app.routers.grievance.submit_grievance): 3 hours from `created_at` when
the complainant flags the matter as court/government-related, else 7
days, per the 2026 IT Rules intake SLA distinction in the brief.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import GrievanceStatus, ModeratedItemType

CONTACT_MAX_LEN = 255
SUBJECT_MAX_LEN = 200
DESCRIPTION_MAX_LEN = 2000


class GrievanceComplaint(Base):
    __tablename__ = "grievance_complaints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    complainant_contact: Mapped[str] = mapped_column(String(CONTACT_MAX_LEN), nullable=False)

    subject: Mapped[str] = mapped_column(String(SUBJECT_MAX_LEN), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    related_item_type: Mapped[ModeratedItemType | None] = mapped_column(
        SAEnum(
            ModeratedItemType,
            name="moderated_item_type",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
    )
    related_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    status: Mapped[GrievanceStatus] = mapped_column(
        SAEnum(
            GrievanceStatus,
            name="grievance_status",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=GrievanceStatus.received,
    )

    sla_deadline: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return (
            f"<GrievanceComplaint id={self.id} status={self.status} "
            f"sla_deadline={self.sla_deadline}>"
        )
