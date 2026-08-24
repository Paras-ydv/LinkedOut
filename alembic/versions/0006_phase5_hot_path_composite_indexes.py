"""phase 5: composite indexes for the aggregation engine's hot read path

Every query in `app.services.stats` (Phase 3) filters on
`company_id == :id AND status == 'PUBLISHED'` — that's the WHERE clause
on `_count_published_reviews`, every `_grouped_counts` call (exit_reason,
tenure_bucket, role_level, is_current_employee), `_corroboration_total`,
`_last_updated`, and `compute_layoff_timeline`. `company_id` already has
its own single-column index (via `index=True` on the FK column, present
since Phase 2), but a query filtering on two equality columns benefits
from one composite index over the two separate single-column indexes
Postgres would otherwise have to bitmap-AND together. This migration adds
`(company_id, status)` composite indexes on `reviews` and `layoff_events`
covering that exact access pattern.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_reviews_company_id_status",
        "reviews",
        ["company_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_layoff_events_company_id_status",
        "layoff_events",
        ["company_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_layoff_events_company_id_status", table_name="layoff_events")
    op.drop_index("ix_reviews_company_id_status", table_name="reviews")
