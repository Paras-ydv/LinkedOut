"""Tests for Phase 4: Moderation & Compliance."""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jwt import create_access_token, create_admin_token
from app.core.security import hash_password
from app.models.admin import AdminUser
from app.models.company import Company
from app.models.enums import (
    DocumentType,
    ExitReason,
    ReviewStatus,
    RoleLevel,
    TenureBucket,
    VerificationTier,
)
from app.models.grievance import GrievanceComplaint
from app.models.moderation import ModerationQueueItem
from app.models.review import Review
from app.models.user import User


async def _seed_company(db_session: AsyncSession, name: str = "Acme Corp") -> uuid.UUID:
    company = Company(
        id=uuid.uuid4(),
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}",
        corporate_email_domains=["acme.com"],
    )
    db_session.add(company)
    await db_session.commit()
    await db_session.refresh(company)
    return company.id


async def _seed_user(
    db_session: AsyncSession, tier: VerificationTier = VerificationTier.email
) -> User:
    user = User(id=uuid.uuid4(), phone_hash=uuid.uuid4().hex, verification_tier=tier)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_admin(
    db_session: AsyncSession, password: str = "correct horse battery staple"
) -> AdminUser:
    admin = AdminUser(
        id=uuid.uuid4(), email="mod@linkedout.example", password_hash=hash_password(password)
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    return admin


def _auth_header(user: User) -> dict:
    token = create_access_token(user.id, user.verification_tier)
    return {"Authorization": f"Bearer {token}"}


def _admin_header(admin: AdminUser) -> dict:
    token = create_admin_token(admin.id)
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------
# Pre-publication name filter
# --------------------------------------------------------------------------


async def test_review_with_name_in_prose_is_flagged(client: AsyncClient, db_session: AsyncSession):
    company_id = await _seed_company(db_session)
    user = await _seed_user(db_session)

    resp = await client.post(
        "/reviews",
        json={
            "company_id": str(company_id),
            "exit_reason": ExitReason.management.value,
            "tenure_bucket": TenureBucket.one_to_3yr.value,
            "department": "Engineering",
            "role_level": RoleLevel.ic.value,
            "is_current_employee": False,
            "prose": "My manager Rahul Sharma was consistently unfair to the whole team.",
        },
        headers=_auth_header(user),
    )
    assert resp.status_code == 201
    review_id = resp.json()["id"]
    assert resp.json()["status"] == "PENDING"

    review = (await db_session.execute(select(Review).where(Review.id == review_id))).scalar_one()
    assert review.flagged_reason is not None
    assert "Rahul Sharma" in review.flagged_reason
    assert review.status == ReviewStatus.pending  # filter hit never auto-rejects


async def test_review_with_no_name_passes_filter_but_stays_pending(
    client: AsyncClient, db_session: AsyncSession
):
    company_id = await _seed_company(db_session)
    user = await _seed_user(db_session)

    resp = await client.post(
        "/reviews",
        json={
            "company_id": str(company_id),
            "exit_reason": ExitReason.compensation.value,
            "tenure_bucket": TenureBucket.one_to_3yr.value,
            "department": "Engineering",
            "role_level": RoleLevel.ic.value,
            "is_current_employee": False,
            "prose": "Compensation was below market and growth was slow.",
        },
        headers=_auth_header(user),
    )
    assert resp.status_code == 201
    review_id = resp.json()["id"]
    assert resp.json()["status"] == "PENDING"  # filter pass still never auto-publishes

    review = (await db_session.execute(select(Review).where(Review.id == review_id))).scalar_one()
    assert review.flagged_reason is None
    assert review.status == ReviewStatus.pending


# --------------------------------------------------------------------------
# Admin auth gate
# --------------------------------------------------------------------------


async def test_non_admin_cannot_access_moderation_queue(
    client: AsyncClient, db_session: AsyncSession
):
    resp = await client.get("/admin/moderation-queue")
    assert resp.status_code == 401


async def test_regular_user_token_rejected_by_admin_routes(
    client: AsyncClient, db_session: AsyncSession
):
    user = await _seed_user(db_session)
    resp = await client.get("/admin/moderation-queue", headers=_auth_header(user))
    assert resp.status_code == 401


async def test_admin_grievances_requires_admin(client: AsyncClient, db_session: AsyncSession):
    resp = await client.get("/admin/grievances")
    assert resp.status_code == 401


# --------------------------------------------------------------------------
# Reject requires a reason
# --------------------------------------------------------------------------


async def test_reject_requires_nonempty_reason(client: AsyncClient, db_session: AsyncSession):
    company_id = await _seed_company(db_session)
    user = await _seed_user(db_session)
    admin = await _seed_admin(db_session)

    review = Review(
        id=uuid.uuid4(),
        user_id=user.id,
        company_id=company_id,
        exit_reason=ExitReason.other,
        tenure_bucket=TenureBucket.less_than_1yr,
        department="Sales",
        role_level=RoleLevel.ic,
        is_current_employee=False,
        prose="Fine job overall.",
        status=ReviewStatus.pending,
    )
    db_session.add(review)
    await db_session.commit()

    # Missing reason field entirely.
    resp = await client.post(
        f"/admin/moderation-queue/REVIEW/{review.id}/reject",
        json={},
        headers=_admin_header(admin),
    )
    assert resp.status_code == 422

    # Empty-string reason.
    resp = await client.post(
        f"/admin/moderation-queue/REVIEW/{review.id}/reject",
        json={"reason": ""},
        headers=_admin_header(admin),
    )
    assert resp.status_code == 422

    # Valid reason succeeds.
    resp = await client.post(
        f"/admin/moderation-queue/REVIEW/{review.id}/reject",
        json={"reason": "violates community guidelines"},
        headers=_admin_header(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "REJECTED"


# --------------------------------------------------------------------------
# Public takedown log: zero auth
# --------------------------------------------------------------------------


async def test_takedown_log_accessible_with_zero_auth(
    client: AsyncClient, db_session: AsyncSession
):
    # Explicitly no Authorization header of any kind.
    resp = await client.get("/takedown-log")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body and "total" in body


async def test_takedown_log_post_requires_admin(client: AsyncClient, db_session: AsyncSession):
    resp = await client.post(
        "/admin/takedown-log",
        json={
            "item_type": "REVIEW",
            "item_id": str(uuid.uuid4()),
            "requester_type": "COURT_ORDER",
            "complied": True,
            "reason": "Court order #1234",
        },
    )
    assert resp.status_code == 401


async def test_admin_can_create_takedown_entry_and_it_appears_publicly(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _seed_admin(db_session)
    resp = await client.post(
        "/admin/takedown-log",
        json={
            "item_type": "REVIEW",
            "item_id": str(uuid.uuid4()),
            "requester_type": "GOVERNMENT_DIRECTION",
            "requester_detail": "Order ref GX-2026-004",
            "complied": True,
            "reason": "Complied per formal government direction.",
        },
        headers=_admin_header(admin),
    )
    assert resp.status_code == 201

    public_resp = await client.get("/takedown-log")
    assert public_resp.status_code == 200
    assert public_resp.json()["total"] == 1


# --------------------------------------------------------------------------
# Grievance SLA computation
# --------------------------------------------------------------------------


async def test_grievance_sla_standard_7_days(client: AsyncClient, db_session: AsyncSession):
    resp = await client.post(
        "/grievance",
        json={
            "complainant_contact": "someone@example.com",
            "subject": "Incorrect review about my company",
            "description": "This review contains factual inaccuracies.",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "ACKNOWLEDGED"

    created = (
        await db_session.execute(
            select(GrievanceComplaint).where(GrievanceComplaint.id == body["id"])
        )
    ).scalar_one()
    delta = created.sla_deadline - created.created_at
    assert timedelta(days=6, hours=23) < delta < timedelta(days=7, hours=1)


async def test_grievance_sla_urgent_3_hours(client: AsyncClient, db_session: AsyncSession):
    resp = await client.post(
        "/grievance",
        json={
            "complainant_contact": "legal@example.com",
            "subject": "Court order compliance request",
            "description": "Please see attached court order.",
            "is_court_or_government_matter": True,
        },
    )
    assert resp.status_code == 201
    body = resp.json()

    created = (
        await db_session.execute(
            select(GrievanceComplaint).where(GrievanceComplaint.id == body["id"])
        )
    ).scalar_one()
    delta = created.sla_deadline - created.created_at
    assert timedelta(hours=2, minutes=55) < delta < timedelta(hours=3, minutes=5)


async def test_admin_grievances_sorted_by_deadline_and_flags_overdue(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _seed_admin(db_session)
    now = datetime.now(UTC)

    urgent = GrievanceComplaint(
        id=uuid.uuid4(),
        complainant_contact="urgent@example.com",
        subject="Urgent",
        description="Urgent matter",
        status="ACKNOWLEDGED",
        sla_deadline=now - timedelta(hours=1),  # already overdue
    )
    standard = GrievanceComplaint(
        id=uuid.uuid4(),
        complainant_contact="standard@example.com",
        subject="Standard",
        description="Standard matter",
        status="ACKNOWLEDGED",
        sla_deadline=now + timedelta(days=6),
    )
    db_session.add_all([standard, urgent])
    await db_session.commit()

    resp = await client.get("/admin/grievances", headers=_admin_header(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"][0]["id"] == str(urgent.id)  # most urgent first
    assert body["items"][0]["past_deadline"] is True
    assert body["items"][1]["past_deadline"] is False


# --------------------------------------------------------------------------
# Integration: approved review becomes visible in Phase 2/3 endpoints
# --------------------------------------------------------------------------


async def test_approved_review_visible_in_published_endpoints(
    client: AsyncClient, db_session: AsyncSession
):
    company_id = await _seed_company(db_session)
    user = await _seed_user(db_session)
    admin = await _seed_admin(db_session)

    submit_resp = await client.post(
        "/reviews",
        json={
            "company_id": str(company_id),
            "exit_reason": ExitReason.growth.value,
            "tenure_bucket": TenureBucket.three_to_5yr.value,
            "department": "Marketing",
            "role_level": RoleLevel.manager.value,
            "is_current_employee": False,
            "prose": "Limited growth opportunities but decent culture overall.",
        },
        headers=_auth_header(user),
    )
    review_id = submit_resp.json()["id"]

    # Not visible yet: still PENDING.
    list_resp = await client.get(f"/reviews/company/{company_id}")
    assert list_resp.json()["total"] == 0

    approve_resp = await client.post(
        f"/admin/moderation-queue/REVIEW/{review_id}/approve", headers=_admin_header(admin)
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "PUBLISHED"

    # Now visible via the Phase 2 public read endpoint.
    list_resp = await client.get(f"/reviews/company/{company_id}")
    body = list_resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == review_id

    # Approving twice is rejected (no longer PENDING).
    approve_again = await client.post(
        f"/admin/moderation-queue/REVIEW/{review_id}/approve", headers=_admin_header(admin)
    )
    assert approve_again.status_code == 409


async def test_moderation_queue_sorts_flagged_first(client: AsyncClient, db_session: AsyncSession):
    company_id = await _seed_company(db_session)
    user = await _seed_user(db_session)
    admin = await _seed_admin(db_session)

    # First: an unflagged review.
    await client.post(
        "/reviews",
        json={
            "company_id": str(company_id),
            "exit_reason": ExitReason.other.value,
            "tenure_bucket": TenureBucket.less_than_1yr.value,
            "department": "Ops",
            "role_level": RoleLevel.ic.value,
            "is_current_employee": True,
            "prose": "Nothing remarkable either way.",
        },
        headers=_auth_header(user),
    )

    user2 = await _seed_user(db_session)
    # Second (created later): a flagged review.
    flagged_resp = await client.post(
        "/reviews",
        json={
            "company_id": str(company_id),
            "exit_reason": ExitReason.management.value,
            "tenure_bucket": TenureBucket.one_to_3yr.value,
            "department": "Ops",
            "role_level": RoleLevel.ic.value,
            "is_current_employee": False,
            "prose": "My manager Anita Desai treated the team poorly.",
        },
        headers=_auth_header(user2),
    )
    flagged_id = flagged_resp.json()["id"]

    resp = await client.get("/admin/moderation-queue", headers=_admin_header(admin))
    body = resp.json()
    assert body["total"] == 2
    # Flagged item first even though it was created second.
    assert body["items"][0]["item_id"] == flagged_id
    assert body["items"][0]["flagged_reason"] is not None
    assert body["items"][1]["flagged_reason"] is None


async def test_admin_login_wrong_password_rejected(client: AsyncClient, db_session: AsyncSession):
    await _seed_admin(db_session, password="correct-password")
    resp = await client.post(
        "/admin/login", json={"email": "mod@linkedout.example", "password": "wrong-password"}
    )
    assert resp.status_code == 401


async def test_admin_login_success_issues_working_token(
    client: AsyncClient, db_session: AsyncSession
):
    await _seed_admin(db_session, password="correct-password")
    resp = await client.post(
        "/admin/login", json={"email": "mod@linkedout.example", "password": "correct-password"}
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    queue_resp = await client.get(
        "/admin/moderation-queue", headers={"Authorization": f"Bearer {token}"}
    )
    assert queue_resp.status_code == 200


# --------------------------------------------------------------------------
# Tier-3 document moderation queue
# --------------------------------------------------------------------------


async def _seed_document_queue_item(
    db_session: AsyncSession, user: User, ephemeral_path: str | None = "/tmp/does-not-matter.bin"
) -> ModerationQueueItem:
    item = ModerationQueueItem(
        id=uuid.uuid4(),
        user_id=user.id,
        doc_type=DocumentType.offer_letter,
        content_hash=uuid.uuid4().hex,
        ephemeral_path=ephemeral_path,
        created_at=datetime.now(UTC),
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


async def test_document_queue_non_admin_unauthorized(client: AsyncClient, db_session: AsyncSession):
    user = await _seed_user(db_session, tier=VerificationTier.email)
    item = await _seed_document_queue_item(db_session, user)

    # No token at all -> 401.
    resp = await client.get("/admin/document-queue")
    assert resp.status_code == 401

    resp = await client.post(f"/admin/document-queue/{item.id}/approve")
    assert resp.status_code == 401

    # A regular (non-admin) user token is also not accepted -> 401, since
    # get_current_admin decodes an admin-typed token, and a `User` access
    # token simply fails that decode rather than authenticating as some
    # lesser-privileged admin.
    resp = await client.get("/admin/document-queue", headers=_auth_header(user))
    assert resp.status_code == 401


async def test_document_reject_requires_nonempty_reason(
    client: AsyncClient, db_session: AsyncSession
):
    user = await _seed_user(db_session, tier=VerificationTier.email)
    admin = await _seed_admin(db_session)
    item = await _seed_document_queue_item(db_session, user)

    resp = await client.post(
        f"/admin/document-queue/{item.id}/reject", json={}, headers=_admin_header(admin)
    )
    assert resp.status_code == 422

    resp = await client.post(
        f"/admin/document-queue/{item.id}/reject", json={"reason": ""}, headers=_admin_header(admin)
    )
    assert resp.status_code == 422

    resp = await client.post(
        f"/admin/document-queue/{item.id}/reject",
        json={"reason": "document image was unreadable"},
        headers=_admin_header(admin),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["action"] == "REJECT"

    # User's tier is untouched by a rejection.
    await db_session.refresh(user)
    assert user.verification_tier == VerificationTier.email

    # Rejecting again 409s: no longer pending.
    resp = await client.post(
        f"/admin/document-queue/{item.id}/reject",
        json={"reason": "already handled"},
        headers=_admin_header(admin),
    )
    assert resp.status_code == 409


async def test_document_approval_bumps_tier_and_unlocks_tier3_route(
    client: AsyncClient, db_session: AsyncSession
):
    user = await _seed_user(db_session, tier=VerificationTier.email)
    admin = await _seed_admin(db_session)
    item = await _seed_document_queue_item(db_session, user)

    # Before approval: a Tier-3-gated route (document upload itself
    # requires Tier 2, but /auth/me plus a synthetic require_tier(3) check
    # is exercised indirectly here via the moderation queue's own effect
    # on the DB row — assert the pre-state first).
    assert user.verification_tier == VerificationTier.email

    resp = await client.get("/admin/document-queue", headers=_admin_header(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(item.id)

    approve_resp = await client.post(
        f"/admin/document-queue/{item.id}/approve", headers=_admin_header(admin)
    )
    assert approve_resp.status_code == 200
    approve_body = approve_resp.json()
    assert approve_body["status"] == "approved"
    assert approve_body["user_id"] == str(user.id)

    await db_session.refresh(user)
    assert user.verification_tier == VerificationTier.document

    # The ephemeral file reference is cleared per the hash-and-delete rule.
    refreshed_item = (
        await db_session.execute(
            select(ModerationQueueItem).where(ModerationQueueItem.id == item.id)
        )
    ).scalar_one()
    assert refreshed_item.ephemeral_path is None
    assert refreshed_item.status == "approved"

    # No longer in the pending queue.
    resp = await client.get("/admin/document-queue", headers=_admin_header(admin))
    assert resp.json()["total"] == 0

    # A subsequent Tier-3-gated route is now reachable: use the token's
    # *current* tier via require_tier(document) — /auth/document/upload
    # itself only requires Tier 2, so exercise the tier gate directly by
    # hitting a route that requires Tier 3. There is no dedicated
    # Tier-3-only route yet in this API surface, so assert against the
    # underlying guarantee `require_tier` relies on instead: the user's
    # current DB tier is now `document`, which is what any future
    # Tier-3-gated route's `require_tier(VerificationTier.document)`
    # dependency checks.
    me_resp = await client.get("/auth/me", headers=_auth_header(user))
    assert me_resp.status_code == 200
    assert me_resp.json()["verification_tier"] == "document"

    # Approving twice 409s.
    resp = await client.post(
        f"/admin/document-queue/{item.id}/approve", headers=_admin_header(admin)
    )
    assert resp.status_code == 409


async def test_document_approval_404_for_unknown_item(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _seed_admin(db_session)
    resp = await client.post(
        f"/admin/document-queue/{uuid.uuid4()}/approve", headers=_admin_header(admin)
    )
    assert resp.status_code == 404
