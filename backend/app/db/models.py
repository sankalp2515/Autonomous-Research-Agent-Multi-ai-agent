"""System-of-record schema (Supabase Postgres / any Postgres).

Custody rule from ARCHITECTURE.md: this database is durable truth.
Qdrant holds only vectors keyed by chunk id (rebuildable from here).
Redis holds only ephemeral state (rebuildable from here).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, JSON,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# ── Multi-tenancy: organizations, memberships, roles ─────────────────────────
# Tenancy boundary is the ORG. Every project belongs to an org; a user reaches a
# project through a Membership in that org, with a role. A user's first sign-in
# gets a "personal" org (org of one) so single-user flows are unchanged.

# Role ordering (higher = more power). Authorization checks compare against a
# required minimum, so "admin" satisfies a "member"-or-above requirement.
ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    # A personal org (auto-created for one user) vs a real shared team org.
    personal: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(64), index=True, default="local")


class Membership(TimestampMixin, Base):
    """A user's role within an org. (user_id, org_id) is unique."""
    __tablename__ = "memberships"
    __table_args__ = (
        Index("ux_membership_user_org", "user_id", "org_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16), default="member")  # see ROLE_RANK


class UserProfile(TimestampMixin, Base):
    """A directory row per user — populated from the auth token on sign-in, so
    member/invite lists can show a real email + name instead of an opaque id."""
    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), index=True, default="")
    display_name: Mapped[str] = mapped_column(String(200), default="")


class Invitation(TimestampMixin, Base):
    """A pending invite to join an org by EMAIL. Accepted the next time the
    invited email signs in (auto-matched), turning into a Membership."""
    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(32), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[str] = mapped_column(String(16), default="member")
    invited_by: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|accepted|revoked


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String(64), index=True, default="local")
    # Tenancy: the org that owns this project. Nullable during rollout/backfill;
    # a null org_id falls back to legacy owner_id checks (see api authz).
    org_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")

    documents: Mapped[list["Document"]] = relationship(back_populates="project")


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(16))  # paper | repo | blog | upload
    title: Mapped[str] = mapped_column(Text, default="")
    authors: Mapped[list] = mapped_column(JSON, default=list)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str] = mapped_column(Text, default="")
    # Dedup keys
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    doi: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    arxiv_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # Preprint/published linkage: both versions kept, linked, never collapsed.
    supersedes_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Honesty flags (Elicit lesson: never silently degrade to abstract-only)
    full_text_available: Mapped[bool] = mapped_column(Boolean, default=False)
    abstract_only: Mapped[bool] = mapped_column(Boolean, default=False)
    language: Mapped[str] = mapped_column(String(8), default="en")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # pending | parsing | indexed | failed | quarantined | tombstoned
    status_reason: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    project: Mapped["Project"] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document")

    __table_args__ = (Index("ix_documents_project_status", "project_id", "status"),)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    section: Mapped[str] = mapped_column(Text, default="")
    page_start: Mapped[int] = mapped_column(Integer, default=0)
    page_end: Mapped[int] = mapped_column(Integer, default=0)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    embedded: Mapped[bool] = mapped_column(Boolean, default=False)

    document: Mapped["Document"] = relationship(back_populates="chunks")


class Run(TimestampMixin, Base):
    """A deep-research pipeline execution, with checkpoints for resume."""
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    query: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="queued")
    # queued | running | completed | completed_with_gaps | failed | budget_exhausted
    current_node: Mapped[str] = mapped_column(String(48), default="")
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    budgets_spent: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    report_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Report(TimestampMixin, Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    outline: Mapped[list] = mapped_column(JSON, default=list)
    sections: Mapped[list] = mapped_column(JSON, default=list)
    # sections: [{heading, claims: [claim_id], gaps: [str], prose_template}]
    confidence: Mapped[dict] = mapped_column(JSON, default=dict)


class Answer(TimestampMixin, Base):
    """A grounded chat response. refused=True is a first-class outcome."""
    __tablename__ = "answers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    question: Mapped[str] = mapped_column(Text)
    refused: Mapped[bool] = mapped_column(Boolean, default=False)
    refusal_reason: Mapped[str] = mapped_column(Text, default="")
    coverage_note: Mapped[str] = mapped_column(Text, default="")
    # Which chat surface produced this: "corpus" (main Ask), "paper" (Ask this
    # paper), or "selection" (chat-with-selection). History restore shows only
    # "corpus" so scoped/one-off chats don't clutter the main conversation.
    kind: Mapped[str] = mapped_column(String(16), default="corpus")


class Claim(TimestampMixin, Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    answer_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    report_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    section_idx: Mapped[int] = mapped_column(Integer, default=0)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # pending | verified | failed | gap


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    chunk_id: Mapped[str] = mapped_column(String(32), index=True)
    quote: Mapped[str] = mapped_column(Text, default="")
    quote_match_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    quote_char_start: Mapped[int] = mapped_column(Integer, default=-1)
    quote_char_end: Mapped[int] = mapped_column(Integer, default=-1)
    nli_label: Mapped[str] = mapped_column(String(16), default="skipped")
    # entailment | neutral | contradiction | skipped
    nli_score: Mapped[float] = mapped_column(Float, default=0.0)


class Citation(Base):
    """A verified reference. Rows exist only after successful resolution -
    the UI renders references exclusively from this table, which is what
    makes fabricated citations structurally impossible."""
    __tablename__ = "citations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    document_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    identifier: Mapped[str] = mapped_column(Text)          # doi / arxiv id / url
    resolver: Mapped[str] = mapped_column(String(24))       # corpus | crossref | openalex | arxiv | github | tavily
    title: Mapped[str] = mapped_column(Text, default="")
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class GraphEdge(Base):
    __tablename__ = "graph_edges"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    src_type: Mapped[str] = mapped_column(String(16))
    src_id: Mapped[str] = mapped_column(String(128))
    dst_type: Mapped[str] = mapped_column(String(16))
    dst_id: Mapped[str] = mapped_column(String(128))
    relation: Mapped[str] = mapped_column(String(32))
    weight: Mapped[float] = mapped_column(Float, default=1.0)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    actor: Mapped[str] = mapped_column(String(64), default="system")
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class SavedClaim(TimestampMixin, Base):
    """Findings notebook: verified claims a user collects across reports into
    a personal, exportable workspace."""
    __tablename__ = "saved_claims"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    claim_id: Mapped[str] = mapped_column(String(32), index=True)
    note: Mapped[str] = mapped_column(Text, default="")


class ShareLink(TimestampMixin, Base):
    """A public, read-only share token for a report. New table -> created by
    init_db()'s create_all with no migration. The slug is the URL-shortening
    layer: a short unguessable capability that maps /s/{slug} -> a report."""
    __tablename__ = "share_links"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    report_id: Mapped[str] = mapped_column(String(32), index=True)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    created_by: Mapped[str] = mapped_column(String(64), default="local")
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Watch(TimestampMixin, Base):
    """A standing query the monitor agent re-checks for new papers."""
    __tablename__ = "watches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    query: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MonitorAlert(TimestampMixin, Base):
    """A newly-discovered paper matching a watch, surfaced for the user."""
    __tablename__ = "monitor_alerts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    watch_id: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(160), index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    pdf_url: Mapped[str] = mapped_column(Text, default="")
    abstract: Mapped[str] = mapped_column(Text, default="")
    authors: Mapped[list] = mapped_column(JSON, default=list)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    arxiv_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(128), nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="new")  # new|dismissed|added


class Note(TimestampMixin, Base):
    """Free-form research notes in the user's own words. Distinct from the
    notebook (verbatim saved quotes): a note can be seeded from a finding but
    its body is the researcher's own synthesis."""
    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    # Optional provenance: the quote/source a note was seeded from.
    source_ref: Mapped[str] = mapped_column(Text, default="")
    claim_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Comparison(TimestampMixin, Base):
    """A persistent cross-paper comparison the researcher assembles by hand.

    The user picks 2-5 documents from the project corpus; for each (document ×
    comparison dimension) cell we draft a grounded claim and run it through the
    SAME verification gate as the pipeline — so every populated cell carries a
    verbatim quote + chunk evidence and is click-to-source. Empty cells are an
    honest 'the source doesn't address this', never a fabrication.

    Stored as durable truth so a comparison survives the session (part of the
    persistent library) and can be exported or included in a report.
    """
    __tablename__ = "comparisons"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    document_ids: Mapped[list] = mapped_column(JSON, default=list)
    dimensions: Mapped[list] = mapped_column(JSON, default=list)
    # matrix: [{ "dimension": str, "cells": { document_id: {claim, quote,
    #            chunk_id, claim_id, page, verified} | null } }]
    matrix: Mapped[list] = mapped_column(JSON, default=list)
    include_in_report: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (Index("ix_comparisons_project_created", "project_id", "created_at"),)


class Memory(TimestampMixin, Base):
    """Cross-session agent memory. Unlike the corpus (raw sources) or claims
    (per-report), a Memory persists across runs so later work can recall what
    this project already established. Kinds:
      episodic  - a summary of a past run (what was researched, key findings)
      semantic  - a durable verified fact worth remembering
      preference - a user/project directive on how to research
    The embedding (when the local model is available) powers semantic recall;
    recall degrades to keyword+recency without it."""
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="episodic")
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_ref: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (Index("ix_memories_project_kind", "project_id", "kind"),)
