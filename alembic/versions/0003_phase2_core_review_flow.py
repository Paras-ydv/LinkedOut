"""phase 2: core review flow (reviews, corroborations, layoff events, employer)

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column(
            "exit_reason",
            sa.Enum(
                "MANAGEMENT",
                "COMPENSATION",
                "LAYOFFS",
                "CULTURE",
                "GROWTH",
                "RELOCATION",
                "OTHER",
                name="exit_reason",
            ),
            nullable=False,
        ),
        sa.Column(
            "tenure_bucket",
            sa.Enum(
                "LESS_THAN_1YR", "ONE_TO_3YR", "THREE_TO_5YR", "FIVE_PLUS_YR", name="tenure_bucket"
            ),
            nullable=False,
        ),
        sa.Column("department", sa.String(length=100), nullable=False),
        sa.Column(
            "role_level",
            sa.Enum("IC", "MANAGER", "SENIOR_MANAGER", "DIRECTOR_PLUS", name="role_level"),
            nullable=False,
        ),
        sa.Column("is_current_employee", sa.Boolean(), nullable=False),
        sa.Column("prose", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "PUBLISHED", "REJECTED", name="review_status"),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "company_id", name="uq_reviews_user_company"),
    )
    op.create_index(op.f("ix_reviews_user_id"), "reviews", ["user_id"], unique=False)
    op.create_index(op.f("ix_reviews_company_id"), "reviews", ["company_id"], unique=False)

    op.create_table(
        "corroborations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("review_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("comment", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id", "user_id", name="uq_corroborations_review_user"),
    )
    op.create_index(op.f("ix_corroborations_review_id"), "corroborations", ["review_id"], unique=False)
    op.create_index(op.f("ix_corroborations_user_id"), "corroborations", ["user_id"], unique=False)

    op.create_table(
        "layoff_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("department", sa.String(length=100), nullable=True),
        sa.Column("estimated_headcount", sa.Integer(), nullable=True),
        sa.Column(
            "source_type",
            sa.Enum("SELF_REPORTED", "NEWS", name="layoff_source_type"),
            nullable=False,
        ),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("submitted_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("PENDING", "PUBLISHED", "REJECTED", name="review_status"),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_layoff_events_company_id"), "layoff_events", ["company_id"], unique=False)
    op.create_index(op.f("ix_layoff_events_event_date"), "layoff_events", ["event_date"], unique=False)

    op.create_table(
        "employer_accounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("domain_hash", sa.String(length=64), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", name="uq_employer_accounts_company_id"),
    )
    op.create_index(
        op.f("ix_employer_accounts_company_id"), "employer_accounts", ["company_id"], unique=False
    )
    op.create_index(
        op.f("ix_employer_accounts_domain_hash"), "employer_accounts", ["domain_hash"], unique=False
    )

    op.create_table(
        "employer_responses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("review_id", sa.UUID(), nullable=False),
        sa.Column("employer_account_id", sa.UUID(), nullable=False),
        sa.Column("response_text", sa.String(length=1000), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["employer_account_id"], ["employer_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id", name="uq_employer_responses_review_id"),
    )
    op.create_index(
        op.f("ix_employer_responses_review_id"), "employer_responses", ["review_id"], unique=False
    )
    op.create_index(
        op.f("ix_employer_responses_employer_account_id"),
        "employer_responses",
        ["employer_account_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_employer_responses_employer_account_id"), table_name="employer_responses")
    op.drop_index(op.f("ix_employer_responses_review_id"), table_name="employer_responses")
    op.drop_table("employer_responses")

    op.drop_index(op.f("ix_employer_accounts_domain_hash"), table_name="employer_accounts")
    op.drop_index(op.f("ix_employer_accounts_company_id"), table_name="employer_accounts")
    op.drop_table("employer_accounts")

    op.drop_index(op.f("ix_layoff_events_event_date"), table_name="layoff_events")
    op.drop_index(op.f("ix_layoff_events_company_id"), table_name="layoff_events")
    op.drop_table("layoff_events")

    op.drop_index(op.f("ix_corroborations_user_id"), table_name="corroborations")
    op.drop_index(op.f("ix_corroborations_review_id"), table_name="corroborations")
    op.drop_table("corroborations")

    op.drop_index(op.f("ix_reviews_company_id"), table_name="reviews")
    op.drop_index(op.f("ix_reviews_user_id"), table_name="reviews")
    op.drop_table("reviews")

    op.execute("DROP TYPE IF EXISTS layoff_source_type")
    op.execute("DROP TYPE IF EXISTS review_status")
    op.execute("DROP TYPE IF EXISTS role_level")
    op.execute("DROP TYPE IF EXISTS tenure_bucket")
    op.execute("DROP TYPE IF EXISTS exit_reason")
