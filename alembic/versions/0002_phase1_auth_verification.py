"""phase 1: auth & verification (otp, email verification, moderation queue)

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_domain_hash", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_users_email_domain_hash"), "users", ["email_domain_hash"], unique=False
    )

    op.create_table(
        "otp_codes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("phone_hash", sa.String(length=64), nullable=False),
        sa.Column("otp_hash", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_otp_codes_phone_hash"), "otp_codes", ["phone_hash"], unique=False)
    op.create_index(op.f("ix_otp_codes_created_at"), "otp_codes", ["created_at"], unique=False)

    op.create_table(
        "email_verification_codes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("domain_hash", sa.String(length=64), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_email_verification_codes_user_id"),
        "email_verification_codes",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_email_verification_codes_created_at"),
        "email_verification_codes",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "moderation_queue",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "doc_type",
            sa.Enum("offer_letter", "payslip", "id_document", "other", name="document_type"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("ephemeral_path", sa.String(length=512), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", name="moderation_status"),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_moderation_queue_user_id"), "moderation_queue", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_moderation_queue_content_hash"), "moderation_queue", ["content_hash"], unique=False
    )
    op.create_index(
        op.f("ix_moderation_queue_created_at"), "moderation_queue", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_moderation_queue_created_at"), table_name="moderation_queue")
    op.drop_index(op.f("ix_moderation_queue_content_hash"), table_name="moderation_queue")
    op.drop_index(op.f("ix_moderation_queue_user_id"), table_name="moderation_queue")
    op.drop_table("moderation_queue")

    op.drop_index(
        op.f("ix_email_verification_codes_created_at"), table_name="email_verification_codes"
    )
    op.drop_index(
        op.f("ix_email_verification_codes_user_id"), table_name="email_verification_codes"
    )
    op.drop_table("email_verification_codes")

    op.drop_index(op.f("ix_otp_codes_created_at"), table_name="otp_codes")
    op.drop_index(op.f("ix_otp_codes_phone_hash"), table_name="otp_codes")
    op.drop_table("otp_codes")

    op.drop_index(op.f("ix_users_email_domain_hash"), table_name="users")
    op.drop_column("users", "email_domain_hash")

    op.execute("DROP TYPE IF EXISTS moderation_status")
    op.execute("DROP TYPE IF EXISTS document_type")
