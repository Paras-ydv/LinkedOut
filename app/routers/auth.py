"""Three-tier auth & verification.

Tier 1 (phone OTP) -> Tier 2 (corporate email) -> Tier 3 (document review).
Each tier's endpoints require the JWT from the previous tier, so a caller
cannot skip ahead (`require_tier` checks the *current DB row*, not just
what an old token claims — see app.core.deps).

PII handling, repeated because it's the whole point of this module: raw
phone numbers, raw emails, and raw document bytes are received, used for
exactly the operation that needs them (hash for lookup/storage, or hand to
a provider for delivery/queuing), and then go out of scope. Nothing here
ever calls `logging`/`print` with a plaintext value, and nothing plaintext
is ever added to a SQLAlchemy model.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user, require_tier
from app.core.jwt import create_access_token, create_refresh_token
from app.core.rate_limit import RateLimitExceeded, enforce_rate_limit
from app.core.security import (
    generate_numeric_code,
    hash_code,
    hash_domain,
    hash_email,
    hash_phone,
    normalize_email,
    split_email_domain,
)
from app.models.enums import DocumentType, VerificationTier
from app.models.moderation import ModerationQueueItem
from app.models.otp import EmailVerificationCode, OTPCode
from app.models.user import User
from app.providers.document import ManualReviewDocumentProvider
from app.providers.email import ConsoleEmailProvider, EmailProvider
from app.providers.sms import ConsoleSMSProvider, SMSProvider
from app.schemas.auth import (
    DocumentUploadOut,
    EmailRequestIn,
    EmailRequestOut,
    EmailVerifyIn,
    EmailVerifyOut,
    OTPRequestIn,
    OTPRequestOut,
    OTPVerifyIn,
    OTPVerifyOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Provider instances. Swappable for real Twilio/MSG91/etc. implementations
# later without touching route logic — see app.providers.
_sms_provider: SMSProvider = ConsoleSMSProvider()
_email_provider: EmailProvider = ConsoleEmailProvider()
_document_provider = ManualReviewDocumentProvider()

_MAX_DOCUMENT_BYTES = 10 * 1024 * 1024  # 10 MiB


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------
# Tier 1: phone OTP
# --------------------------------------------------------------------------


@router.post("/otp/request", response_model=OTPRequestOut)
async def request_otp(body: OTPRequestIn, db: AsyncSession = Depends(get_db)) -> OTPRequestOut:
    try:
        phone_hash = hash_phone(body.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    try:
        await enforce_rate_limit(
            db,
            model=OTPCode,
            key_column=OTPCode.phone_hash,
            key_value=phone_hash,
            window_minutes=settings.otp_rate_limit_window_minutes,
            max_requests=settings.otp_rate_limit_max_requests,
        )
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many OTP requests for this phone number, try again later",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    code = generate_numeric_code(settings.otp_length)

    otp_row = OTPCode(
        id=uuid.uuid4(),
        phone_hash=phone_hash,
        otp_hash=hash_code(code),
        attempts=0,
        expires_at=_now() + timedelta(minutes=settings.otp_expire_minutes),
        created_at=_now(),
    )
    db.add(otp_row)
    await db.commit()

    # `body.phone` (plaintext) and `code` (plaintext) are used here, for
    # this one delivery call, and never touched again.
    await _sms_provider.send_otp(body.phone, code)

    return OTPRequestOut(expires_in_seconds=settings.otp_expire_minutes * 60)


@router.post("/otp/verify", response_model=OTPVerifyOut)
async def verify_otp(body: OTPVerifyIn, db: AsyncSession = Depends(get_db)) -> OTPVerifyOut:
    try:
        phone_hash = hash_phone(body.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    result = await db.execute(
        select(OTPCode)
        .where(OTPCode.phone_hash == phone_hash, OTPCode.consumed_at.is_(None))
        .order_by(OTPCode.created_at.desc())
        .limit(1)
    )
    otp_row = result.scalar_one_or_none()

    if otp_row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="no pending OTP for this phone"
        )

    if otp_row.expires_at < _now():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP expired")

    if otp_row.attempts >= settings.otp_max_attempts:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too many attempts"
        )

    if hash_code(body.code) != otp_row.otp_hash:
        otp_row.attempts += 1
        await db.commit()
        remaining = max(settings.otp_max_attempts - otp_row.attempts, 0)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"incorrect code, {remaining} attempt(s) remaining",
        )

    otp_row.consumed_at = _now()

    result = await db.execute(select(User).where(User.phone_hash == phone_hash))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            id=uuid.uuid4(), phone_hash=phone_hash, verification_tier=VerificationTier.phone
        )
        db.add(user)
    elif user.verification_tier == VerificationTier.unverified:
        user.verification_tier = VerificationTier.phone
    # If the user already reached a higher tier, verifying phone OTP again
    # (e.g. re-login) must not downgrade them.

    await db.commit()
    await db.refresh(user)

    return OTPVerifyOut(
        access_token=create_access_token(user.id, user.verification_tier),
        refresh_token=create_refresh_token(user.id, user.verification_tier),
        user_id=user.id,
        verification_tier=user.verification_tier,
    )


# --------------------------------------------------------------------------
# Tier 2: corporate email
# --------------------------------------------------------------------------


@router.post("/email/request", response_model=EmailRequestOut)
async def request_email_verification(
    body: EmailRequestIn,
    user: User = Depends(require_tier(VerificationTier.phone)),
    db: AsyncSession = Depends(get_db),
) -> EmailRequestOut:
    normalized = normalize_email(body.email)
    try:
        domain = split_email_domain(normalized)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    email_hash = hash_email(normalized)

    try:
        await enforce_rate_limit(
            db,
            model=EmailVerificationCode,
            key_column=EmailVerificationCode.user_id,
            key_value=str(user.id),
            window_minutes=settings.email_rate_limit_window_minutes,
            max_requests=settings.email_rate_limit_max_requests,
        )
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many verification requests, try again later",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    code = generate_numeric_code(settings.email_code_length)

    code_row = EmailVerificationCode(
        id=uuid.uuid4(),
        user_id=user.id,
        email_hash=email_hash,
        domain_hash=hash_domain(domain),
        code_hash=hash_code(code),
        attempts=0,
        expires_at=_now() + timedelta(minutes=settings.email_code_expire_minutes),
        created_at=_now(),
    )
    db.add(code_row)
    await db.commit()

    # `normalized` (plaintext email) and `code` are used here only.
    await _email_provider.send_verification_code(normalized, code)

    return EmailRequestOut(expires_in_seconds=settings.email_code_expire_minutes * 60)


@router.post("/email/verify", response_model=EmailVerifyOut)
async def verify_email(
    body: EmailVerifyIn,
    user: User = Depends(require_tier(VerificationTier.phone)),
    db: AsyncSession = Depends(get_db),
) -> EmailVerifyOut:
    normalized = normalize_email(body.email)
    try:
        split_email_domain(normalized)  # validate shape only
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    email_hash = hash_email(normalized)

    result = await db.execute(
        select(EmailVerificationCode)
        .where(
            EmailVerificationCode.user_id == user.id,
            EmailVerificationCode.email_hash == email_hash,
            EmailVerificationCode.consumed_at.is_(None),
        )
        .order_by(EmailVerificationCode.created_at.desc())
        .limit(1)
    )
    code_row = result.scalar_one_or_none()

    if code_row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="no pending verification for this email"
        )

    if code_row.expires_at < _now():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="verification code expired"
        )

    if code_row.attempts >= settings.otp_max_attempts:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too many attempts"
        )

    if hash_code(body.code) != code_row.code_hash:
        code_row.attempts += 1
        await db.commit()
        remaining = max(settings.otp_max_attempts - code_row.attempts, 0)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"incorrect code, {remaining} attempt(s) remaining",
        )

    code_row.consumed_at = _now()

    # `normalized` (plaintext email) is discarded after this point — only
    # `code_row.domain_hash` (already hashed) survives onto the user.
    user.email_domain_hash = code_row.domain_hash
    if user.verification_tier == VerificationTier.phone:
        user.verification_tier = VerificationTier.email

    await db.commit()
    await db.refresh(user)

    return EmailVerifyOut(
        access_token=create_access_token(user.id, user.verification_tier),
        refresh_token=create_refresh_token(user.id, user.verification_tier),
        user_id=user.id,
        verification_tier=user.verification_tier,
    )


# --------------------------------------------------------------------------
# Tier 3: document upload
# --------------------------------------------------------------------------


@router.post("/document/upload", response_model=DocumentUploadOut)
async def upload_document(
    doc_type: DocumentType,
    file: UploadFile = File(...),
    user: User = Depends(require_tier(VerificationTier.email)),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadOut:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty file")
    if len(content) > _MAX_DOCUMENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="file too large"
        )

    # `content` (raw document bytes) only ever lives in this in-memory
    # buffer; the provider writes it to an ephemeral temp path, never
    # permanent disk/S3.
    queued = await _document_provider.submit(user.id, doc_type, content)

    moderation_row = ModerationQueueItem(
        id=uuid.uuid4(),
        user_id=user.id,
        doc_type=doc_type,
        content_hash=queued.content_hash,
        ephemeral_path=queued.ephemeral_path,
        created_at=_now(),
    )
    db.add(moderation_row)
    await db.commit()
    await db.refresh(moderation_row)

    return DocumentUploadOut(
        moderation_id=moderation_row.id,
        doc_type=moderation_row.doc_type,
        status=moderation_row.status.value,
    )


@router.get("/me")
async def read_current_user(user: User = Depends(get_current_user)) -> dict:
    return {"user_id": str(user.id), "verification_tier": user.verification_tier.value}
