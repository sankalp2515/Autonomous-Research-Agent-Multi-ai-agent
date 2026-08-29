"""Deterministic guard on LLM-parsed research constraints.

THE BUG THIS EXISTS FOR. Both clarify paths ask a model to pull constraints out
of the user's own words — "after 2022" -> since_year, "at least 50 citations" ->
min_citations — with the schema telling it to return 0 when nothing was stated.
Models over-trigger on that instruction. Measured live: the query

    "Compare dense retrievers (DPR, ColBERT, SPLADE, BM25) on BEIR and MS MARCO:
     retrieval accuracy (nDCG@10, MRR@10), query latency, and index size"

came back with since_year=2023 AND min_citations=50, and the UI presented both
as "parsed from your question · enforced". Neither appears anywhere in that
sentence. The consequences are not cosmetic: a 50-citation floor silently
excludes essentially every recent arXiv preprint, which for a retrieval question
IS the literature — the same class of corpus poisoning as the screening bug that
`tests/test_screening_pools.py` pins, arriving through a different door. And the
user is told THEY asked for it.

THE RULE. A constraint may only survive if the user's text contains a token that
could have produced it. This is deliberately asymmetric: it can drop a
constraint the model invented, and it can never add one. Ambiguity resolves
toward "the user did not ask for this", because an unrequested filter that
quietly shrinks the corpus is far more damaging than a missed one the user can
restate.

Pure functions, no model call, no I/O.
"""

import re

# Words that could plausibly produce a citation floor.
_CITATION_CUE = re.compile(
    r"\bcitation|\bcited\b|\bcites\b|\bhighly[- ]cited\b|\bimpact\b|\bh-?index\b",
    re.IGNORECASE,
)

# Anything that could produce a year bound: an explicit 4-digit year, a decade,
# or a relative window ("last two years", "since", "recent", "past 5 years").
_YEAR_CUE = re.compile(
    r"\b(?:19|20)\d{2}\b"
    r"|\blast\s+(?:\d+|one|two|three|four|five|ten)\s+(?:year|month)s?\b"
    r"|\bpast\s+(?:\d+|one|two|three|four|five|ten)\s+(?:year|month)s?\b"
    r"|\bsince\b|\bafter\b|\bbefore\b|\bprior to\b|\bup to\b"
    r"|\brecent(?:ly)?\b|\bcurrent\b|\blatest\b|\bnewer?\b|\bmodern\b"
    r"|\bstate[- ]of[- ]the[- ]art\b|\bsota\b",
    re.IGNORECASE,
)


def scrub_constraints(query: str, *, since_year: int = 0, until_year: int = 0,
                      min_citations: int = 0) -> tuple[int, int, int, list[str]]:
    """Drop constraints the query cannot have asked for.

    Returns (since_year, until_year, min_citations, dropped_notes). The notes are
    reader-facing: if we discard something the model claimed, the run says so
    rather than silently disagreeing with the chip the user was shown.
    """
    text = query or ""
    dropped: list[str] = []

    if min_citations and not _CITATION_CUE.search(text):
        dropped.append(
            f"ignored a minimum-citation filter (≥{min_citations}) that was not "
            "in your question — a citation floor would have excluded recent "
            "preprints, which is usually where this literature lives")
        min_citations = 0

    if (since_year or until_year) and not _YEAR_CUE.search(text):
        bound = "–".join(str(y) for y in (since_year, until_year) if y)
        dropped.append(
            f"ignored a publication-year window ({bound}) that was not in your "
            "question")
        since_year = until_year = 0

    # A window that cannot contain anything is a parse error, not a constraint.
    if since_year and until_year and since_year > until_year:
        dropped.append(
            f"ignored an impossible year window ({since_year}–{until_year})")
        since_year = until_year = 0

    return since_year, until_year, min_citations, dropped


# ── Clarification policy ─────────────────────────────────────────────────
#
# Clarification used to be a mandatory gateway: the schema could not express
# "no questions", so every run stopped to interrogate the user — including
# queries that already named their systems, their metrics and their time
# window. The fix has two halves, and this is the cheap deterministic one.
#
# A query that already carries the marks of a well-formed research question
# does not need a model's opinion about whether it is clear. Checking that in
# code is free, cannot drift, and means the common case (a researcher who
# wrote a precise question) never pays a round trip OR a pause.

# Signals that a request is already scoped. Deliberately shallow and additive:
# this decides whether to SKIP asking, never whether to reject anything.
_COMPARATIVE = re.compile(
    r"\b(vs\.?|versus|compared? (?:to|with|against)|between|trade[- ]?offs?|"
    r"differ(?:ence|s)?|outperform|baseline)\b", re.I)
_MEASURED = re.compile(
    r"\b(accuracy|f1|recall|precision|latency|throughput|cost|tokens?|speed|"
    r"memory|error rate|benchmark|score|performance|efficiency)\b", re.I)
_SCOPED = re.compile(
    r"\b(since|after|before|between)\s+(19|20)\d{2}\b|\b(19|20)\d{2}\s*[-–]\s*(19|20)\d{2}\b"
    r"|\b(latest|recent|current|state[- ]of[- ]the[- ]art)\b", re.I)
# A capitalised or acronym-shaped token is usually a named system/dataset.
_NAMED = re.compile(r"\b(?:[A-Z][a-z0-9]+[A-Z][A-Za-z0-9-]*|[A-Z]{2,}[A-Za-z0-9-]*)\b")

# Below this a query is a topic, not a question ("RAG", "graph databases").
_MIN_SPECIFIC_WORDS = 12


def query_specificity(query: str) -> tuple[str, list[str]]:
    """Classify a request as 'specific' | 'underspecified', with the signals.

    Returns 'specific' when the text already pins down enough that asking would
    be busywork. Never returns 'ambiguous': genuine ambiguity is a semantic
    judgement this cannot make, and is left to the model.
    """
    text = (query or "").strip()
    words = text.split()
    signals: list[str] = []
    if _COMPARATIVE.search(text):
        signals.append("names a comparison")
    if _MEASURED.search(text):
        signals.append("names what to measure")
    if _SCOPED.search(text):
        signals.append("states a time scope")
    if len(_NAMED.findall(text)) >= 2:
        signals.append("names specific systems")
    if len(words) >= _MIN_SPECIFIC_WORDS and text.endswith("?"):
        signals.append("is a fully-formed question")

    # Two independent signals on a query of reasonable length is enough. One
    # signal on a very long, well-formed question is too.
    if len(signals) >= 2 and len(words) >= _MIN_SPECIFIC_WORDS:
        return "specific", signals
    if len(words) >= 30 and signals:
        return "specific", signals
    return "underspecified", signals
