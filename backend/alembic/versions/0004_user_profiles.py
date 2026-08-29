"""user directory (user_profiles)

Revision ID: 0004_user_profiles
Revises: 0003_invitations
Create Date: 2026-08-08

Idempotent: only creates the table if missing.
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_user_profiles"
down_revision = "0003_invitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "user_profiles" in insp.get_table_names():
        return
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, server_default=""),
        sa.Column("display_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_profiles_email", "user_profiles", ["email"])


def downgrade() -> None:
    op.drop_table("user_profiles")
