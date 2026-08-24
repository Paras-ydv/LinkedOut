"""Shared enum types used across models.

These are plain `str` enums so they serialize cleanly through Pydantic and
map to native Postgres ENUM types via SQLAlchemy.
"""

import enum


class VerificationTier(str, enum.Enum):
    """Where a user is on the auth ladder: phone OTP -> corporate email -> document."""

    unverified = "unverified"
    phone = "phone"
    email = "email"
    document = "document"


class EmployeeSizeBucket(str, enum.Enum):
    """Coarse company size bucket, for seeded company metadata / aggregate stats."""

    micro = "1-10"
    small = "11-50"
    medium = "51-200"
    large = "201-1000"
    enterprise = "1000+"


class DocumentType(str, enum.Enum):
    """Kind of document submitted for Tier 3 verification."""

    offer_letter = "offer_letter"
    payslip = "payslip"
    id_document = "id_document"
    other = "other"


class ModerationStatus(str, enum.Enum):
    """Review state of a Tier 3 document sitting in the moderation queue."""

    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ExitReason(str, enum.Enum):
    """Primary reason a reviewer gives for leaving (Phase 2 review submission)."""

    management = "MANAGEMENT"
    compensation = "COMPENSATION"
    layoffs = "LAYOFFS"
    culture = "CULTURE"
    growth = "GROWTH"
    relocation = "RELOCATION"
    other = "OTHER"


class TenureBucket(str, enum.Enum):
    """Coarse length-of-employment bucket for a review."""

    less_than_1yr = "LESS_THAN_1YR"
    one_to_3yr = "ONE_TO_3YR"
    three_to_5yr = "THREE_TO_5YR"
    five_plus_yr = "FIVE_PLUS_YR"


class RoleLevel(str, enum.Enum):
    """Reviewer's seniority level."""

    ic = "IC"
    manager = "MANAGER"
    senior_manager = "SENIOR_MANAGER"
    director_plus = "DIRECTOR_PLUS"


class ReviewStatus(str, enum.Enum):
    """Publication state shared by Review and LayoffEvent.

    PENDING -> PUBLISHED/REJECTED via the moderation queue wired up in
    Phase 4 (the pre-publication name filter also lands there). Every
    review/layoff-event is created PENDING; nothing here flips it.
    """

    pending = "PENDING"
    published = "PUBLISHED"
    rejected = "REJECTED"


class LayoffSourceType(str, enum.Enum):
    """Where a LayoffEvent's data came from."""

    self_reported = "SELF_REPORTED"
    news = "NEWS"
