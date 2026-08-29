"""multi-tenancy: organizations, memberships, projects.org_id + backfill

Revision ID: 0002_tenancy
Revises: 0001_baseline
Create Date: 2026-08-08

Idempotent by design so it is safe on BOTH:
  * a fresh DB where the baseline's create_all already built the tenancy tables
    and the projects.org_id column, and
  * an existing pre-tenancy DB that only has the old projects table.

It ensures the org/membership tables exist, adds projects.org_id if missing, and
backfills a personal org (+ owner membership) for every legacy project so no row
is left without a tenant.
"""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0002_tenancy"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def _has_table(insp, name: str) -> bool:
    return name in insp.get_table_names()


def _has_column(insp, table: str, col: str) -> bool:
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)

    if not _has_table(insp, "organizations"):
        op.create_table(
            "organizations",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("personal", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_by", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_organizations_created_by", "organizations", ["created_by"])

    if not _has_table(insp, "memberships"):
        op.create_table(
            "memberships",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("org_id", sa.String(32), nullable=False),
            sa.Column("user_id", sa.String(64), nullable=False),
            sa.Column("role", sa.String(16), nullable=False, server_default="member"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_memberships_org_id", "memberships", ["org_id"])
        op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
        op.create_index("ux_membership_user_org", "memberships", ["user_id", "org_id"], unique=True)

    if not _has_column(insp, "projects", "org_id"):
        op.add_column("projects", sa.Column("org_id", sa.String(32), nullable=True))
        op.create_index("ix_projects_org_id", "projects", ["org_id"])

    _backfill(conn)


def _backfill(conn) -> None:
    now = datetime.now(timezone.utc)
    owners = conn.execute(sa.text(
        "SELECT DISTINCT owner_id FROM projects WHERE org_id IS NULL")).fetchall()
    for (owner,) in owners:
        row = conn.execute(sa.text(
            "SELECT id FROM organizations WHERE created_by=:o AND personal=true LIMIT 1"),
            {"o": owner}).fetchone()
        if row:
            org_id = row[0]
        else:
            org_id = uuid.uuid4().hex
            conn.execute(sa.text(
                "INSERT INTO organizations (id,name,personal,created_by,created_at,updated_at) "
                "VALUES (:id,'Personal workspace',true,:o,:t,:t)"),
                {"id": org_id, "o": owner, "t": now})
            conn.execute(sa.text(
                "INSERT INTO memberships (id,org_id,user_id,role,created_at,updated_at) "
                "VALUES (:id,:org,:o,'owner',:t,:t)"),
                {"id": uuid.uuid4().hex, "org": org_id, "o": owner, "t": now})
        conn.execute(sa.text(
            "UPDATE projects SET org_id=:org WHERE owner_id=:o AND org_id IS NULL"),
            {"org": org_id, "o": owner})


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if _has_column(insp, "projects", "org_id"):
        op.drop_index("ix_projects_org_id", table_name="projects")
        op.drop_column("projects", "org_id")
    op.drop_table("memberships")
    op.drop_table("organizations")
