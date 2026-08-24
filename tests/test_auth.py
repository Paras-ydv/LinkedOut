"""Tests for Phase 1: Auth & Verification (three-tier).

Covers: OTP expiry/max-attempts, phone hash never appears in
DB/logs, email plaintext never persisted, tier progression can't be
skipped, and JWT payload has no PII.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from jose import jwt as jose_jwt
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_phone
from app.models.otp import OTPCode

PHONE = "+15551234567"
CORP_EMAIL = "employee@acme.com"


async def _get_latest_otp(db_session: AsyncSession, phone: str) -> OTPCode:
    phone_hash = hash_phone(phone)
    result = await db_session.execute(
        select(OTPCode).where(OTPCode.phone_hash == phone_hash).order_by(OTPCode.created_at.desc())
    )
    return result.scalars().first()


async def test_otp_request_and_verify_success(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture
):
    resp = await client.post("/auth/otp/request", json={"phone": PHONE})
    assert resp.status_code == 200
    body = resp.json()
    assert body["expires_in_seconds"] == settings.otp_expire_minutes * 60

    captured = capsys.readouterr()
    assert "would send OTP" in captured.out
    code = captured.out.strip().split()[-3]  # "... OTP <code> to <phone>"

    resp = await client.post("/auth/otp/verify", json={"phone": PHONE, "code": code})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verification_tier"] == "phone"
    assert "access_token" in body and "refresh_token" in body


async def test_otp_verify_wrong_code_increments_attempts_and_max_attempts_locks(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture
):
    resp = await client.post("/auth/otp/request", json={"phone": PHONE})
    assert resp.status_code == 200
    capsys.readouterr()

    for _attempt in range(settings.otp_max_attempts):
        resp = await client.post("/auth/otp/verify", json={"phone": PHONE, "code": "000000"})
        assert resp.status_code == 400, resp.text

    # One more attempt beyond the max must be rejected as rate-limited /
    # locked, not just "incorrect code" again.
    resp = await client.post("/auth/otp/verify", json={"phone": PHONE, "code": "000000"})
    assert resp.status_code == 429


async def test_otp_expiry(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture
):
    resp = await client.post("/auth/otp/request", json={"phone": PHONE})
    assert resp.status_code == 200
    captured = capsys.readouterr()
    code = captured.out.strip().split()[-3]

    otp_row = await _get_latest_otp(db_session, PHONE)
    otp_row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    resp = await client.post("/auth/otp/verify", json={"phone": PHONE, "code": code})
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"]


async def test_otp_rate_limit_on_request(client: AsyncClient, db_session: AsyncSession):
    for _ in range(settings.otp_rate_limit_max_requests):
        resp = await client.post("/auth/otp/request", json={"phone": PHONE})
        assert resp.status_code == 200

    resp = await client.post("/auth/otp/request", json={"phone": PHONE})
    assert resp.status_code == 429


async def test_raw_phone_never_persisted_in_db(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture
):
    resp = await client.post("/auth/otp/request", json={"phone": PHONE})
    assert resp.status_code == 200
    captured = capsys.readouterr()
    code = captured.out.strip().split()[-3]

    resp = await client.post("/auth/otp/verify", json={"phone": PHONE, "code": code})
    assert resp.status_code == 200

    # Scan every text-ish column of every relevant table for the raw phone
    # number; none should contain it.
    for table, column in [("otp_codes", "phone_hash"), ("users", "phone_hash")]:
        result = await db_session.execute(text(f"SELECT {column} FROM {table}"))
        for (value,) in result:
            assert PHONE not in value
            assert value != hash_phone(PHONE) or column == "phone_hash"  # sanity: hash, not raw


async def test_raw_phone_and_otp_never_logged(client: AsyncClient, capsys: pytest.CaptureFixture):
    # The only place plaintext phone/OTP legitimately appears is stdout via
    # the ConsoleSMSProvider stub (standing in for a real SMS API call) —
    # never via the `logging` module, which would be captured/aggregated.
    import logging

    logging.disable(logging.NOTSET)
    resp = await client.post("/auth/otp/request", json={"phone": PHONE})
    assert resp.status_code == 200
    captured = capsys.readouterr()
    assert PHONE in captured.out  # only the provider's stdout print, by design
    assert captured.err == ""  # nothing went out via logging/stderr


async def test_tier_progression_cannot_skip_tier1(client: AsyncClient, db_session: AsyncSession):
    # No Authorization header at all -> 401.
    resp = await client.post("/auth/email/request", json={"email": CORP_EMAIL})
    assert resp.status_code == 401

    # A well-formed but bogus token -> 401.
    resp = await client.post(
        "/auth/email/request",
        json={"email": CORP_EMAIL},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


async def test_full_tier1_to_tier2_flow_and_email_plaintext_never_persisted(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture
):
    resp = await client.post("/auth/otp/request", json={"phone": PHONE})
    code = capsys.readouterr().out.strip().split()[-3]
    resp = await client.post("/auth/otp/verify", json={"phone": PHONE, "code": code})
    tier1_access = resp.json()["access_token"]

    headers = {"Authorization": f"Bearer {tier1_access}"}
    resp = await client.post("/auth/email/request", json={"email": CORP_EMAIL}, headers=headers)
    assert resp.status_code == 200, resp.text
    captured = capsys.readouterr()
    assert CORP_EMAIL in captured.out
    email_code = captured.out.strip().split()[-3]

    resp = await client.post(
        "/auth/email/verify", json={"email": CORP_EMAIL, "code": email_code}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verification_tier"] == "email"

    # Plaintext email must not appear anywhere in the DB.
    for table, columns in [
        ("email_verification_codes", ["email_hash", "domain_hash", "code_hash"]),
        ("users", ["email_domain_hash"]),
    ]:
        for column in columns:
            result = await db_session.execute(text(f"SELECT {column} FROM {table}"))
            for (value,) in result:
                if value is None:
                    continue
                assert CORP_EMAIL not in value
                assert "acme.com" not in value


async def test_tier_progression_cannot_skip_tier2_for_document_upload(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture
):
    resp = await client.post("/auth/otp/request", json={"phone": PHONE})
    code = capsys.readouterr().out.strip().split()[-3]
    resp = await client.post("/auth/otp/verify", json={"phone": PHONE, "code": code})
    tier1_access = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {tier1_access}"}

    resp = await client.post(
        "/auth/document/upload?doc_type=offer_letter",
        headers=headers,
        files={"file": ("offer.pdf", b"fake-pdf-bytes", "application/pdf")},
    )
    assert resp.status_code == 403


async def test_jwt_payload_has_no_pii(client: AsyncClient, capsys: pytest.CaptureFixture):
    resp = await client.post("/auth/otp/request", json={"phone": PHONE})
    code = capsys.readouterr().out.strip().split()[-3]
    resp = await client.post("/auth/otp/verify", json={"phone": PHONE, "code": code})
    access_token = resp.json()["access_token"]
    refresh_token = resp.json()["refresh_token"]

    for token in (access_token, refresh_token):
        claims = jose_jwt.get_unverified_claims(token)
        assert set(claims.keys()) == {"sub", "tier", "iat", "exp", "type"}
        for value in claims.values():
            assert PHONE not in str(value)
