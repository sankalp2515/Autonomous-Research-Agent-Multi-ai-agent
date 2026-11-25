"""runs.launch_params - the filters a run was launched with

Revision ID: 0008_run_launch_params
Revises: 0007_pgvector
Create Date: 2026-11-19

Recovery rebuilds a job from the Run row, and the row did not record the
launch filters (scope, year window, citation floor, hand-picked papers). A run
orphaned before its first checkpoint therefore resumed with defaults and
silently answered a broader question than the user asked.

Idempotent: adds the column only if missing.
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_run_launch_params"
down_revision = "0007_pgvector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("runs")}
    if "launch_params" not in cols:
        op.add_column("runs", sa.Column(
            "launch_params", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("runs", "launch_params")
