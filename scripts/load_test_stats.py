#!/usr/bin/env python3
"""Phase 5 hardening: load/correctness test for the aggregation engine.

Standalone script, not a pytest test — this is meant to be run by a human
against a real running instance (`uvicorn app.main:app`) with a real
Postgres behind it, to answer two questions pytest's fast, small-fixture
tests can't:

  1. Does `GET /companies/{id}/stats` stay fast once a company has a
     realistic number of reviews (hundreds, not the handful pytest seeds
     per test)?
  2. Does the largest-remainder percentage rounding (app/core/percentages.py)
     still sum to exactly 100.0 against real, randomly-distributed seeded
     data — not just the hand-picked fixture in tests/test_stats.py that
     was specifically chosen to exercise the rounding edge case?

What it does:
  - Seeds ~20 companies and ~500 reviews across them directly via the ORM
    (bypassing the API's tier/auth checks entirely — this is seed data,
    not a simulation of real user traffic through auth). Exit reason,
    tenure bucket, role level, current/former, and status are all drawn
    from weighted random distributions meant to look like real data:
    lopsided (not uniform) category splits, and a status split that's
    mostly PUBLISHED with a realistic minority PENDING/REJECTED, so most
    (not all) seeded companies clear the insufficient-data threshold.
  - Calls `GET /companies/{id}/stats` for every seeded company over real
    HTTP against a running server, times each call, and re-verifies (on
    the actual response bodies, not the seed data) that every
    percentage-distribution field sums to exactly 100.0 and that no
    composite-score-shaped key appears anywhere in the response — the
    same two guarantees tests/test_stats.py checks against small fixtures,
    now checked against ~500 real rows.
  - Prints a timing summary (min/p50/p95/max) and a pass/fail line per
    correctness check.

Usage:
    # 1. Point this at a *test-safe* database — it seeds real rows and
    #    does not clean up after itself (see the warning below).
    export DATABASE_URL=postgresql+asyncpg://linkedout:linkedout@localhost:5432/linkedout_loadtest
    alembic upgrade head

    # 2. Start the API against that same database in another terminal:
    uvicorn app.main:app --port 8000

    # 3. Run the script:
    python scripts/load_test_stats.py
    python scripts/load_test_stats.py --base-url http://localhost:8000 --companies 20 --reviews 500

WARNING: this script INSERTS rows and does not delete them. Never point
it at a database you care about — use a disposable one, same posture as
the test suite's `linkedout_test` guardrail (see tests/conftest.py),
except this script does not enforce that guardrail itself since it's a
deliberately manual, human-run tool, not part of CI.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, ".")  # run as `python scripts/load_test_stats.py` from repo root

from app.core.config import settings  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.enums import ExitReason, ReviewStatus, RoleLevel, TenureBucket  # noqa: E402
from app.models.review import Review  # noqa: E402
from app.models.user import User  # noqa: E402

# Forbidden key substrings, same list as tests/test_stats.py — kept
# duplicated rather than imported so this script has zero dependency on
# the test suite and can be handed to someone reading only `scripts/`.
_FORBIDDEN_KEY_SUBSTRINGS = ("score", "index", "overall", "rating", "toxicity", "composite")

# Weighted, deliberately lopsided distributions — real exit-interview data
# is not uniform across categories, and a uniform seed wouldn't exercise
# the largest-remainder rounding path nearly as hard as a skewed one does.
_EXIT_REASON_WEIGHTS = {
    ExitReason.compensation: 30,
    ExitReason.management: 22,
    ExitReason.culture: 18,
    ExitReason.growth: 15,
    ExitReason.layoffs: 8,
    ExitReason.relocation: 4,
    ExitReason.other: 3,
}
_TENURE_WEIGHTS = {
    TenureBucket.less_than_1yr: 20,
    TenureBucket.one_to_3yr: 40,
    TenureBucket.three_to_5yr: 25,
    TenureBucket.five_plus_yr: 15,
}
_ROLE_LEVEL_WEIGHTS = {
    RoleLevel.ic: 60,
    RoleLevel.manager: 25,
    RoleLevel.senior_manager: 10,
    RoleLevel.director_plus: 5,
}
_STATUS_WEIGHTS = {
    ReviewStatus.published: 82,
    ReviewStatus.pending: 12,
    ReviewStatus.rejected: 6,
}

_DEPARTMENTS = [
    "Engineering",
    "Sales",
    "Marketing",
    "Customer Success",
    "Operations",
    "Finance",
    "Product",
    "Human Resources",
]


def _weighted_choice(weights: dict) -> object:
    keys = list(weights.keys())
    values = list(weights.values())
    return random.choices(keys, weights=values, k=1)[0]


async def seed(engine, n_companies: int, n_reviews: int) -> list[uuid.UUID]:
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    company_ids: list[uuid.UUID] = []

    async with session_factory() as session:
        for i in range(n_companies):
            company = Company(
                id=uuid.uuid4(),
                name=f"LoadTest Co {i} {uuid.uuid4().hex[:6]}",
                slug=f"loadtest-co-{i}-{uuid.uuid4().hex[:6]}",
                corporate_email_domains=[f"loadtest{i}.example.com"],
            )
            session.add(company)
            company_ids.append(company.id)
        await session.commit()

        # Reviews are spread unevenly across companies (some get many,
        # some get few) rather than an exact n_reviews / n_companies each
        # — real traffic isn't evenly distributed across employers either,
        # and this also exercises the insufficient_data path for whatever
        # companies land under the threshold.
        remaining = n_reviews
        for idx, company_id in enumerate(company_ids):
            companies_left = n_companies - idx
            # Randomize this company's share of what's left, weighted so
            # earlier companies don't starve later ones.
            share = max(
                0, int(random.gauss(remaining / companies_left, remaining / companies_left / 2))
            )
            share = min(share, remaining)
            for _ in range(share):
                user = User(id=uuid.uuid4(), phone_hash=uuid.uuid4().hex, verification_tier="email")
                session.add(user)
                await session.flush()  # need user.id before the FK insert below

                review = Review(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    company_id=company_id,
                    exit_reason=_weighted_choice(_EXIT_REASON_WEIGHTS),
                    tenure_bucket=_weighted_choice(_TENURE_WEIGHTS),
                    department=random.choice(_DEPARTMENTS),
                    role_level=_weighted_choice(_ROLE_LEVEL_WEIGHTS),
                    is_current_employee=random.random() < 0.15,
                    prose="Seeded load-test review text, no real content.",
                    status=_weighted_choice(_STATUS_WEIGHTS),
                    created_at=datetime.now(UTC) - timedelta(days=random.randint(0, 400)),
                )
                session.add(review)
            remaining -= share
            await session.commit()

    return company_ids


def _walk_keys(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from _walk_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_keys(item)


def _sum_percentages(distribution: dict) -> float | None:
    if not distribution:
        return None
    return round(sum(bucket["percentage"] for bucket in distribution.values()), 9)


async def run_stats_calls(
    base_url: str, company_ids: list[uuid.UUID]
) -> tuple[list[float], list[str]]:
    timings: list[float] = []
    failures: list[str] = []

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        for company_id in company_ids:
            start = time.perf_counter()
            resp = await client.get(f"/companies/{company_id}/stats")
            elapsed_ms = (time.perf_counter() - start) * 1000
            timings.append(elapsed_ms)

            if resp.status_code != 200:
                failures.append(f"{company_id}: unexpected status {resp.status_code}")
                continue

            body = resp.json()

            if body.get("insufficient_data"):
                continue  # nothing to percentage-check for this one

            for field in (
                "exit_reason_distribution",
                "role_level_distribution",
                "current_vs_former_split",
            ):
                total = _sum_percentages(body.get(field, {}))
                if total is not None and total != 100.0:
                    failures.append(f"{company_id}: {field} sums to {total}, not 100.0")

            tenure_dist = body.get("avg_tenure_bucket", {}).get("distribution", {})
            total = _sum_percentages(tenure_dist)
            if total is not None and total != 100.0:
                failures.append(
                    f"{company_id}: avg_tenure_bucket.distribution sums to {total}, not 100.0"
                )

            offending_keys = [
                key
                for key in _walk_keys(body)
                if any(bad in key.lower() for bad in _FORBIDDEN_KEY_SUBSTRINGS)
            ]
            if offending_keys:
                failures.append(
                    f"{company_id}: forbidden composite-score-like keys: {offending_keys}"
                )

    return timings, failures


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * pct
    f, c = int(k), min(int(k) + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--companies", type=int, default=20)
    parser.add_argument("--reviews", type=int, default=500)
    parser.add_argument(
        "--skip-seed",
        action="store_true",
        help="skip seeding and just re-run stats calls against companies already seeded "
        "by a prior run (requires --company-ids-file, not currently implemented — "
        "primarily useful when iterating on this script itself against a DB you "
        "already seeded once).",
    )
    args = parser.parse_args()

    print(f"Database: {settings.database_url}")
    print(f"API base URL: {args.base_url}")
    print(f"Seeding ~{args.companies} companies / ~{args.reviews} reviews...")

    engine = create_async_engine(settings.database_url, future=True)
    seed_start = time.perf_counter()
    company_ids = await seed(engine, args.companies, args.reviews)
    seed_elapsed = time.perf_counter() - seed_start
    await engine.dispose()
    print(f"Seeded {len(company_ids)} companies in {seed_elapsed:.2f}s.")

    print(f"\nCalling GET /companies/{{id}}/stats for each of {len(company_ids)} companies...")
    try:
        timings, failures = await run_stats_calls(args.base_url, company_ids)
    except httpx.ConnectError as exc:
        print(
            f"\nERROR: could not reach {args.base_url} — is `uvicorn app.main:app` "
            f"running against the same database this script just seeded? ({exc})"
        )
        return 2

    sorted_timings = sorted(timings)
    print("\n--- Timing (ms) ---")
    print(f"  count : {len(timings)}")
    print(f"  min   : {min(timings):.2f}")
    print(f"  p50   : {_percentile(sorted_timings, 0.50):.2f}")
    print(f"  p95   : {_percentile(sorted_timings, 0.95):.2f}")
    print(f"  max   : {max(timings):.2f}")
    print(f"  mean  : {statistics.mean(timings):.2f}")

    print("\n--- Correctness ---")
    if failures:
        print(f"  FAILED: {len(failures)} issue(s) found:")
        for f in failures:
            print(f"    - {f}")
        return 1

    print("  PASSED: every distribution summed to exactly 100.0; no composite-score keys found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
