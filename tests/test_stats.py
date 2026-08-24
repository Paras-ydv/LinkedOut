"""Tests for Phase 3: Aggregation Engine.

Covers: insufficient_data path, stats reflect PUBLISHED only, percentages
sum to exactly 100, no composite/overall score keys anywhere, and a known
corroboration_density fixture.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.company import Company
from app.models.enums import ExitReason, ReviewStatus, RoleLevel, TenureBucket
from app.models.review import Corroboration, Review
from app.models.user import User

# Keys that would signal a single composite/overall score sneaking into a
# response — this is a hard product constraint (see app/services/stats.py).
FORBIDDEN_KEY_SUBSTRINGS = (
    "score",
    "index",
    "overall",
    "rating",
    "toxicity",
    "composite",
)


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


async def _seed_user(db_session: AsyncSession) -> uuid.UUID:
    user = User(id=uuid.uuid4(), phone_hash=uuid.uuid4().hex, verification_tier="email")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user.id


async def _seed_review(
    db_session: AsyncSession,
    company_id: uuid.UUID,
    *,
    status: ReviewStatus = ReviewStatus.published,
    exit_reason: ExitReason = ExitReason.culture,
    tenure_bucket: TenureBucket = TenureBucket.one_to_3yr,
    role_level: RoleLevel = RoleLevel.ic,
    is_current_employee: bool = False,
) -> uuid.UUID:
    user_id = await _seed_user(db_session)
    review = Review(
        id=uuid.uuid4(),
        user_id=user_id,
        company_id=company_id,
        exit_reason=exit_reason,
        tenure_bucket=tenure_bucket,
        department="Engineering",
        role_level=role_level,
        is_current_employee=is_current_employee,
        prose="Some review text.",
        status=status,
    )
    db_session.add(review)
    await db_session.commit()
    await db_session.refresh(review)
    return review.id


async def _seed_corroborations(db_session: AsyncSession, review_id: uuid.UUID, count: int) -> None:
    for _ in range(count):
        user_id = await _seed_user(db_session)
        db_session.add(Corroboration(id=uuid.uuid4(), review_id=review_id, user_id=user_id))
    await db_session.commit()


# --------------------------------------------------------------------------
# insufficient_data
# --------------------------------------------------------------------------


async def test_stats_insufficient_data_with_zero_reviews(
    client: AsyncClient, db_session: AsyncSession
):
    company_id = await _seed_company(db_session)
    resp = await client.get(f"/companies/{company_id}/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "insufficient_data": True,
        "minimum_required": settings.stats_min_published_reviews,
        "current_count": 0,
    }


async def test_stats_insufficient_data_below_threshold(
    client: AsyncClient, db_session: AsyncSession
):
    assert settings.stats_min_published_reviews == 5, "test assumes the documented default"
    company_id = await _seed_company(db_session)
    for _ in range(4):
        await _seed_review(db_session, company_id)

    resp = await client.get(f"/companies/{company_id}/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["insufficient_data"] is True
    assert body["current_count"] == 4
    assert body["minimum_required"] == 5
    # Only the insufficient-data keys should be present.
    assert set(body.keys()) == {"insufficient_data", "minimum_required", "current_count"}


async def test_stats_returns_full_payload_at_threshold(
    client: AsyncClient, db_session: AsyncSession
):
    company_id = await _seed_company(db_session)
    for _ in range(5):
        await _seed_review(db_session, company_id)

    resp = await client.get(f"/companies/{company_id}/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["insufficient_data"] is False
    assert body["total_published_reviews"] == 5


async def test_stats_404_for_unknown_company(client: AsyncClient, db_session: AsyncSession):
    resp = await client.get(f"/companies/{uuid.uuid4()}/stats")
    assert resp.status_code == 404


# --------------------------------------------------------------------------
# PUBLISHED-only
# --------------------------------------------------------------------------


async def test_stats_excludes_pending_reviews(client: AsyncClient, db_session: AsyncSession):
    company_id = await _seed_company(db_session)
    for _ in range(5):
        await _seed_review(db_session, company_id, status=ReviewStatus.published)
    # A PENDING review that, if counted, would change the totals/percentages.
    await _seed_review(
        db_session, company_id, status=ReviewStatus.pending, exit_reason=ExitReason.layoffs
    )

    resp = await client.get(f"/companies/{company_id}/stats")
    body = resp.json()
    assert body["total_published_reviews"] == 5
    assert body["exit_reason_distribution"]["LAYOFFS"]["count"] == 0


async def test_stats_excludes_rejected_reviews(client: AsyncClient, db_session: AsyncSession):
    company_id = await _seed_company(db_session)
    for _ in range(5):
        await _seed_review(db_session, company_id, status=ReviewStatus.published)
    await _seed_review(db_session, company_id, status=ReviewStatus.rejected)

    resp = await client.get(f"/companies/{company_id}/stats")
    body = resp.json()
    assert body["total_published_reviews"] == 5


# --------------------------------------------------------------------------
# Percentage rounding
# --------------------------------------------------------------------------


async def test_percentages_sum_to_exactly_100(client: AsyncClient, db_session: AsyncSession):
    # 3 reviews split across exit reasons -> naive 1-decimal rounding of
    # 1/3 each gives 33.3 + 33.3 + 33.3 = 99.9. Use enough reviews (7) with
    # an uneven split to actually exercise the largest-remainder path.
    company_id = await _seed_company(db_session)
    reasons = [
        ExitReason.management,
        ExitReason.management,
        ExitReason.compensation,
        ExitReason.compensation,
        ExitReason.compensation,
        ExitReason.culture,
        ExitReason.other,
    ]
    for reason in reasons:
        await _seed_review(db_session, company_id, exit_reason=reason)

    resp = await client.get(f"/companies/{company_id}/stats")
    body = resp.json()

    total_pct = sum(bucket["percentage"] for bucket in body["exit_reason_distribution"].values())
    assert total_pct == pytest.approx(100.0, abs=1e-9)

    total_pct_tenure = sum(
        bucket["percentage"] for bucket in body["avg_tenure_bucket"]["distribution"].values()
    )
    assert total_pct_tenure == pytest.approx(100.0, abs=1e-9)

    total_pct_role = sum(
        bucket["percentage"] for bucket in body["role_level_distribution"].values()
    )
    assert total_pct_role == pytest.approx(100.0, abs=1e-9)

    total_pct_current = sum(
        bucket["percentage"] for bucket in body["current_vs_former_split"].values()
    )
    assert total_pct_current == pytest.approx(100.0, abs=1e-9)


# --------------------------------------------------------------------------
# No composite score anywhere
# --------------------------------------------------------------------------


def _walk_keys(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from _walk_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_keys(item)


async def test_no_composite_score_keys_anywhere(client: AsyncClient, db_session: AsyncSession):
    company_id = await _seed_company(db_session)
    for _ in range(6):
        await _seed_review(db_session, company_id)

    resp = await client.get(f"/companies/{company_id}/stats")
    body = resp.json()

    offending = [
        key
        for key in _walk_keys(body)
        if any(bad in key.lower() for bad in FORBIDDEN_KEY_SUBSTRINGS)
    ]
    assert offending == [], f"forbidden composite-score-like keys found: {offending}"

    resp2 = await client.get(f"/companies/{company_id}/layoff-timeline")
    body2 = resp2.json()
    offending2 = [
        key
        for key in _walk_keys(body2)
        if any(bad in key.lower() for bad in FORBIDDEN_KEY_SUBSTRINGS)
    ]
    assert offending2 == [], f"forbidden composite-score-like keys found: {offending2}"


# --------------------------------------------------------------------------
# corroboration_density fixture
# --------------------------------------------------------------------------


async def test_corroboration_density_known_fixture(client: AsyncClient, db_session: AsyncSession):
    company_id = await _seed_company(db_session)

    review_a = await _seed_review(db_session, company_id)
    review_b = await _seed_review(db_session, company_id)
    review_c = await _seed_review(db_session, company_id)
    # Pad to the minimum-review threshold with plain, uncorroborated reviews.
    for _ in range(settings.stats_min_published_reviews - 3):
        await _seed_review(db_session, company_id)

    await _seed_corroborations(db_session, review_a, 2)
    await _seed_corroborations(db_session, review_b, 0)
    await _seed_corroborations(db_session, review_c, 4)

    resp = await client.get(f"/companies/{company_id}/stats")
    body = resp.json()

    total_reviews = body["total_published_reviews"]
    expected_density = round(6 / total_reviews, 2)  # 2 + 0 + 4 corroborations total
    assert body["corroboration_density"] == expected_density


# --------------------------------------------------------------------------
# Layoff timeline
# --------------------------------------------------------------------------


async def test_layoff_timeline_only_published_grouped_by_year_running_total(
    client: AsyncClient, db_session: AsyncSession
):
    from datetime import UTC, datetime

    from app.models.enums import LayoffSourceType
    from app.models.layoff import LayoffEvent

    company_id = await _seed_company(db_session)
    events = [
        (datetime(2024, 1, 15, tzinfo=UTC), 50, ReviewStatus.published),
        (datetime(2024, 6, 1, tzinfo=UTC), 30, ReviewStatus.published),
        (datetime(2025, 2, 1, tzinfo=UTC), None, ReviewStatus.published),
        (datetime(2025, 3, 1, tzinfo=UTC), 20, ReviewStatus.pending),  # excluded
    ]
    for event_date, headcount, status in events:
        db_session.add(
            LayoffEvent(
                id=uuid.uuid4(),
                company_id=company_id,
                event_date=event_date,
                estimated_headcount=headcount,
                source_type=LayoffSourceType.self_reported,
                status=status,
            )
        )
    await db_session.commit()

    resp = await client.get(f"/companies/{company_id}/layoff-timeline")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_events"] == 3
    years = {y["year"]: y for y in body["years"]}
    assert set(years.keys()) == {2024, 2025}
    assert body["years"][0]["year"] == 2025  # newest year first

    year_2024_headcounts = [e["running_total_headcount"] for e in years[2024]["events"]]
    assert 80 in year_2024_headcounts  # 50 + 30 cumulative
