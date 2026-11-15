"""Ask is a grounded follow-up CONVERSATION, and these are the traps.

Four properties are pinned here, each one a bug that shipped:

1. **Addressing.** The drafting prompt names each passage by `_source_id` (a
   content hash), so the gate must be keyed the same way and the id translated
   back to a real row before anything is persisted. Keying the lookup by
   `chunk_id` failed every claim at gate layer 1 as `missing_chunk` — the corpus
   path could not return an answer at all.

2. **Routing.** "What is this report about" is a question about VERISCOPE.
   Sending it to corpus retrieval is a category error whose only possible
   outcome is a refusal. And the router must stay conservative: a literature
   question routed to the workspace answerer would swap a grounded answer for a
   fact about our bookkeeping.

3. **Refusal typing.** Only `empty_corpus` is a statement about the corpus.
   Saying "your corpus does not cover this" when we mean "we could not establish
   this" is the cell-state error (`not_reported` vs `extraction_uncertain`) one
   level up.

4. **Restraint in D.** The workspace answerer has no LLM in its assertion path.
   Its sentences may state the counts and nothing beyond them, and a statement
   that cannot name its basis is not emitted.
"""

from dataclasses import dataclass

import pytest

from app.agents import nodes
from app.agents.schemas import ChatAnswer, DraftClaim
from app.services import ask_intent, ask_workspace, grounded
from app.verification.gate import GateReport, GateResult
from app.verification.gate import EvidenceResult
from app.verification.quote_match import QuoteMatch


# ── fixtures ─────────────────────────────────────────────────────────────

CHUNK_TEXT = ("GraphRAG reaches 89.2 F1 on HotpotQA against 63.4 for the vector "
              "baseline, while median query latency rises from 310ms to 1.2s.")
QUOTE = "89.2 F1 on HotpotQA"
SOURCE_ID = nodes._source_id(CHUNK_TEXT)


@dataclass
class _Chunk:
    chunk_id: str = "real-row-id-42"
    document_id: str = "doc1"
    document_title: str = "GraphRAG at scale"
    section: str = "Results"
    page_start: int = 4
    page_end: int = 5
    text: str = CHUNK_TEXT
    score: float = 0.9
    abstract_only: bool = False
    source_type: str = "paper"


class _FakeSession:
    """Captures persisted rows; assigns ids the way a real flush would."""

    def __init__(self):
        self.added = []
        self._n = 0

    def add(self, row):
        self._n += 1
        if getattr(row, "id", None) is None:
            row.id = f"row{self._n}"
        self.added.append(row)

    async def flush(self):
        return None

    async def get(self, _model, _pk):
        return None


def _verified_report(chunk_id: str) -> GateReport:
    ev = EvidenceResult(chunk_id, QUOTE, QuoteMatch(True, "exact", 1.0, 0, len(QUOTE)),
                        "entailment", 0.94)
    report = GateReport()
    report.results = [GateResult(True, "ok", ev)]
    return report


@pytest.fixture
def corpus_turn(monkeypatch):
    """A healthy corpus turn: one chunk, one drafted claim, gate passes."""
    session = _FakeSession()

    async def fake_retrieve(*_a, **_kw):
        return [_Chunk()]

    async def fake_transform(*_a, **_kw):
        from app.retrieval.query_transform import TransformedQuery
        return TransformedQuery(original="q", rewritten="q rewritten")

    async def fake_intent(_q):
        return True, ""

    # The model cites the id it was SHOWN — the content hash, not the row id.
    async def fake_draft(_q, _chunks):
        return ChatAnswer(claims=[DraftClaim(
            text="GraphRAG reaches 89.2 F1 on HotpotQA.",
            chunk_id=SOURCE_ID, quote=QUOTE)])

    captured: dict = {}

    async def fake_verify(claims, chunk_lookup):
        captured["lookup_keys"] = set(chunk_lookup)
        captured["cited"] = [c.chunk_id for c in claims]
        # Behave like the real gate: a citation the lookup does not know fails.
        if claims[0].chunk_id not in chunk_lookup:
            report = GateReport()
            report.results = [GateResult(False, "missing_chunk")]
            return report
        return _verified_report(claims[0].chunk_id)

    monkeypatch.setattr(grounded, "retrieve", fake_retrieve)
    monkeypatch.setattr(grounded, "_intent_ok", fake_intent)
    monkeypatch.setattr(grounded, "_draft", fake_draft)
    monkeypatch.setattr(grounded, "verify_claims", fake_verify)
    monkeypatch.setattr("app.retrieval.query_transform.transform_query", fake_transform)

    async def no_suggestions(*_a, **_kw):
        return []
    monkeypatch.setattr(ask_workspace, "suggestions", no_suggestions)
    return session, captured


# ── 1. addressing: the bug that refused every answer ─────────────────────

@pytest.mark.asyncio
async def test_gate_lookup_is_keyed_the_way_the_prompt_names_passages(corpus_turn):
    """THE REGRESSION. `_format_sources` prints `_source_id(text)`; the lookup
    must be keyed by the same thing or every claim dies as `missing_chunk`."""
    session, captured = corpus_turn
    result = await grounded.grounded_chat(session, "p1", "How does GraphRAG do on HotpotQA?")

    assert captured["cited"] == [SOURCE_ID]
    assert SOURCE_ID in captured["lookup_keys"], (
        "the gate was keyed by row id while the prompt names passages by content "
        "hash — every claim fails layer 1 and the answer path cannot return")
    assert not result.refused
    assert len(result.claims) == 1


@pytest.mark.asyncio
async def test_persisted_evidence_points_at_a_real_row_not_the_content_hash(corpus_turn):
    """The content hash is an ADDRESSING scheme for the prompt. What is stored
    must be a row this project owns, or the evidence rail resolves nothing."""
    session, _ = corpus_turn
    result = await grounded.grounded_chat(session, "p1", "How does GraphRAG do on HotpotQA?")

    assert result.claims[0].evidence.chunk_id == "real-row-id-42"
    evidence_rows = [r for r in session.added if type(r).__name__ == "ClaimEvidence"]
    assert evidence_rows and evidence_rows[0].chunk_id == "real-row-id-42"


@pytest.mark.asyncio
async def test_every_evidential_segment_carries_a_claim_id(corpus_turn):
    session, _ = corpus_turn
    result = await grounded.grounded_chat(session, "p1", "How does GraphRAG do on HotpotQA?")
    e_segments = [s for s in result.segments if s["type"] == "E"]
    assert e_segments
    assert all(s["claim_id"] for s in e_segments)


@pytest.mark.asyncio
async def test_a_derived_segment_is_never_given_a_footnote(corpus_turn):
    """A citation to one paper misrepresents a sentence derived from many. The
    provenance affordance for D is the row-set, never a claim id."""
    session, _ = corpus_turn
    result = await grounded.grounded_chat(session, "p1", "How does GraphRAG do on HotpotQA?")
    for seg in result.segments:
        if seg["type"] == "D":
            assert not seg["claim_id"]
            assert seg["basis"], "a D sentence that cannot name its basis is not emitted"


# ── 2. routing ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("question, topic", [
    ("what is the report about?", ask_intent.TOPIC_OVERVIEW),
    ("What's this report about", ask_intent.TOPIC_OVERVIEW),
    ("what did you find?", ask_intent.TOPIC_FINDINGS),
    ("how many papers are in my corpus?", ask_intent.TOPIC_CORPUS),
    ("which papers did you use", ask_intent.TOPIC_CORPUS),
    ("what are the gaps?", ask_intent.TOPIC_GAPS),
    ("how many papers did you screen", ask_intent.TOPIC_METHODS),
])
def test_questions_about_our_own_artifacts_route_to_the_workspace(question, topic):
    route, got = ask_intent.route(question)
    assert route == ask_intent.ROUTE_WORKSPACE
    assert got == topic


@pytest.mark.parametrize("question", [
    "How does zero-shot prompting work in GPT-4?",
    "What accuracy did GraphRAG report on HotpotQA?",
    "Which studies report latency, and what did they measure?",
    "Do the papers agree on the effect of abliteration?",
    "What did Wang et al. conclude about hallucination rates?",
])
def test_literature_questions_stay_on_the_corpus(question):
    """Ambiguity resolves to the corpus. Mis-routing here would replace a
    grounded answer with a fact about our bookkeeping."""
    route, _ = ask_intent.route(question)
    assert route == ask_intent.ROUTE_CORPUS


# ── 3. follow-up resolution ──────────────────────────────────────────────

@pytest.mark.parametrize("question", ["why?", "what about latency?", "and cost?",
                                      "compare those two", "tell me more",
                                      "does it beat the baseline?"])
def test_anaphoric_turns_need_resolution(question):
    assert ask_intent.needs_resolution(question, has_history=True)


def test_a_standalone_question_is_left_alone():
    """Rewriting a good question is a way to make it worse — and it costs a call."""
    q = "Which studies evaluated retrieval latency on multi-hop question answering?"
    assert not ask_intent.needs_resolution(q, has_history=True)


def test_the_first_turn_is_never_rewritten():
    assert not ask_intent.needs_resolution("why?", has_history=False)


@pytest.mark.asyncio
async def test_resolution_failure_falls_back_to_the_raw_turn(monkeypatch):
    """Fail-open: the rewrite steers retrieval, so losing it costs recall and
    must never cost the turn."""
    async def boom(*_a, **_kw):
        raise RuntimeError("provider down")
    monkeypatch.setattr("app.llm.router.complete_json", boom)
    out = await ask_intent.resolve_followup("why?", [{"question": "q", "answer": "a"}])
    assert out == "why?"


# ── 4. refusal typing ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_passages_at_all_is_the_only_claim_about_the_corpus(monkeypatch):
    session = _FakeSession()

    async def empty(*_a, **_kw):
        return []

    async def fake_intent(_q):
        return True, ""

    async def fake_transform(*_a, **_kw):
        from app.retrieval.query_transform import TransformedQuery
        return TransformedQuery(original="q")

    async def no_suggestions(*_a, **_kw):
        return []

    monkeypatch.setattr(grounded, "retrieve", empty)
    monkeypatch.setattr(grounded, "_intent_ok", fake_intent)
    monkeypatch.setattr(ask_workspace, "suggestions", no_suggestions)
    monkeypatch.setattr("app.retrieval.query_transform.transform_query", fake_transform)

    result = await grounded.grounded_chat(session, "p1", "What about quantum annealing?")
    assert result.refused
    assert result.refusal_kind == grounded.REFUSAL_EMPTY_CORPUS


@pytest.mark.asyncio
async def test_read_but_unsupported_blames_the_search_not_the_corpus(monkeypatch):
    """THE HONESTY RULE. We retrieved passages and could not establish an
    answer. That is a fact about this search, and the old text —
    "N chunks retrieved but none support an answer" — asserted it about the
    corpus instead."""
    session = _FakeSession()

    async def one_chunk(*_a, **_kw):
        return [_Chunk()]

    async def fake_intent(_q):
        return True, ""

    async def fake_transform(*_a, **_kw):
        from app.retrieval.query_transform import TransformedQuery
        return TransformedQuery(original="q")   # no rewrite -> no recovery pass

    async def always_refuses(_q, _chunks):
        return ChatAnswer(refuse=True, refusal_reason="The sources do not cover this.")

    async def no_suggestions(*_a, **_kw):
        return []

    monkeypatch.setattr(grounded, "retrieve", one_chunk)
    monkeypatch.setattr(grounded, "_intent_ok", fake_intent)
    monkeypatch.setattr(grounded, "_draft", always_refuses)
    monkeypatch.setattr(ask_workspace, "suggestions", no_suggestions)
    monkeypatch.setattr("app.retrieval.query_transform.transform_query", fake_transform)

    result = await grounded.grounded_chat(session, "p1", "How does zero-shot prompting work?")
    assert result.refused
    assert result.refusal_kind == grounded.REFUSAL_NO_SUPPORT
    blob = (result.refusal_reason + " " + result.coverage_note).lower()
    assert "limit of this search" in blob
    for forbidden in ("your corpus has no", "the corpus does not cover",
                      "corpus lacks"):
        assert forbidden not in blob
    # A refusal shows its work: the passages we read are on the page.
    assert result.looked_at and result.looked_at[0].document_title


@pytest.mark.asyncio
async def test_a_refusal_after_reading_recovers_once_before_giving_up(monkeypatch):
    """Recovery, not a second opinion — the same shape as the matrix's
    `_recover_unresolved`, and it costs a call only on the path that was about
    to return nothing."""
    session = _FakeSession()
    calls = {"retrieve": 0, "draft": 0}

    async def retrieving(*_a, **kw):
        calls["retrieve"] += 1
        if calls["retrieve"] == 1:
            return [_Chunk()]
        return [_Chunk(), _Chunk(chunk_id="row2", text=CHUNK_TEXT + " Extra.")]

    async def fake_intent(_q):
        return True, ""

    async def fake_transform(*_a, **_kw):
        from app.retrieval.query_transform import TransformedQuery
        return TransformedQuery(original="q", hypothetical="GraphRAG reaches 89.2 F1.")

    async def drafting(_q, _chunks):
        calls["draft"] += 1
        return ChatAnswer(refuse=True, refusal_reason="not covered")

    async def no_suggestions(*_a, **_kw):
        return []

    monkeypatch.setattr(grounded, "retrieve", retrieving)
    monkeypatch.setattr(grounded, "_intent_ok", fake_intent)
    monkeypatch.setattr(grounded, "_draft", drafting)
    monkeypatch.setattr(ask_workspace, "suggestions", no_suggestions)
    monkeypatch.setattr("app.retrieval.query_transform.transform_query", fake_transform)

    result = await grounded.grounded_chat(session, "p1", "What is the F1 on HotpotQA?")
    assert calls["draft"] == 2, "a refusal with retrieval signal is re-read once"
    assert result.refusal_kind == grounded.REFUSAL_NO_SUPPORT


# ── 4b. the refusal trigger is the instrument ────────────────────────────
#
# An earlier revision told the drafter "partial is better than nothing": answer
# what you can, name what is missing, do not refuse. It was safe at the gate —
# a partial answer's claims face quote-match and NLI like any other — and it was
# removed anyway, because it moves the REFUSAL TRIGGER.
#
# A system that always finds something to say teaches the reader nothing about
# when to believe it. These pin that the trigger stays where it was.

@pytest.mark.asyncio
async def test_a_refusing_draft_refuses_even_when_it_attached_claims(monkeypatch):
    """`refuse=true` is the model's verdict and it is final. Salvaging the
    claims it attached anyway would answer a question the drafter just said its
    sources could not answer."""
    session = _FakeSession()

    async def one_chunk(*_a, **_kw):
        return [_Chunk()]

    async def fake_intent(_q):
        return True, ""

    async def fake_transform(*_a, **_kw):
        from app.retrieval.query_transform import TransformedQuery
        return TransformedQuery(original="q")   # no rewrite -> no recovery pass

    async def refuses_with_claims(_q, _chunks):
        return ChatAnswer(
            claims=[DraftClaim(text="GraphRAG reaches 89.2 F1 on HotpotQA.",
                               chunk_id=SOURCE_ID, quote=QUOTE)],
            refuse=True, refusal_reason="The sources only cover accuracy.")

    async def no_suggestions(*_a, **_kw):
        return []

    monkeypatch.setattr(grounded, "retrieve", one_chunk)
    monkeypatch.setattr(grounded, "_intent_ok", fake_intent)
    monkeypatch.setattr(grounded, "_draft", refuses_with_claims)
    monkeypatch.setattr(ask_workspace, "suggestions", no_suggestions)
    monkeypatch.setattr("app.retrieval.query_transform.transform_query", fake_transform)

    result = await grounded.grounded_chat(session, "p1", "What was the latency?")
    assert result.refused
    assert result.claims == []
    # Nothing was persisted as a verified claim on a refused turn.
    assert not [r for r in session.added if type(r).__name__ == "Claim"]


@pytest.mark.asyncio
async def test_an_answer_never_carries_a_not_covered_caveat(corpus_turn):
    """The caveat existed only to render what the partial rule invited. An
    answer states what the sources support; what they do not support is a
    refusal, not a footer."""
    session, _ = corpus_turn
    result = await grounded.grounded_chat(session, "p1", "How does GraphRAG do on HotpotQA?")
    blob = " ".join(seg["text"] for seg in result.segments).lower()
    assert "not covered by these sources" not in blob


def test_the_drafting_prompt_does_not_invite_a_partial_answer():
    """The prompt is the trigger. Rules 5-8 shape PRESENTATION and stay; a rule
    that tells the drafter to answer rather than refuse does not."""
    prompt = grounded._CHAT_SYSTEM.lower()
    assert "refusing is a correct answer" in prompt
    for phrase in ("partial is better", "without setting refuse",
                   "return the claims you can support"):
        assert phrase not in prompt, f"the refusal trigger was loosened: {phrase!r}"


# ── 5. the workspace answerer: deterministic, provenanced, restrained ────

class _Report:
    def __init__(self):
        self.title = "Retrieval architectures for multi-hop QA"
        self.sections = [
            {"heading": "Accuracy", "status": "ok"},
            {"heading": "Latency", "status": "gap", "gap_kind": "no_evidence",
             "gap_note": "No study in this corpus reported latency."},
            {"heading": "Cost", "status": "gap", "gap_kind": "drafting_failed"},
        ]
        self.confidence = {
            "composition": {"verified": 38, "derived": 6},
            "synthesis": {
                "dimensions": [
                    {"dimension": "accuracy", "state": "strongly_supported",
                     "basis": "9 studies report accuracy, 4 comparably"},
                    {"dimension": "latency", "state": "contested",
                     "basis": "3 studies report latency and 1 pair disagrees"},
                ],
                "gaps": [{"kind": "single_study", "dimension": "cost",
                          "basis": "exactly one of 12 studies reports cost"}],
            },
            "derived_statements": [
                {"text": "9 of the 12 studies report accuracy.",
                 "basis": "9 of 12", "doc_ids": ["d1", "d2"]},
            ],
            "evidence_matrix": [{"doc_id": "d1"}, {"doc_id": "d2"}],
            "study_characteristics": {"year_span": {"min": 2021, "max": 2025},
                                      "frameworks": [{"name": "GraphRAG", "studies": 5},
                                                     {"name": "Vector RAG", "studies": 4}]},
            "funnel": {"ladder": {"discovered": 307, "screened": 307, "ingested": 28,
                                  "extracted": 22, "cited_in_report": 14},
                       "excluded_by_reason": {"screened_out": 240, "no_full_text": 6}},
        }


class _ReportSession(_FakeSession):
    def __init__(self, report=None, docs=3):
        super().__init__()
        self._report = report
        self._docs = docs

    async def scalars(self, _stmt):
        report = self._report

        class _R:
            def first(self_inner):
                return report
        return _R()

    async def scalar(self, _stmt):
        return self._docs

    async def execute(self, _stmt):
        rows = [("A paper", 2025), ("Another paper", 2023)]

        class _E:
            def all(self_inner):
                return rows
        return _E()


FORBIDDEN = ("the field", "the literature", "suggests that", "more research is needed",
             "better", "worse", "promising", "state of the art")


@pytest.mark.asyncio
@pytest.mark.parametrize("topic", [ask_intent.TOPIC_OVERVIEW, ask_intent.TOPIC_FINDINGS,
                                   ask_intent.TOPIC_CORPUS, ask_intent.TOPIC_GAPS,
                                   ask_intent.TOPIC_METHODS])
async def test_workspace_answers_are_deterministic(topic):
    """No model, no sampling: recomputing reproduces the sentence exactly. That
    is the gate a D statement passes instead of quote+NLI."""
    a = await ask_workspace.answer(_ReportSession(_Report()), "p1", topic)
    b = await ask_workspace.answer(_ReportSession(_Report()), "p1", topic)
    assert [s.as_dict() for s in a.segments] == [s.as_dict() for s in b.segments]
    assert a.segments


@pytest.mark.asyncio
@pytest.mark.parametrize("topic", [ask_intent.TOPIC_OVERVIEW, ask_intent.TOPIC_FINDINGS,
                                   ask_intent.TOPIC_CORPUS, ask_intent.TOPIC_GAPS,
                                   ask_intent.TOPIC_METHODS])
async def test_no_workspace_sentence_infers_about_the_world(topic):
    """Restraint: a D sentence may state the counts and nothing beyond them.
    Anything with a judgement in it is an I sentence, and I is not shipped."""
    result = await ask_workspace.answer(_ReportSession(_Report()), "p1", topic)
    for seg in result.segments:
        low = seg.text.lower()
        for phrase in FORBIDDEN:
            assert phrase not in low, f"{topic}: {seg.text!r} contains {phrase!r}"


@pytest.mark.asyncio
@pytest.mark.parametrize("topic", [ask_intent.TOPIC_OVERVIEW, ask_intent.TOPIC_FINDINGS,
                                   ask_intent.TOPIC_CORPUS, ask_intent.TOPIC_GAPS,
                                   ask_intent.TOPIC_METHODS])
async def test_every_derived_sentence_names_its_counts(topic):
    """Provenance: a statement that cannot name its basis is NOT emitted, and a
    basis without a digit is not a count."""
    result = await ask_workspace.answer(_ReportSession(_Report()), "p1", topic)
    for seg in result.segments:
        if seg.type == ask_workspace.TYPE_DERIVED:
            assert seg.basis, f"{topic}: derived sentence with no basis: {seg.text!r}"
            assert any(ch.isdigit() for ch in seg.basis), (
                f"{topic}: basis names no count: {seg.basis!r}")


@pytest.mark.asyncio
async def test_a_failed_section_is_never_reported_as_an_evidence_gap():
    """Both close a section; only one is a fact about the corpus."""
    result = await ask_workspace.answer(_ReportSession(_Report()), "p1",
                                        ask_intent.TOPIC_GAPS)
    text = " ".join(s.text for s in result.segments)
    assert "failure on our side" in text


@pytest.mark.asyncio
async def test_no_report_yields_no_sentences_rather_than_padding():
    """An empty answer is what the caller turns into an honest refusal. Padding
    a sentence out of nothing is the failure mode this guards."""
    result = await ask_workspace.answer(_ReportSession(None, docs=0), "p1",
                                        ask_intent.TOPIC_OVERVIEW)
    assert result.empty


@pytest.mark.asyncio
async def test_a_workspace_question_with_no_records_refuses_about_us(monkeypatch):
    """It must NOT fall through to corpus retrieval, where the only possible
    outcome is a refusal blaming the literature for our missing run."""
    session = _ReportSession(None, docs=0)

    async def never(*_a, **_kw):
        raise AssertionError("retrieval must not run for a workspace question")

    monkeypatch.setattr(grounded, "retrieve", never)
    result = await grounded.grounded_chat(session, "p1", "What is this report about?")
    assert result.refused
    assert result.refusal_kind == grounded.REFUSAL_NO_RECORDS


@pytest.mark.asyncio
async def test_a_workspace_answer_is_derived_and_carries_no_claims():
    session = _ReportSession(_Report())
    result = await grounded.grounded_chat(session, "p1", "What is this report about?")
    assert not result.refused
    assert result.answer_kind == grounded.KIND_DERIVED
    assert result.claims == []
    assert all(s["type"] in ("D", "S") for s in result.segments)
