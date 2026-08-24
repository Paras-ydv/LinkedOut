"""Aggregation engine (Phase 3): per-company stats + layoff timeline.

Computed-on-read: every call here queries Postgres and aggregates with
SQL (`GROUP BY`/`COUNT`/`func.max`), never by pulling ORM objects into
Python and looping — that's both slower and, for the count/percentage
math, exactly the kind of thing that's easy to get subtly wrong at scale.
No background recompute job exists (or is needed) at this data size; see
`app.core.cache` for the thin TTL cache sitting in front of this module.

Hard product constraint, not a suggestion: nothing in this module ever
computes or returns a single composite/overall score. Every stat here is
a component distribution or a plain count — see
`tests/test_stats.py::test_no_composite_score_keys_anywhere` for the test
that guards this.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.percentages import distribution_with_percentages
from app.models.enums import ExitReason, ReviewStatus, RoleLevel, TenureBucket
from app.models.layoff import LayoffEvent
from app.models.review import Corroboration, Review


async def _count_published_reviews(db: AsyncSession, company_id) -> int:
    stmt = (
        select(func.count())
        .select_from(Review)
        .where(Review.company_id == company_id, Review.status == ReviewStatus.published)
    )
    return (await db.execute(stmt)).scalar_one()


async def _grouped_counts(db: AsyncSession, column, company_id) -> dict:
    stmt = (
        select(column, func.count())
        .where(Review.company_id == company_id, Review.status == ReviewStatus.published)
        .group_by(column)
    )
    result = await db.execute(stmt)
    return {row[0]: row[1] for row in result}


def _full_enum_counts(enum_cls, grouped: dict) -> dict[str, int]:
    """Every enum member present (0 if unseen), in declaration order."""
    return {member.value: grouped.get(member, 0) for member in enum_cls}


async def _corroboration_total(db: AsyncSession, company_id) -> int:
    # LEFT JOIN + COUNT(corroborations.id) ignores the NULL rows a review
    # with zero corroborations produces, so this is exactly
    # "total corroborations across published reviews for this company" —
    # not "number of reviews that have at least one".
    stmt = (
        select(func.count(Corroboration.id))
        .select_from(Review)
        .outerjoin(Corroboration, Corroboration.review_id == Review.id)
        .where(Review.company_id == company_id, Review.status == ReviewStatus.published)
    )
    return (await db.execute(stmt)).scalar_one()


async def _last_updated(db: AsyncSession, company_id) -> datetime | None:
    review_max = select(func.max(Review.created_at)).where(
        Review.company_id == company_id, Review.status == ReviewStatus.published
    )
    layoff_max = select(func.max(LayoffEvent.created_at)).where(
        LayoffEvent.company_id == company_id, LayoffEvent.status == ReviewStatus.published
    )
    review_ts = (await db.execute(review_max)).scalar_one_or_none()
    layoff_ts = (await db.execute(layoff_max)).scalar_one_or_none()
    candidates = [ts for ts in (review_ts, layoff_ts) if ts is not None]
    return max(candidates) if candidates else None


async def compute_company_stats(db: AsyncSession, company_id) -> dict:
    """Returns either the full stats payload or an insufficient-data payload.

    Below `settings.stats_min_published_reviews` PUBLISHED reviews, returns
    `{"insufficient_data": true, "minimum_required": N, "current_count": n}`
    instead of percentages — a handful of reviews is both statistically
    meaningless and a re-identification risk.
    """
    total = await _count_published_reviews(db, company_id)

    if total < settings.stats_min_published_reviews:
        return {
            "insufficient_data": True,
            "minimum_required": settings.stats_min_published_reviews,
            "current_count": total,
        }

    exit_reason_counts = _full_enum_counts(
        ExitReason, await _grouped_counts(db, Review.exit_reason, company_id)
    )
    tenure_counts = _full_enum_counts(
        TenureBucket, await _grouped_counts(db, Review.tenure_bucket, company_id)
    )
    role_level_counts = _full_enum_counts(
        RoleLevel, await _grouped_counts(db, Review.role_level, company_id)
    )
    current_former_grouped = await _grouped_counts(db, Review.is_current_employee, company_id)
    current_former_counts = {
        "current": current_former_grouped.get(True, 0),
        "former": current_former_grouped.get(False, 0),
    }

    tenure_distribution = distribution_with_percentages(tenure_counts, total)
    modal_tenure_bucket = max(tenure_counts, key=lambda key: tenure_counts[key])

    corroboration_total = await _corroboration_total(db, company_id)
    last_updated = await _last_updated(db, company_id)

    return {
        "insufficient_data": False,
        "total_published_reviews": total,
        "exit_reason_distribution": distribution_with_percentages(exit_reason_counts, total),
        "avg_tenure_bucket": {
            "modal_bucket": modal_tenure_bucket,
            "distribution": tenure_distribution,
        },
        "current_vs_former_split": distribution_with_percentages(current_former_counts, total),
        "corroboration_density": round(corroboration_total / total, 2),
        "role_level_distribution": distribution_with_percentages(role_level_counts, total),
        "last_updated": last_updated,
    }


async def compute_layoff_timeline(db: AsyncSession, company_id) -> dict:
    """Published layoff events, grouped by year, newest year first.

    Running total headcount accumulates forward in time (oldest -> newest)
    across events that report `estimated_headcount`; events without a
    headcount don't contribute to the running total but are still listed.
    This grouping/running-total pass is presentation logic over a single
    already-sorted query result, not a second N+1 query per event.
    """
    stmt = (
        select(LayoffEvent)
        .where(LayoffEvent.company_id == company_id, LayoffEvent.status == ReviewStatus.published)
        .order_by(LayoffEvent.event_date.asc())
    )
    events = (await db.execute(stmt)).scalars().all()

    running_total = 0
    enriched = []
    for event in events:
        if event.estimated_headcount is not None:
            running_total += event.estimated_headcount
        enriched.append(
            {
                "id": event.id,
                "event_date": event.event_date,
                "department": event.department,
                "estimated_headcount": event.estimated_headcount,
                "source_type": event.source_type,
                "running_total_headcount": running_total if running_total > 0 else None,
                "created_at": event.created_at,
            }
        )

    # Newest year first; within a year, newest event first.
    enriched.reverse()
    years: dict[int, list[dict]] = {}
    for item in enriched:
        years.setdefault(item["event_date"].year, []).append(item)

    return {
        "total_events": len(enriched),
        "years": [{"year": year, "events": years[year]} for year in sorted(years, reverse=True)],
    }
