"""Company-scoped read endpoints: the Phase 3 aggregation engine.

Computed-on-read + a short in-process TTL cache in front (see
app.core.cache, app.services.stats) — no background recompute job, no
Redis. This is the product's core value: structured component
distributions, never a single composite/overall score.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import TTLCache
from app.core.config import settings
from app.core.database import get_db
from app.models.company import Company
from app.schemas.stats import CompanyStatsOut, LayoffTimelineOut
from app.services.stats import compute_company_stats, compute_layoff_timeline

router = APIRouter(prefix="/companies", tags=["companies"])

# Two independent caches (not one shared by key prefix) so a change to one
# endpoint's TTL/eviction never has to reason about the other's keys.
_stats_cache: TTLCache[dict] = TTLCache(ttl_seconds=settings.stats_cache_ttl_seconds)
_timeline_cache: TTLCache[dict] = TTLCache(ttl_seconds=settings.stats_cache_ttl_seconds)


async def _require_company(db: AsyncSession, company_id: uuid.UUID) -> None:
    exists = (
        await db.execute(select(Company.id).where(Company.id == company_id))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="company not found")


@router.get("/{company_id}/stats", response_model=CompanyStatsOut, response_model_exclude_none=True)
async def get_company_stats(
    company_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> CompanyStatsOut:
    await _require_company(db, company_id)

    cache_key = str(company_id)
    cached = _stats_cache.get(cache_key)
    if cached is not None:
        return CompanyStatsOut(**cached)

    result = await compute_company_stats(db, company_id)
    _stats_cache.set(cache_key, result)
    return CompanyStatsOut(**result)


@router.get("/{company_id}/layoff-timeline", response_model=LayoffTimelineOut)
async def get_layoff_timeline(
    company_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> LayoffTimelineOut:
    await _require_company(db, company_id)

    cache_key = str(company_id)
    cached = _timeline_cache.get(cache_key)
    if cached is not None:
        return LayoffTimelineOut(**cached)

    result = await compute_layoff_timeline(db, company_id)
    _timeline_cache.set(cache_key, result)
    return LayoffTimelineOut(**result)
