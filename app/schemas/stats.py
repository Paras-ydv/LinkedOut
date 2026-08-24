"""Pydantic schemas for the aggregation engine (Phase 3).

No schema here has a field resembling a composite/overall score — see
`tests/test_stats.py::test_no_composite_score_keys_anywhere`, which
asserts this at the JSON level so a future edit can't quietly reintroduce
one.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import LayoffSourceType


class DistributionBucket(BaseModel):
    count: int
    percentage: float


class TenureStats(BaseModel):
    modal_bucket: str
    distribution: dict[str, DistributionBucket]


class CompanyStatsOut(BaseModel):
    insufficient_data: bool = False

    # Populated only when insufficient_data is True.
    minimum_required: int | None = None
    current_count: int | None = None

    # Populated only when insufficient_data is False.
    total_published_reviews: int | None = None
    exit_reason_distribution: dict[str, DistributionBucket] | None = None
    avg_tenure_bucket: TenureStats | None = None
    current_vs_former_split: dict[str, DistributionBucket] | None = None
    corroboration_density: float | None = None
    role_level_distribution: dict[str, DistributionBucket] | None = None
    last_updated: datetime | None = None


class LayoffTimelineEvent(BaseModel):
    id: uuid.UUID
    event_date: datetime
    department: str | None
    estimated_headcount: int | None
    source_type: LayoffSourceType
    running_total_headcount: int | None
    created_at: datetime


class LayoffTimelineYear(BaseModel):
    year: int
    events: list[LayoffTimelineEvent]


class LayoffTimelineOut(BaseModel):
    total_events: int
    years: list[LayoffTimelineYear]
