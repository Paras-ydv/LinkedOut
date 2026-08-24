"""phase 4 follow-up: admin endpoints for the Tier-3 document moderation queue

Adds `DOCUMENT` to the shared `moderated_item_type` enum so
`ModerationAuditLogEntry` (and, if ever used that way, the takedown log /
grievance `related_item_type`) can reference a `ModerationQueueItem` the
same way they already reference a review or layoff event.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction that
    # later uses the new value, but it's fine as the sole statement in its
    # own migration (which is all this migration does).
    op.execute("ALTER TYPE moderated_item_type ADD VALUE IF NOT EXISTS 'DOCUMENT'")


def downgrade() -> None:
    # Postgres has no `ALTER TYPE ... DROP VALUE` — removing an enum value
    # requires rebuilding the type (create new type, migrate columns,
    # drop old type), which isn't worth the complexity/risk for a
    # downgrade path that only ever runs in local dev. Downgrading past
    # this migration with existing 'DOCUMENT' rows present will fail
    # loudly rather than silently corrupt data, which is the safer
    # failure mode here.
    pass
