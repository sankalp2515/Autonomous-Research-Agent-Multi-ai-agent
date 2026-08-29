"""The outline comes from the question's axes, not from a genre template.

The architect asked a model to invent 4-7 headings from a genre spine. Nearly
every CS question resolves to `comparison` or `survey`, so it produced the same
five sections every time — and, because the headings were chosen independently
of what was extracted, it could create a section the corpus could not fill while
omitting an axis every study reported.

The evidence schema already derives the axes the answer needs FROM THE QUESTION,
and extraction fills a matrix column per axis. Using those as the outline makes
the report's shape a property of the question, guarantees each section has
evidence behind it, and costs one fewer LLM call.
"""

from app.agents.nodes import _axis_sections, _heading_for


def _schema(required, optional=()):
    def dim(name, desc="", syn=(), met=()):
        return {"name": name, "kind": "quantitative", "description": desc,
                "synonyms": list(syn), "metrics": list(met),
                "location_hints": [], "not_applicable_when": ""}
    return {"evidence_schema": {
        "required_dimensions": [dim(*d) if isinstance(d, tuple) else dim(d)
                                for d in required],
        "optional_dimensions": [dim(d) for d in optional],
    }}


def _matrix(axis_counts):
    rows, i = [], 0
    for axis, n in axis_counts.items():
        for _ in range(n):
            i += 1
            rows.append({"doc_id": f"d{i}", "findings": [{"dimension": axis}]})
    return rows


def test_one_section_per_axis():
    secs = _axis_sections(_schema(["retrieval accuracy", "latency"]), [])
    assert [s["axis"] for s in secs] == ["latency", "retrieval accuracy"]  # alpha at 0 evidence
    assert all(s["section_type"] == "evidence_axis" for s in secs)


def test_required_axes_precede_optional_ones_even_with_less_evidence():
    """The question's own priorities outrank corpus abundance: an optional axis
    every study happened to report must not displace a required one."""
    state = _schema(["cost"], optional=["popularity"])
    secs = _axis_sections(state, _matrix({"popularity": 9, "cost": 1}))
    assert [s["axis"] for s in secs] == ["cost", "popularity"]


def test_within_a_group_the_best_evidenced_axis_comes_first():
    state = _schema(["accuracy", "latency", "cost"])
    secs = _axis_sections(state, _matrix({"latency": 5, "cost": 2, "accuracy": 1}))
    assert [s["axis"] for s in secs] == ["latency", "cost", "accuracy"]


def test_the_retrieval_brief_carries_the_axis_vocabulary():
    """Drafting must search the corpus with the same words extraction used to
    build the matrix, or a section can miss the evidence in its own column."""
    state = _schema([("latency", "How fast?", ["response time", "ms"], ["ms"])])
    brief = _axis_sections(state, [])[0]["sub_question"]
    assert "latency" in brief and "response time" in brief and "ms" in brief


def test_the_schema_description_becomes_the_reader_facing_question():
    state = _schema([("latency", "What did each system cost in time?")])
    assert _axis_sections(state, [])[0]["framing"] == "What did each system cost in time?"


def test_a_run_without_a_schema_falls_back_rather_than_losing_its_outline():
    assert _axis_sections({}, []) == []
    assert _axis_sections({"evidence_schema": {}}, []) == []


def test_headings_are_cased_for_display_but_the_axis_label_is_untouched():
    """The label is the matrix column key — mutating it would desynchronise the
    section from the evidence it is meant to present."""
    secs = _axis_sections(_schema(["retrieval accuracy"]), [])
    assert secs[0]["heading"] == "Retrieval accuracy"
    assert secs[0]["axis"] == "retrieval accuracy"


def test_acronyms_survive_display_casing():
    assert _heading_for("QPS under load") == "QPS under load"
    assert _heading_for("F1 score") == "F1 score"
    assert _heading_for("multi-hop reasoning") == "Multi-hop reasoning"


# ── the architect is now the fallback, not the default ───────────────────

async def test_a_run_with_a_schema_never_calls_the_architect(monkeypatch):
    """The outline is derived, not generated. If the architect were still
    invoked we would be paying for an LLM call whose result is discarded — and
    reintroducing the template shape it produces."""
    import time

    from app.agents import nodes

    called = {"n": 0}

    async def boom(*_a, **_kw):
        called["n"] += 1
        raise AssertionError("architect must not run when a schema is present")

    async def no_checkpoint(*_a, **_kw):
        return None

    monkeypatch.setattr(nodes, "complete_json", boom)
    monkeypatch.setattr(nodes, "_checkpoint", no_checkpoint)

    state = {
        "run_id": "r", "project_id": "p", "query": "how do A and B compare?",
        "llm_calls_used": 0, "started_at": time.time(), "coverage_notes": [],
        "clarification": {"objective": "compare A and B", "sub_questions": []},
        "paper_doc_ids": ["d1"], "repo_doc_ids": [], "blog_doc_ids": [],
        "evidence_matrix": [], "synthesis": {},
        "evidence_schema": {
            "research_type": "comparison", "entities": ["A", "B"],
            "required_dimensions": [
                {"name": "accuracy", "description": "How accurate?",
                 "synonyms": [], "metrics": [], "kind": "quantitative"}],
            "optional_dimensions": [],
        },
    }
    await nodes.report_architect_node(state)

    assert called["n"] == 0
    assert [s["axis"] for s in state["sections"]] == ["accuracy"]
    assert state["llm_calls_used"] == 0     # one call cheaper than before
