"""Company model.

IMPORTANT: companies are seeded (via a seed script / admin process) from a
curated list — there is no user-facing "create company" endpoint, and no
router in this project should expose free-text company creation. This
model only defines the *storage shape* of a seeded company; enforcing
"seeded only" is a routing/permissions concern, not a schema concern.
"""

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import EmployeeSizeBucket


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Core identity
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Corporate email domain(s) used to match a user's verified corporate
    # email (tier 2) to this seeded company. Domains only — never an actual
    # email address, and never populated from user input.
    corporate_email_domains: Mapped[list[str]] = mapped_column(
        ARRAY(String(255)), nullable=False, default=list, server_default="{}"
    )

    # Size / HQ metadata, for aggregate-stat context (e.g. filtering by size)
    employee_size_bucket: Mapped[EmployeeSizeBucket | None] = mapped_column(
        # NOTE: intentionally NOT using values_callable here, unlike the
        # Phase 2 enums below — migration 0001 already created this native
        # Postgres enum type using the Python enum's *member names*
        # (micro/small/medium/...), not `.value` ("1-10"/"11-50"/...).
        # Adding values_callable now would desync the model from the type
        # that migration actually created. Left as a known Phase 0
        # inconsistency rather than risking a migration mismatch here.
        SAEnum(EmployeeSizeBucket, name="employee_size_bucket", native_enum=True),
        nullable=True,
    )
    hq_location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Display metadata
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return f"<Company id={self.id} slug={self.slug!r}>"
