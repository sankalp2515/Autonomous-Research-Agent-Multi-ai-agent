"""answers.kind — tag chat surface (corpus|paper|selection)

Revision ID: 0005_answer_kind
Revises: 0004_user_profiles
Create Date: 2026-08-08

Idempotent: adds the column only if missing.
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_answer_kind"
down_revision = "0004_user_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("answers")}
    if "kind" not in cols:
        op.add_column("answers", sa.Column(
            "kind", sa.String(16), nullable=False, server_default="corpus"))


def downgrade() -> None:
    op.drop_column("answers", "kind")
