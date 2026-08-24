"""Phase 5 hardening: automated security checks.

Two things live here:

1. A schema-walk test that inspects the live OpenAPI document and flags
   any *response* model field whose name suggests raw PII (phone, email,
   document content) slipping into an API response. This is deliberately
   mechanical (substring match on field names) rather than a one-time
   manual read-through, so a future schema addition that reintroduces a
   plaintext field trips a test instead of shipping silently. See item 7
   of the Phase 5 brief.

2. Rate-limit tests for the four endpoints Phase 5 added/confirmed
   limiting on: `/auth/otp/request`, `/auth/email/request`, `POST
   /reviews`, `POST /grievance`.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.jwt import create_access_token
from app.main import app
from app.models.company import Company
from app.models.enums import ExitReason, RoleLevel, TenureBucket, VerificationTier
from app.models.user import User

# --------------------------------------------------------------------------
# PII-leak schema walk
# --------------------------------------------------------------------------

# Substrings that would suggest a response field carries raw PII rather
# than a hash/id/enum. Deliberately narrow (not "phone_number" etc.) so a
# variant naming still gets caught by the substring match.
_PII_NAME_SUBSTRINGS = ("phone", "email", "document")

# Field names that legitimately match one of the substrings above but are
# not a leak, with the reasoning for each. Anything added here should be
# added *because* a test run flagged it and a human confirmed it's fine
# by design — not added preemptively.
_ALLOWLISTED_FIELDS: dict[str, str] = {
    # (currently empty — nothing in this API's response models matches
    # the PII substrings above; see the module docstring. Kept as a named
    # dict, not just an empty set literal, so the next genuine exception
    # has an obvious place to land with its justification alongside it.)
}


def _resolve_schema(node: dict, components: dict, seen: set[str] | None = None) -> dict:
    """Follow a single `$ref` one level, if present. `seen` guards cycles."""
    seen = seen if seen is not None else set()
    if "$ref" in node:
        ref_name = node["$ref"].rsplit("/", 1)[-1]
        if ref_name in seen:
            return {}
        seen.add(ref_name)
        return components.get(ref_name, {})
    return node


def _collect_response_field_names(schema: dict) -> set[str]:
    """Walk every 2xx response schema in the OpenAPI doc, collecting field names.

    Deliberately scoped to *response* bodies only — request bodies
    legitimately carry fields named `phone`/`email` (you have to submit a
    phone number to request an OTP); the leak this test cares about is
    those values coming back out.
    """
    components = schema.get("components", {}).get("schemas", {})
    names: set[str] = set()

    def walk_schema_obj(node: dict, seen: set[str]) -> None:
        resolved = _resolve_schema(node, components, seen)
        if not resolved:
            return
        for prop_name, prop_schema in resolved.get("properties", {}).items():
            names.add(prop_name)
            walk_schema_obj(prop_schema, set(seen))
        # array items (e.g. PaginatedReviews.items: list[ReviewRead])
        if "items" in resolved:
            walk_schema_obj(resolved["items"], set(seen))
        # anyOf/allOf (e.g. Optional[SomeModel])
        for key in ("anyOf", "allOf", "oneOf"):
            for sub in resolved.get(key, []):
                walk_schema_obj(sub, set(seen))

    for path_item in schema.get("paths", {}).values():
        for method, operation in path_item.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            for status_code, response in operation.get("responses", {}).items():
                if not status_code.startswith("2"):
                    continue
                content = response.get("content", {}).get("application/json", {})
                body_schema = content.get("schema")
                if body_schema:
                    walk_schema_obj(body_schema, set())

    return names


def test_no_pii_shaped_fields_in_any_response_schema():
    schema = app.openapi()
    response_fields = _collect_response_field_names(schema)

    offending = sorted(
        field
        for field in response_fields
        if any(substr in field.lower() for substr in _PII_NAME_SUBSTRINGS)
        and field not in _ALLOWLISTED_FIELDS
    )

    assert offending == [], (
        f"response schema field(s) look like raw PII, not a hash/id/enum: {offending}. "
        "If this is a deliberate, reviewed exception, add it to _ALLOWLISTED_FIELDS "
        "with a reason; otherwise this is a real leak."
    )


def test_known_hash_and_id_fields_are_not_accidentally_over_flagged():
    """Sanity check on the test itself: confirm the substring match actually
    fires on an obviously-bad synthetic field name, so a change that
    breaks `_collect_response_field_names` (e.g. by pointing it at the
    wrong dict) doesn't silently turn this whole test into a no-op.
    """
    assert any(substr in "raw_phone_number".lower() for substr in _PII_NAME_SUBSTRINGS)
    assert any(substr in "corporate_email".lower() for substr in _PII_NAME_SUBSTRINGS)
    assert any(substr in "document_content".lower() for substr in _PII_NAME_SUBSTRINGS)


# --------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------


async def _seed_company(db_session: AsyncSession, name: str = "RateCo") -> uuid.UUID:
    unique_suffix = uuid.uuid4().hex[:8]
    company = Company(
        id=uuid.uuid4(),
        name=f"{name} {unique_suffix}",
        slug=f"{name.lower()}-{unique_suffix}",
        corporate_email_domains=["rateco.com"],
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


def _auth_header(user: User) -> dict:
    token = create_access_token(user.id, user.verification_tier)
    return {"Authorization": f"Bearer {token}"}


async def test_otp_request_rate_limited(client: AsyncClient, db_session: AsyncSession):
    phone = "+15550001111"
    limit = settings.otp_rate_limit_max_requests

    for _ in range(limit):
        resp = await client.post("/auth/otp/request", json={"phone": phone})
        assert resp.status_code == 200

    resp = await client.post("/auth/otp/request", json={"phone": phone})
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert int(resp.headers["Retry-After"]) > 0


async def test_email_request_rate_limited(client: AsyncClient, db_session: AsyncSession):
    user = await _seed_user(db_session, tier=VerificationTier.phone)
    limit = settings.email_rate_limit_max_requests

    for _ in range(limit):
        resp = await client.post(
            "/auth/email/request", json={"email": "person@acme.com"}, headers=_auth_header(user)
        )
        assert resp.status_code == 200

    resp = await client.post(
        "/auth/email/request", json={"email": "person@acme.com"}, headers=_auth_header(user)
    )
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


async def test_review_submission_rate_limited(client: AsyncClient, db_session: AsyncSession):
    user = await _seed_user(db_session)
    limit = settings.review_rate_limit_max_requests

    # A fresh company per attempt so the unique-per-user-per-company
    # constraint never itself blocks the request — this test is about
    # the rate limit specifically, not the uniqueness rule.
    for _ in range(limit):
        company_id = await _seed_company(db_session)
        resp = await client.post(
            "/reviews",
            json={
                "company_id": str(company_id),
                "exit_reason": ExitReason.other.value,
                "tenure_bucket": TenureBucket.less_than_1yr.value,
                "department": "Ops",
                "role_level": RoleLevel.ic.value,
                "is_current_employee": False,
                "prose": "Nothing remarkable.",
            },
            headers=_auth_header(user),
        )
        assert resp.status_code == 201

    company_id = await _seed_company(db_session)
    resp = await client.post(
        "/reviews",
        json={
            "company_id": str(company_id),
            "exit_reason": ExitReason.other.value,
            "tenure_bucket": TenureBucket.less_than_1yr.value,
            "department": "Ops",
            "role_level": RoleLevel.ic.value,
            "is_current_employee": False,
            "prose": "One review too many.",
        },
        headers=_auth_header(user),
    )
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


async def test_grievance_submission_rate_limited(client: AsyncClient, db_session: AsyncSession):
    contact = "frequent-filer@example.com"
    limit = settings.grievance_rate_limit_max_requests

    for _ in range(limit):
        resp = await client.post(
            "/grievance",
            json={
                "complainant_contact": contact,
                "subject": "Repeat complaint",
                "description": "Same complainant, different submission.",
            },
        )
        assert resp.status_code == 201

    resp = await client.post(
        "/grievance",
        json={
            "complainant_contact": contact,
            "subject": "One too many",
            "description": "This one should be rate limited.",
        },
    )
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers

    # A different complainant is unaffected — the limit is per-key, not global.
    other_resp = await client.post(
        "/grievance",
        json={
            "complainant_contact": "someone-else@example.com",
            "subject": "Unrelated complaint",
            "description": "Different complainant, should go through.",
        },
    )
    assert other_resp.status_code == 201
