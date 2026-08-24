"""Public grievance-officer intake (Phase 4, 2026 IT Rules).

`POST /grievance` is public — anyone can lodge a complaint, no auth
required, matching the statutory intent of a grievance-officer channel.
It auto-acknowledges synchronously (sets status ACKNOWLEDGED immediately
and stubs a confirmation email) and computes `sla_deadline` at creation
time: 3 hours out if the complainant flags this as a court/government
matter, else 7 days, per the 2026 IT Rules distinction in the brief.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import RateLimitExceeded, enforce_rate_limit
from app.models.enums import GrievanceStatus
from app.models.grievance import GrievanceComplaint
from app.providers.email import ConsoleEmailProvider, EmailProvider
from app.schemas.grievance import GrievanceComplaintCreate, GrievanceComplaintOut

router = APIRouter(tags=["grievance"])

_URGENT_SLA = timedelta(hours=3)
_STANDARD_SLA = timedelta(days=7)

# Same swappable-provider pattern as Phase 1's OTP/verification email —
# "confirmation" is a stub send, never blocking, never logged with the
# complainant's plaintext address (the provider interface itself forbids
# that, see app.providers.email).
_email_provider: EmailProvider = ConsoleEmailProvider()


def _now() -> datetime:
    return datetime.now(UTC)


@router.post(
    "/grievance", response_model=GrievanceComplaintOut, status_code=status.HTTP_201_CREATED
)
async def submit_grievance(
    body: GrievanceComplaintCreate, db: AsyncSession = Depends(get_db)
) -> GrievanceComplaintOut:
    # Phase 5: same DB-backed rate-limit pattern as everywhere else in
    # this project, reused as-is. This endpoint is public/unauthenticated,
    # so there's no user id to key on — `complainant_contact` is the only
    # available signal, and it's already stored in plaintext on this table
    # (see app.models.grievance), so keying the rate-limit lookup on it
    # directly adds no new PII exposure. A determined abuser can rotate
    # the contact string trivially; this is a spam-friction ceiling, not a
    # security boundary — see TRUST_ARCHITECTURE.md.
    try:
        await enforce_rate_limit(
            db,
            model=GrievanceComplaint,
            key_column=GrievanceComplaint.complainant_contact,
            key_value=body.complainant_contact,
            window_minutes=settings.grievance_rate_limit_window_minutes,
            max_requests=settings.grievance_rate_limit_max_requests,
        )
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many grievance submissions recently, try again later",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    now = _now()
    sla_window = _URGENT_SLA if body.is_court_or_government_matter else _STANDARD_SLA
    sla_deadline = now + sla_window

    complaint = GrievanceComplaint(
        id=uuid.uuid4(),
        complainant_contact=body.complainant_contact,
        subject=body.subject,
        description=body.description,
        related_item_type=body.related_item_type,
        related_item_id=body.related_item_id,
        status=GrievanceStatus.acknowledged,
        sla_deadline=sla_deadline,
        created_at=now,
    )
    db.add(complaint)
    await db.commit()
    await db.refresh(complaint)

    # Stub confirmation send — see app.providers.email. Unlike Tier 2's
    # verification-code email, `complainant_contact` here is legitimate
    # plaintext business contact info (already persisted on `complaint`
    # above, per the brief), not anonymous-reviewer PII, so there's no
    # discard requirement on this call itself.
    await _email_provider.send_verification_code(
        body.complainant_contact, f"tracking id {complaint.id}"
    )

    return GrievanceComplaintOut(
        id=complaint.id, status=complaint.status, sla_deadline=complaint.sla_deadline
    )
