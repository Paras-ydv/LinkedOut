"""phase 4: moderation & compliance (admin users, audit log, takedown log, grievances)

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- flagged_reason on the pre-existing Review / LayoffEvent tables ---
    op.add_column("reviews", sa.Column("flagged_reason", sa.Text(), nullable=True))
    op.add_column("layoff_events", sa.Column("flagged_reason", sa.Text(), nullable=True))

    # --- admin_users ---
    op.create_table(
        "admin_users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(op.f("ix_admin_users_email"), "admin_users", ["email"], unique=True)

    # --- moderation_audit_log ---
    op.create_table(
        "moderation_audit_log",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("actor_admin_id", sa.UUID(), nullable=True),
        sa.Column(
            "item_type",
            sa.Enum("REVIEW", "LAYOFF_EVENT", name="moderated_item_type"),
            nullable=False,
        ),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column(
            "action", sa.Enum("APPROVE", "REJECT", name="moderation_action"), nullable=False
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["actor_admin_id"], ["admin_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_moderation_audit_log_actor_admin_id"),
        "moderation_audit_log",
        ["actor_admin_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_moderation_audit_log_item_id"), "moderation_audit_log", ["item_id"], unique=False
    )

    # --- takedown_log_entries ---
    op.create_table(
        "takedown_log_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "item_type",
            sa.Enum("REVIEW", "LAYOFF_EVENT", name="moderated_item_type"),
            nullable=False,
        ),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column(
            "requester_type",
            sa.Enum(
                "COURT_ORDER",
                "GOVERNMENT_DIRECTION",
                "COMPANY_LEGAL_REQUEST",
                "USER_REPORT",
                "INTERNAL_MODERATION",
                name="takedown_requester_type",
            ),
            nullable=False,
        ),
        sa.Column("requester_detail", sa.String(length=500), nullable=True),
        sa.Column("complied", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_takedown_log_entries_item_id"), "takedown_log_entries", ["item_id"], unique=False
    )
    op.create_index(
        op.f("ix_takedown_log_entries_created_at"),
        "takedown_log_entries",
        ["created_at"],
        unique=False,
    )

    # --- grievance_complaints ---
    op.create_table(
        "grievance_complaints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("complainant_contact", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "related_item_type",
            sa.Enum("REVIEW", "LAYOFF_EVENT", name="moderated_item_type"),
            nullable=True,
        ),
        sa.Column("related_item_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("RECEIVED", "ACKNOWLEDGED", "RESOLVED", name="grievance_status"),
            nullable=False,
        ),
        sa.Column("sla_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_grievance_complaints_sla_deadline"),
        "grievance_complaints",
        ["sla_deadline"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_grievance_complaints_sla_deadline"), table_name="grievance_complaints")
    op.drop_table("grievance_complaints")
    op.execute("DROP TYPE IF EXISTS grievance_status")

    op.drop_index(op.f("ix_takedown_log_entries_created_at"), table_name="takedown_log_entries")
    op.drop_index(op.f("ix_takedown_log_entries_item_id"), table_name="takedown_log_entries")
    op.drop_table("takedown_log_entries")
    op.execute("DROP TYPE IF EXISTS takedown_requester_type")

    op.drop_index(op.f("ix_moderation_audit_log_item_id"), table_name="moderation_audit_log")
    op.drop_index(
        op.f("ix_moderation_audit_log_actor_admin_id"), table_name="moderation_audit_log"
    )
    op.drop_table("moderation_audit_log")
    op.execute("DROP TYPE IF EXISTS moderation_action")

    # moderated_item_type is used by three tables above; drop it only after
    # all of them are gone.
    op.execute("DROP TYPE IF EXISTS moderated_item_type")

    op.drop_index(op.f("ix_admin_users_email"), table_name="admin_users")
    op.drop_table("admin_users")

    op.drop_column("layoff_events", "flagged_reason")
    op.drop_column("reviews", "flagged_reason")
