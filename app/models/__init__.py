"""ORM models package.

Every model module is imported here so that (a) `Base.metadata` is fully
populated for Alembic autogenerate, and (b) application code can do
`from app.models import User, Company`.
"""

from app.models.base import Base
from app.models.company import Company
from app.models.enums import (
    DocumentType,
    EmployeeSizeBucket,
    ModerationStatus,
    VerificationTier,
)
from app.models.moderation import ModerationQueueItem
from app.models.otp import EmailVerificationCode, OTPCode
from app.models.user import User

__all__ = [
    "Base",
    "Company",
    "User",
    "VerificationTier",
    "EmployeeSizeBucket",
    "DocumentType",
    "ModerationStatus",
    "OTPCode",
    "EmailVerificationCode",
    "ModerationQueueItem",
]
