"""email invitations table

Revision ID: 0003_invitations
Revises: 0002_tenancy
Create Date: 2026-08-08

Idempotent: only creates the invitations table if it is missing (a fresh DB's
baseline create_all already made it).
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_invitations"
down_revision = "0002_tenancy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "invitations" in insp.get_table_names():
        return
    op.create_table(
        "invitations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="member"),
        sa.Column("invited_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_invitations_org_id", "invitations", ["org_id"])
    op.create_index("ix_invitations_email", "invitations", ["email"])


def downgrade() -> None:
    op.drop_table("invitations")
