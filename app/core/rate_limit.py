"""Simple DB-backed rate limiting.

Phase 1 doesn't add Redis; instead we count recent rows in the table that
already exists for the flow being limited (otp_codes / email_verification_codes)
within a sliding window. That's enough for a first cut and swaps out for a
Redis-backed limiter later without changing the call sites.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"rate limit exceeded, retry after {retry_after_seconds}s")


async def enforce_rate_limit(
    db: AsyncSession,
    *,
    model,
    key_column,
    key_value: str,
    window_minutes: int,
    max_requests: int,
) -> None:
    """Raise `RateLimitExceeded` if `key_value` has made >= max_requests rows
    of `model` (matched via `key_column`) within the trailing window.
    """
    window_start = datetime.now(UTC) - timedelta(minutes=window_minutes)
    count_stmt = (
        select(func.count())
        .select_from(model)
        .where(key_column == key_value, model.created_at >= window_start)
    )
    count = (await db.execute(count_stmt)).scalar_one()
    if count >= max_requests:
        retry_after = window_minutes * 60
        raise RateLimitExceeded(retry_after_seconds=retry_after)
