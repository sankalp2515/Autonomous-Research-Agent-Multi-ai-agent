"""Answers about VERISCOPE'S OWN ARTIFACTS, computed rather than retrieved.

"What is this report about", "what did you find", "how many papers", "what are
the gaps" are not questions about the literature. Nothing in any paper answers
them, so corpus retrieval can only ever refuse - and it did, which is how a user
asking the most natural follow-up in the product got told their corpus was
inadequate.

These are facts about the RUN, and the run already computed every one of them:
`Report.confidence` carries the funnel, the evidence matrix, the synthesis, the
derived statements, the composition and the study characteristics.

WHAT MAKES THIS SAFE. There is no LLM anywhere in this module. Every sentence is
a **D statement** - a template over numbers `synthesize`/`funnel` already
produced, reproducible by recomputation, which is the harder guarantee - or an
**S statement**, which asserts nothing. The three properties `statements.py`
pins hold here too:

  determinism  no model call, no sampling, same inputs -> same sentence;
  provenance   a statement that cannot name its rows is NOT emitted;
  restraint    a sentence may state the counts and nothing beyond them.

So "6 of the 13 studies report latency" ships and "the field lacks a shared
benchmark" does not - the second is an inference about the world, which is an I
sentence, and I is not shipped. A D sentence is never rendered with a footnote:
a citation to one paper would misrepresent a sentence derived from many, so the
provenance affordance is the row-set.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Document, Report
from app.services.ask_intent import (
    TOPIC_CORPUS, TOPIC_FINDINGS, TOPIC_GAPS, TOPIC_METHODS, TOPIC_OVERVIEW,
)

logger = get_logger("ask.workspace")

TYPE_EVIDENTIAL = "E"
TYPE_DERIVED = "D"
TYPE_STRUCTURAL = "S"


@dataclass
class Segment:
    """One sentence of an answer, carrying the type it is and the provenance
    that type earns. G6: the reader can always tell which they are reading."""
    type: str
    text: str
    claim_id: str = ""      # E only
    basis: str = ""         # D only - the counts the sentence was computed from
    doc_ids: list[str] | None = None  # D only - the row-set, never a footnote

    def as_dict(self) -> dict:
        return {"type": self.type, "text": self.text, "claim_id": self.claim_id,
                "basis": self.basis, "doc_ids": list(self.doc_ids or [])}


@dataclass
class WorkspaceAnswer:
    segments: list[Segment]
    coverage_note: str = ""
    suggestions: list[str] | None = None

    @property
    def empty(self) -> bool:
        return not self.segments


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


async def _latest_report(session: AsyncSession, project_id: str) -> Report | None:
    return (await session.scalars(
        select(Report).where(Report.project_id == project_id)
        .order_by(Report.created_at.desc()).limit(1))).first()


async def _doc_counts(session: AsyncSession, project_id: str) -> tuple[int, list[tuple[str, int | None]]]:
    total = await session.scalar(
        select(func.count(Document.id)).where(
            Document.project_id == project_id, Document.status == "indexed")) or 0
    rows = (await session.execute(
        select(Document.title, Document.year).where(
            Document.project_id == project_id, Document.status == "indexed")
        .order_by(Document.year.desc().nullslast()).limit(8))).all()
    return total, [(r[0], r[1]) for r in rows]


# -- topic answers ---------------------------------------------------------
#
# Each returns ordered segments. An empty list means "we hold nothing that
# answers this", which the caller turns into an honest refusal rather than a
# sentence padded out of nothing.

def _overview(report: Report | None, doc_total: int) -> list[Segment]:
    if report is None:
        return []
    conf = report.confidence or {}
    sections = report.sections or []
    out = [Segment(TYPE_STRUCTURAL, f"This report is titled “{report.title}”.")]

    answered = [s for s in sections if s.get("status") != "gap"]
    gaps = [s for s in sections if s.get("status") == "gap"]
    if sections:
        out.append(Segment(
            TYPE_DERIVED,
            f"It is organised into {_plural(len(sections), 'section')}, of which "
            f"{len(answered)} found evidence it could verify and {len(gaps)} closed as a gap.",
            basis=f"{len(answered)} grounded + {len(gaps)} gap of {len(sections)} sections",
        ))
    comp = conf.get("composition") or {}
    verified, derived = comp.get("verified", 0), comp.get("derived", 0)
    if verified or derived:
        out.append(Segment(
            TYPE_DERIVED,
            f"Its sentences are {verified} quote-verified and {derived} derived "
            "from the evidence matrix.",
            basis=f"composition: {verified} E + {derived} D",
        ))
    if doc_total:
        out.append(Segment(
            TYPE_DERIVED,
            f"It was drawn from {_plural(doc_total, 'indexed source')} in this project.",
            basis=f"{doc_total} documents with status=indexed",
        ))
    heads = [s.get("heading", "") for s in sections if s.get("heading")][:8]
    if heads:
        out.append(Segment(TYPE_STRUCTURAL,
                           "The sections are: " + "; ".join(heads) + "."))
    return out


def _findings(report: Report | None) -> list[Segment]:
    """The report's D statements, verbatim.

    These were computed by `derive_statements` at run time and already carry
    their own basis and row-set. Re-serving them here is the same sentence with
    the same provenance - nothing is re-derived, re-worded or re-ranked.
    """
    if report is None:
        return []
    conf = report.confidence or {}
    derived = conf.get("derived_statements") or []
    out: list[Segment] = []
    if derived:
        out.append(Segment(TYPE_STRUCTURAL,
                           "These are the report's derived statements - each one "
                           "recomputed from the evidence matrix, not written by a model."))
        for st in derived[:8]:
            text = (st.get("text") or "").strip()
            if not text:
                continue
            out.append(Segment(TYPE_DERIVED, text,
                               basis=st.get("basis", ""),
                               doc_ids=list(st.get("doc_ids") or [])))
    synth = conf.get("synthesis") or {}
    dims = synth.get("dimensions") or []
    # `state` is a CLASS with a basis, never a score - see synthesis._classify.
    strong = [d for d in dims if d.get("state") == "strongly_supported"]
    contested = [d for d in dims if d.get("state") == "contested"]
    if strong:
        names = "; ".join(str(d.get("dimension", "")) for d in strong[:4])
        out.append(Segment(
            TYPE_DERIVED,
            f"{_plural(len(strong), 'dimension')} of {len(dims)} reached "
            f"strongly_supported: {names}.",
            basis=strong[0].get("basis", "")
            or f"{len(strong)} of {len(dims)} dimensions classed strongly_supported",
        ))
    if contested:
        names = "; ".join(str(d.get("dimension", "")) for d in contested[:4])
        out.append(Segment(
            TYPE_DERIVED,
            f"{_plural(len(contested), 'dimension')} came out contested: {names}.",
            basis=contested[0].get("basis", "")
            or f"{len(contested)} of {len(dims)} dimensions classed contested",
        ))
    if not out:
        return []
    out.append(Segment(TYPE_STRUCTURAL,
                       "A derived statement carries its row-set rather than a "
                       "footnote: it is computed from many studies, so citing one "
                       "would misrepresent it."))
    return out


def _corpus(doc_total: int, titles: list[tuple[str, int | None]],
            report: Report | None) -> list[Segment]:
    if not doc_total:
        return []
    out = [Segment(TYPE_DERIVED,
                   f"This project holds {_plural(doc_total, 'indexed source')}.",
                   basis=f"{doc_total} documents with status=indexed")]
    conf = (report.confidence if report else {}) or {}
    chars = conf.get("study_characteristics") or {}
    span = chars.get("year_span") or {}
    lo, hi = span.get("min"), span.get("max")
    if lo and hi:
        window = str(lo) if lo == hi else f"{lo}-{hi}"
        out.append(Segment(TYPE_DERIVED, f"The extracted studies span {window}.",
                           basis=f"year span {window} over the extracted studies"))
    matrix = conf.get("evidence_matrix") or []
    if matrix:
        out.append(Segment(
            TYPE_DERIVED,
            f"{_plural(len(matrix), 'study')} were read into the evidence matrix.",
            basis=f"{len(matrix)} matrix rows",
            doc_ids=[r.get("doc_id", "") for r in matrix if r.get("doc_id")],
        ))
    if titles:
        listed = "; ".join(t + (f" ({y})" if y else "") for t, y in titles[:6])
        out.append(Segment(TYPE_STRUCTURAL, "Most recent first: " + listed + "."))
    return out


def _gaps(report: Report | None) -> list[Segment]:
    if report is None:
        return []
    conf = report.confidence or {}
    sections = report.sections or []
    gaps = [s for s in sections if s.get("status") == "gap"]
    out: list[Segment] = []
    if sections:
        out.append(Segment(
            TYPE_DERIVED,
            f"{len(gaps)} of {_plural(len(sections), 'section')} closed without "
            "verifiable evidence.",
            basis=f"{len(gaps)} gap sections of {len(sections)}",
        ))
    # Whose limitation it was is the whole point of gap_kind - never blur it.
    ours = [s for s in gaps if s.get("gap_kind") == "drafting_failed"]
    for sec in gaps[:5]:
        note = (sec.get("gap_note") or "").strip()
        head = sec.get("heading", "a section")
        if sec.get("gap_kind") == "drafting_failed":
            out.append(Segment(TYPE_STRUCTURAL,
                               f"“{head}” was not drafted - Veriscope failed "
                               "while writing it. That is a failure on our side, not "
                               "an absence of evidence in the corpus."))
        elif note:
            out.append(Segment(TYPE_STRUCTURAL, f"“{head}”: {note}"))
    if ours:
        out.append(Segment(
            TYPE_DERIVED,
            f"{len(ours)} of those closed because Veriscope failed while writing "
            "the section, not because the studies reported nothing.",
            basis=f"{len(ours)} sections with gap_kind=drafting_failed",
        ))
    # Derived research gaps: every one names its counts, which is the field
    # that makes it a finding instead of "more research is needed".
    research = conf.get("synthesis", {}).get("gaps") or []
    for gap in research[:4]:
        basis = (gap.get("basis") or "").strip()
        dim = (gap.get("dimension") or "").strip()
        if not basis or not dim:
            continue  # no counts to name -> not emitted
        kind = str(gap.get("kind", "")).replace("_", " ")
        out.append(Segment(TYPE_DERIVED, f"{dim} - {kind}: {basis}.", basis=basis))
    return out


_FUNNEL_LABELS = [
    ("discovered", "discovered"), ("screened", "screened"),
    ("eligible", "found eligible"), ("ingested", "ingested"),
    ("full_text_available", "had retrievable full text"),
    ("extracted", "were read into the matrix"),
    ("included_in_synthesis", "reached synthesis"),
    ("cited_in_report", "were cited in the report"),
]


def _methods(report: Report | None) -> list[Segment]:
    if report is None:
        return []
    funnel = (report.confidence or {}).get("funnel") or {}
    ladder = funnel.get("ladder") or {}
    out: list[Segment] = []
    steps = [(label, ladder[key]) for key, label in _FUNNEL_LABELS
             if isinstance(ladder.get(key), int)]
    if steps:
        out.append(Segment(TYPE_STRUCTURAL,
                           "This is the research funnel, stage by stage - a ladder, "
                           "never one percentage."))
        for label, count in steps:
            out.append(Segment(TYPE_DERIVED, f"{count} {label}.",
                               basis=f"funnel.ladder recorded {count} {label}"))
    excluded = funnel.get("excluded_by_reason") or {}
    for reason, count in list(excluded.items())[:6]:
        if isinstance(count, int) and count:
            pretty = str(reason).replace("_", " ")
            out.append(Segment(TYPE_DERIVED, f"{count} left the funnel: {pretty}.",
                               basis=f"excluded_by_reason[{reason}] = {count}"))
    if funnel.get("screen_failed"):
        out.append(Segment(TYPE_STRUCTURAL,
                           "Screening failed for part of this run, so some papers "
                           "were admitted by authority order without an assessment."))
    return out


# -- suggestions -----------------------------------------------------------

def _suggestions(report: Report | None, doc_total: int) -> list[str]:
    """Questions this workspace can actually answer right now.

    Derived from the schema's own dimensions and the matrix's own entities, so
    a suggestion is never a guess about what might be in there.
    """
    out: list[str] = []
    conf = (report.confidence if report else {}) or {}
    dims = [d.get("dimension", "") for d in (conf.get("synthesis", {}).get("dimensions") or [])]
    for name in [d for d in dims if d][:2]:
        out.append(f"What did the studies report on {name}?")
    chars = conf.get("study_characteristics") or {}
    named = [(f.get("name") or "").strip()
             for f in (chars.get("frameworks") or []) + (chars.get("models") or [])]
    systems = [n for n in named if n][:2]
    if len(systems) >= 2:
        out.append(f"How do {systems[0]} and {systems[1]} compare?")
    elif systems:
        out.append(f"What evidence is there for {systems[0]}?")
    if report is not None:
        out.append("What are the open gaps in this report?")
    if doc_total:
        out.append("Which papers are in this corpus?")
    seen: set[str] = set()
    uniq = [q for q in out if not (q.lower() in seen or seen.add(q.lower()))]
    return uniq[:4]


async def answer(session: AsyncSession, project_id: str, topic: str) -> WorkspaceAnswer:
    """A deterministic answer about this project, or an empty one."""
    report = await _latest_report(session, project_id)
    doc_total, titles = await _doc_counts(session, project_id)

    if topic == TOPIC_OVERVIEW:
        segments = _overview(report, doc_total)
    elif topic == TOPIC_FINDINGS:
        segments = _findings(report)
    elif topic == TOPIC_CORPUS:
        segments = _corpus(doc_total, titles, report)
    elif topic == TOPIC_GAPS:
        segments = _gaps(report)
    elif topic == TOPIC_METHODS:
        segments = _methods(report)
    else:
        segments = []

    note = ""
    if segments:
        note = ("Answered from this project's own run records - counts and "
                "structure, not a claim about the literature.")
    logger.info("workspace answer", extra={"topic": topic, "segments": len(segments)})
    return WorkspaceAnswer(segments, note, _suggestions(report, doc_total))


async def suggestions(session: AsyncSession, project_id: str) -> list[str]:
    """Answerable reformulations, for the refusal path."""
    report = await _latest_report(session, project_id)
    doc_total, _ = await _doc_counts(session, project_id)
    return _suggestions(report, doc_total)


async def covered_topics(session: AsyncSession, project_id: str) -> list[str]:
    """What this corpus is demonstrably about - dimension names first (they were
    audited), paper titles as the fallback."""
    report = await _latest_report(session, project_id)
    conf = (report.confidence if report else {}) or {}
    dims = [d.get("dimension", "") for d in (conf.get("synthesis", {}).get("dimensions") or [])]
    dims = [d for d in dims if d]
    if dims:
        return dims[:6]
    _, titles = await _doc_counts(session, project_id)
    return [t for t, _y in titles][:5]
