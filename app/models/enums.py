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
