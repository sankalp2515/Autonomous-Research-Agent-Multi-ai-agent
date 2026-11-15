"""answers.meta — the conversational envelope (segments, refusal kind, sources)

Revision ID: 0006_answer_meta
Revises: 0005_answer_kind
Create Date: 2026-08-31

Restoring a conversation has to restore the ANSWER the user read: which
sentences were evidential and which derived, WHY a turn refused, and what it
looked at. Reconstructing that from claims alone loses every refusal's reason,
which is the most informative thing Ask produces.

Idempotent: adds the column only if missing.
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_answer_meta"
down_revision = "0005_answer_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("answers")}
    if "meta" not in cols:
        op.add_column("answers", sa.Column(
            "meta", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("answers", "meta")
