"""The same question, read in a second project, must not cost full price.

WHAT WAS BROKEN. `Chunk.id` is a per-project primary key, and it was printed
into every extraction and drafting prompt — the model has to name the passage
it quotes. So the same paper, read in a new project, produced a prompt that
differed from the first one in exactly the UUIDs, and every LLM cache entry
missed. A completed run was reusable only inside the project that produced it:
re-running the identical question elsewhere re-downloaded, re-parsed,
re-embedded, re-extracted and re-verified everything, and (because the searches
were re-issued live) usually against a DIFFERENT set of papers.

THE FIX IS AN ADDRESSING CHANGE, NOT A GROUNDING CHANGE. A passage is now
identified by its content (`_source_id`), so two chunks with the same bytes are
the same evidence in any project and the prompt for a given paper is
byte-identical wherever it is read. The id is translated back to a real
`Chunk.id` before anything is persisted, so every `ClaimEvidence` row still
points at a row THIS project owns, and the gate still matches quotes against
real chunk text.

Four memos then remove the recomputation the stable prompt exposes: search
responses, PDF parses, embeddings and NLI verdicts, each keyed by content.
"""

from dataclasses import dataclass

from app.agents import nodes


@dataclass
class _Chunk:
    chunk_id: str
    text: str
    document_title: str = "A Paper"
    section: str = "Results"
    page_start: int = 1
    page_end: int = 2
    abstract_only: bool = False


TEXT_A = "GraphRAG improves multi-hop accuracy to 89% versus 63% for vector approaches."
TEXT_B = "Latency rose from 120 ms to 410 ms under the graph index."


def _project(prefix: str) -> list[_Chunk]:
    """The same paper as it exists in one project: same text, its own row ids."""
    return [_Chunk(f"{prefix}-1", TEXT_A), _Chunk(f"{prefix}-2", TEXT_B)]


def test_the_same_paper_produces_the_same_prompt_in_any_project():
    """The whole unlock. If this regresses, every cross-project cache misses and
    a re-run silently costs full price again."""
    assert nodes._format_sources(_project("alpha")) == \
           nodes._format_sources(_project("beta"))


def test_a_source_id_is_derived_from_content_not_from_the_row():
    a, _ = nodes._source_index(_project("alpha"))
    b, _ = nodes._source_index(_project("beta"))
    assert set(a) == set(b)
    assert nodes._source_id(TEXT_A) in a
    # And it is genuinely content-sensitive: an edited passage is a new source.
    assert nodes._source_id(TEXT_A) != nodes._source_id(TEXT_A + " Revised.")


def test_every_source_id_maps_back_to_a_row_this_project_owns():
    """The half that keeps G2 true: the model addresses content, but a citation
    the reader clicks has to resolve to a real Chunk in the current project."""
    sid = nodes._source_id(TEXT_A)
    _, alpha = nodes._source_index(_project("alpha"))
    _, beta = nodes._source_index(_project("beta"))
    assert alpha[sid] == "alpha-1"
    assert beta[sid] == "beta-1"
    assert alpha[sid] != beta[sid]


def test_identical_passages_collapse_to_one_source():
    """Two chunks with the same bytes ARE one piece of evidence. Collapsing them
    is correct; the first chunk carrying the text is the one credited."""
    dupes = [_Chunk("row-1", TEXT_A), _Chunk("row-2", TEXT_A)]
    lookup, real = nodes._source_index(dupes)
    assert len(lookup) == 1
    assert real[nodes._source_id(TEXT_A)] == "row-1"


def test_the_gate_lookup_holds_full_text_under_the_id_the_model_is_given():
    """The prompt shows a compressed view; the gate must verify against the FULL
    chunk. Both have to be reachable by the same key or every quote fails."""
    chunks = _project("alpha")
    lookup, _ = nodes._source_index(chunks)
    assert lookup[nodes._source_id(TEXT_A)] == TEXT_A
    block = nodes._format_sources(chunks)
    assert f'chunk_id="{nodes._source_id(TEXT_A)}"' in block
    # The row id must not leak into the prompt - that is what broke portability.
    assert "alpha-1" not in block


# -- Prompt stability under concurrency -----------------------------------

def _counts(matrix):
    """The architect's evidence brief joins, lifted out of the node so the
    ordering rule can be pinned without running the graph."""
    dim_counts: dict[str, int] = {}
    frameworks: dict[str, int] = {}
    for row in matrix:
        for d in {f["dimension"] for f in row.get("findings", [])}:
            dim_counts[d] = dim_counts.get(d, 0) + 1
        for fw in row.get("frameworks", []):
            frameworks[fw] = frameworks.get(fw, 0) + 1
    top_dims = sorted(dim_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:14]
    top_fw = sorted(frameworks.items(), key=lambda kv: (-kv[1], kv[0]))[:14]
    sample = sorted((r["title"] or "")[:70] for r in matrix)[:8]
    return top_dims, top_fw, sample


def _row(title, dims, fws):
    return {"title": title, "frameworks": fws,
            "findings": [{"dimension": d} for d in dims]}


def test_the_architect_brief_does_not_depend_on_extraction_order():
    """`matrix` is appended to by a concurrent worker pool, so its row order is
    the order papers happened to FINISH — different on every run of the same
    question. The architect's sections carry the retrieval brief for drafting,
    so if this prompt is unstable its cache misses, its structure can shift, and
    then every drafting prompt downstream differs too. One unstable join at the
    top costs the entire back half of the run."""
    matrix = [
        _row("Zeta study", ["latency", "accuracy"], ["GraphRAG"]),
        _row("Alpha study", ["accuracy", "cost"], ["VectorRAG"]),
        _row("Mid study", ["latency"], ["GraphRAG"]),
    ]
    assert _counts(matrix) == _counts(list(reversed(matrix)))
    assert _counts(matrix) == _counts([matrix[1], matrix[2], matrix[0]])


def test_equal_counts_are_broken_by_name_not_by_arrival():
    """'cost' and 'accuracy' both appear once here; without the tie-break the
    winner is whichever paper finished first."""
    a = [_row("S1", ["cost"], []), _row("S2", ["accuracy"], [])]
    b = [_row("S2", ["accuracy"], []), _row("S1", ["cost"], [])]
    assert _counts(a)[0] == _counts(b)[0] == [("accuracy", 1), ("cost", 1)]


# -- The extractor's label pool must not depend on the run --------------------

def test_the_label_pool_is_the_schemas_not_the_runs_running_tally():
    """`_extract_one_study` was handed `dims[:14]` — the dimension labels
    discovered by papers that had already FINISHED. A concurrent worker pool
    decides that order, so the same paper produced a different prompt on every
    run, and a different one again when the corpus was a 12-paper subset of the
    28 already read. Measured on a re-run of an already-extracted corpus, 9 of
    12 papers missed the LLM cache for this reason alone — and each miss
    cascades into new gate pairs, a different matrix and a different architect
    prompt after it.

    The schema's axes are derived from the QUESTION at temperature 0, so they
    are the same in every run and every project."""
    state = {"evidence_schema": {
        "required_dimensions": [{"name": "privacy constraints"},
                                {"name": "productivity impact"}],
        "optional_dimensions": [{"name": "compute cost"}],
    }}
    pool = nodes._schema_label_pool(state)
    assert pool[:2] == ["privacy constraints", "productivity impact"]
    assert "compute cost" in pool
    # Required axes lead: they are what the matrix is audited against.
    assert pool.index("privacy constraints") < pool.index("compute cost")
    # And it is a pure function of the schema - no run state, no arrival order.
    assert nodes._schema_label_pool(state) == pool


def test_the_label_pool_is_empty_without_a_schema():
    """Degrades to the legacy hint rather than inventing axes."""
    assert nodes._schema_label_pool({}) == []
