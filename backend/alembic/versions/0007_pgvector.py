"""chunks.embedding: dense vectors move into Postgres (pgvector)

Revision ID: 0007_pgvector
Revises: 0006_answer_meta
Create Date: 2026-11-19

Vectors used to live in Qdrant, keyed by chunk id, written separately from the
chunk row with no shared transaction. They now live on the row. See
app/stores/pgvector_store.py for why, and scripts/backfill_pgvector.py to copy
existing vectors across without re-embedding.

No ANN index on purpose: retrieval is always scoped to one project (a few
thousand chunks) or one document (~60), where an exact scan is milliseconds and
never misses a neighbour. Add an HNSW index in a later revision only when a
project passes ~100k chunks - and then with pgvector >= 0.8 iterative scans, or
filtered queries return fewer rows than asked for.

Idempotent. The extension is created here rather than assumed, because a fresh
Cloud SQL / Supabase database has pgvector AVAILABLE but not ENABLED.
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_pgvector"
down_revision = "0006_answer_meta"
branch_labels = None
depends_on = None

DIM = 384  # app.db.models.EMBEDDING_DIM at the time of this revision - frozen.


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    cols = {c["name"] for c in sa.inspect(bind).get_columns("chunks")}
    if "embedding" not in cols:
        op.execute(f"ALTER TABLE chunks ADD COLUMN embedding vector({DIM})")
    # Vectors that were in Qdrant are not here yet. Mark every chunk cold so
    # nothing claims a vector it does not have; the backfill script (or the
    # reindex job) sets `embedded` back to true as it writes each vector.
    op.execute("UPDATE chunks SET embedded = false WHERE embedding IS NULL AND embedded")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS embedding")
    # The extension is left installed: other objects may depend on it, and
    # dropping it is not this revision's to decide.
