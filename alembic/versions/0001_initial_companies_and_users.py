"""initial: companies and users

Revision ID: 0001
Revises:
Create Date: 2026-08-24 13:09:33.051333

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("industry", sa.String(length=120), nullable=True),
        sa.Column(
            "corporate_email_domains",
            sa.ARRAY(sa.String(length=255)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "employee_size_bucket",
            sa.Enum(
                "micro", "small", "medium", "large", "enterprise",
                name="employee_size_bucket",
            ),
            nullable=True,
        ),
        sa.Column("hq_location", sa.String(length=255), nullable=True),
        sa.Column("logo_url", sa.String(length=500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_companies_slug"), "companies", ["slug"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("phone_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "verification_tier",
            sa.Enum(
                "unverified", "phone", "email", "document",
                name="verification_tier",
            ),
            server_default="unverified",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_phone_hash"), "users", ["phone_hash"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_phone_hash"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_companies_slug"), table_name="companies")
    op.drop_table("companies")

    # `drop_table` above does NOT drop the native Postgres ENUM types the
    # columns used (SQLAlchemy only auto-creates/-drops a named enum type
    # alongside a *metadata-driven* create_all/drop_all, not around a bare
    # CREATE/DROP TABLE emitted by Alembic). Without this, re-running
    # `upgrade` after a `downgrade` fails with "type already exists".
    op.execute("DROP TYPE IF EXISTS verification_tier")
    op.execute("DROP TYPE IF EXISTS employee_size_bucket")
