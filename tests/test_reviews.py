"""Tests for Phase 2: Core Review Flow.

Covers: one-review-per-user-per-company constraint, corroboration
self-block, employer can only respond to their own company's reviews,
unpublished reviews never appear in GET endpoints, tenure/exit_reason
enums reject invalid values.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_domain
from app.models.company import Company
from app.models.employer import EmployerAccount
from app.models.enums import ReviewStatus
from app.models.review import Review

PHONE_A = "+15550000001"
PHONE_B = "+15550000002"
EMAIL_A = "alice@acme.com"
EMAIL_B = "bob@acme.com"

VALID_REVIEW_BODY = {
    "exit_reason": "CULTURE",
    "tenure_bucket": "ONE_TO_3YR",
    "department": "Engineering",
    "role_level": "IC",
    "is_current_employee": False,
    "prose": "It was fine, could be better.",
}


async def _seed_company(db_session: AsyncSession, name: str = "Acme Corp") -> uuid.UUID:
    company = Company(
        id=uuid.uuid4(),
        name=name,
        slug=name.lower().replace(" ", "-"),
        corporate_email_domains=["acme.com"],
    )
    db_session.add(company)
    await db_session.commit()
    await db_session.refresh(company)
    return company.id


async def _tier2_token(
    client: AsyncClient, capsys: pytest.CaptureFixture, phone: str, email: str
) -> str:
    await client.post("/auth/otp/request", json={"phone": phone})
    otp_code = capsys.readouterr().out.strip().split()[-3]
    resp = await client.post("/auth/otp/verify", json={"phone": phone, "code": otp_code})
    tier1_access = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {tier1_access}"}

    await client.post("/auth/email/request", json={"email": email}, headers=headers)
    email_code = capsys.readouterr().out.strip().split()[-3]
    resp = await client.post(
        "/auth/email/verify", json={"email": email, "code": email_code}, headers=headers
    )
    return resp.json()["access_token"]


async def _tier1_token(client: AsyncClient, capsys: pytest.CaptureFixture, phone: str) -> str:
    await client.post("/auth/otp/request", json={"phone": phone})
    otp_code = capsys.readouterr().out.strip().split()[-3]
    resp = await client.post("/auth/otp/verify", json={"phone": phone, "code": otp_code})
    return resp.json()["access_token"]


# --------------------------------------------------------------------------
# Review submission
# --------------------------------------------------------------------------


async def test_submit_review_requires_tier2(client: AsyncClient, db_session: AsyncSession):
    company_id = await _seed_company(db_session)
    resp = await client.post("/reviews", json={"company_id": str(company_id), **VALID_REVIEW_BODY})
    assert resp.status_code == 401


async def test_submit_review_rejects_unknown_company(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture
):
    token = await _tier2_token(client, capsys, PHONE_A, EMAIL_A)
    resp = await client.post(
        "/reviews",
        json={"company_id": str(uuid.uuid4()), **VALID_REVIEW_BODY},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_submit_review_starts_pending(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture
):
    company_id = await _seed_company(db_session)
    token = await _tier2_token(client, capsys, PHONE_A, EMAIL_A)
    resp = await client.post(
        "/reviews",
        json={"company_id": str(company_id), **VALID_REVIEW_BODY},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "PENDING"


async def test_one_review_per_user_per_company(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture
):
    company_id = await _seed_company(db_session)
    token = await _tier2_token(client, capsys, PHONE_A, EMAIL_A)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/reviews", json={"company_id": str(company_id), **VALID_REVIEW_BODY}, headers=headers
    )
    assert resp.status_code == 201

    resp = await client.post(
        "/reviews", json={"company_id": str(company_id), **VALID_REVIEW_BODY}, headers=headers
    )
    assert resp.status_code == 409


async def test_invalid_exit_reason_rejected(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture
):
    company_id = await _seed_company(db_session)
    token = await _tier2_token(client, capsys, PHONE_A, EMAIL_A)
    body = {**VALID_REVIEW_BODY, "company_id": str(company_id), "exit_reason": "NOT_A_REAL_REASON"}
    resp = await client.post("/reviews", json=body, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422


async def test_invalid_tenure_bucket_rejected(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture
):
    company_id = await _seed_company(db_session)
    token = await _tier2_token(client, capsys, PHONE_A, EMAIL_A)
    body = {**VALID_REVIEW_BODY, "company_id": str(company_id), "tenure_bucket": "TWENTY_YEARS"}
    resp = await client.post("/reviews", json=body, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422


# --------------------------------------------------------------------------
# Unpublished reviews never appear in GET endpoints
# --------------------------------------------------------------------------


async def test_pending_review_not_in_company_list(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture
):
    company_id = await _seed_company(db_session)
    token = await _tier2_token(client, capsys, PHONE_A, EMAIL_A)
    await client.post(
        "/reviews",
        json={"company_id": str(company_id), **VALID_REVIEW_BODY},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.get(f"/reviews/company/{company_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


async def test_published_review_appears_in_company_list(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture
):
    company_id = await _seed_company(db_session)
    token = await _tier2_token(client, capsys, PHONE_A, EMAIL_A)
    resp = await client.post(
        "/reviews",
        json={"company_id": str(company_id), **VALID_REVIEW_BODY},
        headers={"Authorization": f"Bearer {token}"},
    )
    review_id = resp.json()["id"]

    # Simulate Phase 4's moderation queue publishing the review.
    review = await db_session.get(Review, uuid.UUID(review_id))
    review.status = ReviewStatus.published
    await db_session.commit()

    resp = await client.get(f"/reviews/company/{company_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == review_id
    assert "user_id" not in body["items"][0]


# --------------------------------------------------------------------------
# Corroboration
# --------------------------------------------------------------------------


async def _publish_review_from(
    client: AsyncClient,
    db_session: AsyncSession,
    capsys: pytest.CaptureFixture,
    phone: str,
    email: str,
) -> tuple[uuid.UUID, str]:
    company_id = await _seed_company(db_session)
    token = await _tier2_token(client, capsys, phone, email)
    resp = await client.post(
        "/reviews",
        json={"company_id": str(company_id), **VALID_REVIEW_BODY},
        headers={"Authorization": f"Bearer {token}"},
    )
    review_id = uuid.UUID(resp.json()["id"])
    return review_id, token


async def test_corroborate_requires_tier1(client: AsyncClient, db_session: AsyncSession):
    resp = await client.post(f"/reviews/{uuid.uuid4()}/corroborate", json={})
    assert resp.status_code == 401


async def test_cannot_corroborate_own_review(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture
):
    review_id, author_token = await _publish_review_from(
        client, db_session, capsys, PHONE_A, EMAIL_A
    )
    resp = await client.post(
        f"/reviews/{review_id}/corroborate",
        json={"comment": "me too!"},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert resp.status_code == 400


async def test_one_corroboration_per_user_per_review(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture
):
    review_id, _ = await _publish_review_from(client, db_session, capsys, PHONE_A, EMAIL_A)
    corroborator_token = await _tier1_token(client, capsys, PHONE_B)
    headers = {"Authorization": f"Bearer {corroborator_token}"}

    resp = await client.post(
        f"/reviews/{review_id}/corroborate", json={"comment": "same here"}, headers=headers
    )
    assert resp.status_code == 201

    resp = await client.post(
        f"/reviews/{review_id}/corroborate", json={"comment": "again"}, headers=headers
    )
    assert resp.status_code == 409


async def test_corroborations_never_expose_user_identity(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture
):
    review_id, _ = await _publish_review_from(client, db_session, capsys, PHONE_A, EMAIL_A)
    corroborator_token = await _tier1_token(client, capsys, PHONE_B)
    await client.post(
        f"/reviews/{review_id}/corroborate",
        json={"comment": "same experience"},
        headers={"Authorization": f"Bearer {corroborator_token}"},
    )

    resp = await client.get(f"/reviews/{review_id}/corroborations")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["comment"] == "same experience"
    for item in body["items"]:
        assert "user_id" not in item
        assert "email" not in item


# --------------------------------------------------------------------------
# Employer response
# --------------------------------------------------------------------------


async def _seed_verified_employer(
    db_session: AsyncSession, company_id: uuid.UUID, domain: str = "acme.com"
) -> EmployerAccount:
    employer = EmployerAccount(
        id=uuid.uuid4(),
        company_id=company_id,
        domain_hash=hash_domain(domain),
        verified=True,
    )
    db_session.add(employer)
    await db_session.commit()
    await db_session.refresh(employer)
    return employer


async def test_employer_can_respond_to_own_company_review(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture
):
    company_id = await _seed_company(db_session)
    token = await _tier2_token(client, capsys, PHONE_A, EMAIL_A)
    resp = await client.post(
        "/reviews",
        json={"company_id": str(company_id), **VALID_REVIEW_BODY},
        headers={"Authorization": f"Bearer {token}"},
    )
    review_id = resp.json()["id"]

    await _seed_verified_employer(db_session, company_id)
    resp = await client.post("/employer/login", json={"email": "hr@acme.com"})
    assert resp.status_code == 200, resp.text
    employer_token = resp.json()["access_token"]

    resp = await client.post(
        f"/reviews/{review_id}/response",
        json={"response_text": "Thanks for the feedback."},
        headers={"Authorization": f"Bearer {employer_token}"},
    )
    assert resp.status_code == 201, resp.text


async def test_employer_cannot_respond_to_other_companys_review(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture
):
    company_a = await _seed_company(db_session, name="Acme Corp")
    company_b = await _seed_company(db_session, name="Beta Inc")

    token = await _tier2_token(client, capsys, PHONE_A, EMAIL_A)
    resp = await client.post(
        "/reviews",
        json={"company_id": str(company_a), **VALID_REVIEW_BODY},
        headers={"Authorization": f"Bearer {token}"},
    )
    review_id = resp.json()["id"]

    # Employer account belongs to company_b, not company_a.
    await _seed_verified_employer(db_session, company_b, domain="beta.com")
    resp = await client.post("/employer/login", json={"email": "hr@beta.com"})
    employer_token = resp.json()["access_token"]

    resp = await client.post(
        f"/reviews/{review_id}/response",
        json={"response_text": "This isn't about us!"},
        headers={"Authorization": f"Bearer {employer_token}"},
    )
    assert resp.status_code == 403


async def test_unverified_employer_account_cannot_login(
    client: AsyncClient, db_session: AsyncSession
):
    company_id = await _seed_company(db_session)
    employer = EmployerAccount(
        id=uuid.uuid4(),
        company_id=company_id,
        domain_hash=hash_domain("acme.com"),
        verified=False,
    )
    db_session.add(employer)
    await db_session.commit()

    resp = await client.post("/employer/login", json={"email": "hr@acme.com"})
    assert resp.status_code == 404
