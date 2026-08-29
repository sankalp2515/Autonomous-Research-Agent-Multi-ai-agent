"""Pipeline state shared across LangGraph nodes.

Plain JSON-serializable dict (TypedDict) so every node boundary can be
checkpointed verbatim into runs.checkpoint and resumed after a crash.
"""

import time
from typing import Any, TypedDict


class SectionState(TypedDict, total=False):
    heading: str
    sub_question: str
    guidance: str
    status: str               # pending | verified | gap
    track: str                # academic | technical - evidence classes never mix
    claim_ids: list[str]
    gap_note: str
    # WHOSE limitation closed this section. "no_evidence" (the default) is a
    # claim about the CORPUS; "drafting_failed" is a claim about VERISCOPE.
    # Both count as ungrounded — that guard never moves — but a reader must be
    # able to tell an outage from a silent literature, exactly as
    # `extraction_uncertain` distinguishes them at cell level.
    gap_kind: str             # no_evidence | drafting_failed
    regens_used: int
    layout: dict[str, Any]    # optional comparison-table presentation (verified claims only)


class PipelineState(TypedDict, total=False):
    run_id: str
    project_id: str
    query: str

    clarification: dict[str, Any]
    plan: dict[str, Any]
    # P0-A - what evidence THIS question requires: research type, the entities
    # under study, and the REQUIRED/optional comparison dimensions with their
    # retrieval vocabulary (synonyms, metric tokens, section hints). Derived once
    # per run and normalized, so the same question yields the same schema and two
    # runs stay comparable. Empty dict = degraded to the legacy single-query read.
    evidence_schema: dict[str, Any]

    scope: str                     # "all" | "papers" - which evidence classes to search
    since_year: int                # 0 = any time (recency still prioritized); else hard floor
    until_year: int                # 0 = no upper bound; else hard ceiling (year range)
    min_citations: int             # 0 = no floor; else drop below-cited papers
    out_of_scope: bool             # clarify flagged the question outside CS/eng scope
    # Pre-screened, researcher-selected candidates to ingest (human-in-the-loop).
    # When present, research skips its own search and ingests exactly these.
    selected_papers: list[dict[str, Any]]

    paper_doc_ids: list[str]
    repo_doc_ids: list[str]
    blog_doc_ids: list[str]
    coverage_notes: list[str]      # honest record of failed/empty sources
    # Methods funnel: found -> screened -> screened_in -> ingested -> cited.
    # Recorded as the pipeline runs so the report can show HOW the corpus was
    # selected, not just what it concluded (the corpus-level audit trail).
    funnel: dict[str, Any]
    # P1-F - every paper that LEFT the funnel, with the reason it left, recorded
    # at the point of the drop: screened out, below a citation floor, outside the
    # year window, over the ingest cap, no retrievable text, extraction failed.
    # Bounded (_MAX_EXCLUSIONS). The counts are kept separately so the report can
    # show the ladder without re-deriving it from a list that may be truncated.
    exclusions: list[dict[str, Any]]
    exclusion_counts: dict[str, int]
    full_text_count: int          # papers ingested from a real PDF, not an abstract

    # Phase 1 - the evidence matrix: one row per paper (frameworks, baselines,
    # datasets, and quote-verified findings tagged by comparison dimension).
    # This is the corpus as a BODY of evidence, and it is what makes real
    # study x dimension tables and cross-paper synthesis possible.
    evidence_matrix: list[dict[str, Any]]
    # P1 G/H/I - cross-study synthesis derived from evidence_matrix: per-axis
    # study counts, comparable value spans, contradictions (split into
    # explained-by-conditions vs genuine), and evidence-derived strength.
    # Deterministic; recomputed whenever the matrix changes.
    synthesis: dict[str, Any]
    # P2-K/L: the research genre the architect designed for, and a deterministic
    # description of the evidence base (years, systems, benchmarks, full text).
    report_genre: str
    study_characteristics: dict[str, Any]
    # Phase 3 — D (derived) statements: the synthesis rendered as sentences.
    # Produced by template from study counts with NO LLM in the path, each
    # carrying the matrix rows it was computed from. Their gate is recomputation,
    # not entailment, which is why they may say what no single paper says.
    derived_statements: list[dict[str, Any]]
    evidence_drafted_total: int
    evidence_verified_total: int
    # Every statement the gate REFUSED, with the source span it was checked
    # against (bounded by _MAX_REFUSALS). Published as the verification
    # appendix: a refusal that survives only as a count cannot be judged, and
    # judging the gate is how a reader decides whether to trust the report.
    refused_claims: list[dict[str, Any]]
    refusal_reasons: dict[str, int]      # reason -> count, UNbounded tally
    # Screening exclusions attributed to the criterion each paper failed.
    screen_excluded_by_criterion: dict[str, int]
    # Phase 1b — the abstract-tier evidence profile: what each paper's abstract
    # says it evaluates, measures and reports. Recorded at screening keyed by
    # candidate identity (`screen_profiles`), then re-keyed onto the document it
    # became at ingest (`paper_profiles`).
    #
    # A PRIOR, NEVER EVIDENCE. Read only off a title+abstract, so it may be
    # wrong. It steers retrieval vocabulary and audits our own coverage; it is
    # never quoted, cited, persisted as a Claim, or rendered. Every consumer
    # must behave correctly when it is absent or mistaken.
    screen_profiles: dict[str, dict[str, Any]]   # hit key  -> profile
    paper_profiles: dict[str, dict[str, Any]]    # doc_id   -> profile

    outline_title: str
    sections: list[SectionState]

    replan_targets: list[str]      # sub-questions needing a replan
    replans_used: dict[str, int]
    used_claim_texts: list[str]    # verified claims already shipped — cross-section dedup

    llm_calls_used: int
    # Running gate tallies, so a client that connects mid-run (or reconnects)
    # reads the totals rather than only the last section's delta.
    claims_verified_total: int
    claims_refused_total: int
    started_at: float
    node_seconds: dict[str, float]   # per-node wall time, for the metrics dashboard
    report_id: str
    final_status: str
    rejected: str  # set by clarify if the query isn't a research question


def new_state(run_id: str, project_id: str, query: str,
              scope: str = "all", since_year: int = 0, until_year: int = 0,
              min_citations: int = 0,
              selected_papers: list[dict[str, Any]] | None = None) -> PipelineState:
    return PipelineState(
        run_id=run_id, project_id=project_id, query=query, scope=scope,
        since_year=since_year, until_year=until_year, min_citations=min_citations,
        selected_papers=selected_papers or [],
        coverage_notes=[], funnel={}, exclusions=[], exclusion_counts={},
        full_text_count=0, evidence_matrix=[], sections=[], replan_targets=[], replans_used={},
        used_claim_texts=[],
        llm_calls_used=0, started_at=time.time(), node_seconds={},
    )


def budget_reason(state: PipelineState, max_calls: int, max_seconds: int) -> str:
    """Which budget ran out — so a truncated report says so honestly instead of
    reporting a wall-clock cutoff as though the literature had a gap."""
    if state.get("llm_calls_used", 0) >= max_calls:
        return "the run reached its model-call budget"
    if time.time() - state.get("started_at", time.time()) >= max_seconds:
        return "the run reached its time budget (not an evidence gap)"
    return "the run reached its budget"


def budget_left(state: PipelineState, max_calls: int, max_seconds: int) -> bool:
    if state.get("llm_calls_used", 0) >= max_calls:
        return False
    if time.time() - state.get("started_at", time.time()) >= max_seconds:
        return False
    return True
