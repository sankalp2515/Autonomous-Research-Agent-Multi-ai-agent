#!/usr/bin/env python3
"""Build the Veriscope architecture board in Miro, via the REST API v2.

This produces a real, laid-out Miro board — frames, shapes and connectors —
not a Mermaid dump. It is the same content as docs/architecture-flow.svg,
arranged for a walkthrough: you present it top-to-bottom, one frame per beat.

USAGE
-----
    # 1. Get a token: https://miro.com/app/settings/user-profile/apps
    #    Create an app in your dev team, grant `boards:read` + `boards:write`,
    #    then "Install app and get OAuth token".
    export MIRO_ACCESS_TOKEN="..."          # PowerShell: $env:MIRO_ACCESS_TOKEN="..."

    python scripts/build_miro_board.py                     # create a new board
    python scripts/build_miro_board.py --board-id <id>     # add to an existing board

Only dependency is `requests`:
    pip install requests

The script is idempotent per run, not across runs — re-running creates a fresh
board unless you pass --board-id.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("This script needs `requests`. Install it with:  pip install requests")

API = "https://api.miro.com/v2"

# ── Editorial Science palette (mirrors frontend/src/styles.css) ────────────
INK, PAPER = "#1c1e17", "#fbfbf7"
ACCENT, OK, WARN, BAD, STEEL, MARK = (
    "#8c2f39", "#356b4d", "#8a5a1a", "#a3333a", "#3d5a70", "#f6e9b8",
)
TINT = {
    ACCENT: "#f0e2e3", OK: "#eaf0ea", WARN: "#f3e7d4",
    STEEL: "#eef1f4", BAD: "#f0e2e3",
}

session = requests.Session()


def call(method: str, path: str, **kw) -> dict:
    """One API call, with a courteous pause and a readable failure."""
    r = session.request(method, f"{API}{path}", timeout=30, **kw)
    if r.status_code == 429:                       # rate limited — back off once
        time.sleep(2)
        r = session.request(method, f"{API}{path}", timeout=30, **kw)
    if not r.ok:
        sys.exit(f"\nMiro API {method} {path} failed [{r.status_code}]\n{r.text}\n")
    time.sleep(0.12)                               # stay well under the credit budget
    return r.json() if r.text else {}


# ── item builders ─────────────────────────────────────────────────────────

def frame(board: str, x: float, y: float, w: float, h: float, title: str) -> str:
    body = {
        "data": {"title": title, "format": "custom", "type": "freeform"},
        "position": {"x": x, "y": y},
        "geometry": {"width": w, "height": h},
        "style": {"fillColor": "#f1f1ea"},
    }
    return call("POST", f"/boards/{board}/frames", json=body)["id"]


def shape(board: str, x: float, y: float, w: float, h: float, html: str,
          border: str = STEEL, fill: str | None = None, size: int = 14,
          form: str = "round_rectangle") -> str:
    body = {
        "data": {"shape": form, "content": html},
        "style": {
            "fillColor": fill or TINT.get(border, PAPER),
            "borderColor": border, "borderWidth": "2",
            "color": INK, "fontSize": str(size),
            "textAlign": "left", "textAlignVertical": "top",
        },
        "position": {"x": x, "y": y},
        "geometry": {"width": w, "height": h},
    }
    return call("POST", f"/boards/{board}/shapes", json=body)["id"]


def text(board: str, x: float, y: float, w: float, html: str, size: int = 18) -> str:
    body = {
        "data": {"content": html},
        "style": {"color": INK, "fontSize": str(size), "textAlign": "left"},
        "position": {"x": x, "y": y},
        "geometry": {"width": w},
    }
    return call("POST", f"/boards/{board}/texts", json=body)["id"]


def connect(board: str, a: str, b: str, label: str = "",
            color: str = "#8c8f80", dashed: bool = False) -> None:
    body = {
        "startItem": {"id": a}, "endItem": {"id": b}, "shape": "elbowed",
        "style": {
            "strokeColor": color, "strokeWidth": "2",
            "strokeStyle": "dashed" if dashed else "normal",
            "endStrokeCap": "arrow",
        },
    }
    if label:
        body["captions"] = [{"content": label, "position": "50%"}]
    call("POST", f"/boards/{board}/connectors", json=body)


def h(title: str, *lines: str) -> str:
    """Shape content: a bold title over plain lines."""
    out = f"<p><strong>{title}</strong></p>"
    return out + "".join(f"<p>{ln}</p>" for ln in lines)


# ── the board ─────────────────────────────────────────────────────────────

def build(board: str) -> None:
    print("  · banner")
    text(board, -1500, -560, 2000,
         "<p><strong>VERISCOPE — verifiable-by-construction research agent</strong></p>", 44)
    text(board, -1300, -480, 2400,
         "<p>Deep-research pipeline where every published sentence resolves to a real "
         "source span. Flow traced from the HTTP entry point.</p>", 20)
    text(board, 1500, -560, 1600,
         "<p><strong>THE GROUNDING CONTRACT</strong></p>"
         "<p>G1 span-traced · G2 zero fabricated citations · G3 closed corpus</p>"
         "<p>G4 refusal over fabrication · G5 honest gaps</p>", 16)

    # ── 1-3 · entry path ──────────────────────────────────────────────────
    print("  · 1-3  entry path")
    frame(board, 0, -100, 5000, 620, "1–3 · ENTRY PATH — one HTTP call, then everything is async")

    user = shape(board, -2000, -200, 320, 260,
                 h("🔬 Researcher", "a research question"), OK, PAPER, 16)
    fe = shape(board, -1560, -200, 620, 300, h(
        "1 · FRONTEND LAYER",
        "React 18 · TypeScript · Vite 6",
        "Supabase JS — JWT sign-in",
        "Evidence rail · click-to-source",
        "<em>src/App.tsx → api.ts</em>"), OK)
    api = shape(board, -820, -200, 700, 340, h(
        "2 · API LAYER — the entry point",
        "<strong>POST /api/pipeline → start_pipeline()</strong>",
        "FastAPI · async SQLAlchemy · Pydantic",
        "Idempotency-Key · RLS tenancy",
        "load-shed 503 · per-project run cap",
        "Fails closed at boot: no auth, or no NLI, in prod ⇒ refuses to start"), WARN)
    queue = shape(board, 0, -200, 640, 320, h(
        "3 · QUEUE → WORKER",
        "Redis list queue — durable jobs",
        "processing list · retry · dead-letter",
        "per-run Redis lock — exactly-once",
        "<em>worker.py → graph.execute_run()</em>"), STEEL)
    prog = shape(board, 760, -200, 560, 300, h(
        "LIVE PROGRESS",
        "Redis Pub/Sub fan-out",
        "GET /status/{id}/stream",
        "SSE + WebSocket",
        "node-by-node status"), OK)

    for a, b in ((user, fe), (fe, api), (api, queue), (queue, prog)):
        connect(board, a, b, color=ACCENT)
    connect(board, prog, fe, "progress events ↺ to the browser", STEEL, dashed=True)

    # ── 4 · orchestrator ──────────────────────────────────────────────────
    print("  · 4    orchestrator")
    frame(board, 0, 620, 5000, 700, "4 · AGENT ORCHESTRATOR — LangGraph StateGraph")
    text(board, 0, 400, 4400,
         "<p>Typed <strong>PipelineState</strong> through 9 nodes · every node checkpointed to "
         "Postgres · budgets: 5400s wall / 150 LLM calls / recursion_limit 40 — "
         "<em>budget_reason() names which budget ran out.</em></p>", 18)

    nodes = [
        ("clarify", "intent guard · 4–6 sub-questions", "scope + constraint parsing", ACCENT),
        ("plan", "source-specific search queries", "memory-informed", ACCENT),
        ("evidence_schema", "declares the REQUIRED axes", "BEFORE any paper is read", OK),
        ("research", "arXiv + S2 → SCREEN → ingest", "into the project corpus", OK),
        ("extract_evidence", "each paper → StudyRecord", "→ the evidence matrix", OK),
        ("report_architect", "how it is COMMUNICATED", "runs AFTER evidence exists", WARN),
        ("draft_sections", "retrieve → claims → GATE", "bounded regeneration", WARN),
        ("assemble", "deterministic · no LLM", "cites only resolved rows", STEEL),
        ("build_graph", "cross-source knowledge edges", "", STEEL),
    ]
    ids, x = [], -1960
    for name, l1, l2, col in nodes:
        ids.append(shape(board, x, 560, 420, 260,
                         h(name, l1, l2), col, size=15))
        x += 470
    for a, b in zip(ids, ids[1:]):
        connect(board, a, b, color=ACCENT)
    connect(board, ids[6], ids[1], "bounded replan — max 1 per sub-question", WARN, dashed=True)
    connect(board, queue, ids[0], color=ACCENT)

    # ── 5 · RAG ───────────────────────────────────────────────────────────
    print("  · 5    RAG pipeline")
    frame(board, 0, 1560, 5000, 1000,
          "5 · THE RAG PIPELINE — six stages, all local models, $0 inference")

    stages = [
        ("01 · Parse & Chunk", OK, [
            "PyMuPDF4LLM → markdown", "section-aware, ~1400 chars / 150 overlap",
            "carries page + char offsets", "= the provenance spine",
            "sha256 + DOI + fuzzy dedup"]),
        ("02 · Embed & Index", OK, [
            "BAAI/bge-small-en-v1.5, local", "→ Qdrant vectors keyed by chunk_id",
            "→ Postgres holds the text", "tiered: hot vectors, cold text"]),
        ("03 · Query Transform", WARN, [
            "ONE LLM call, three techniques:", "rewrite · expansion · HyDE",
            "+ multi-hop decomposition", "fail-open — never blocks retrieval"]),
        ("04 · Hybrid Search", WARN, [
            "BM25, cached per project", "+ dense ANN (Qdrant)",
            "→ Reciprocal Rank Fusion", "every path filters project_id",
            "(the closed-corpus rule)"]),
        ("05 · Rerank", ACCENT, [
            "cross-encoder", "ms-marco-MiniLM-L-6-v2", "local, free",
            "scores RELEVANCE ONLY —", "never truth. Truth is the gate."]),
        ("06 · Compress", ACCENT, [
            "query-aware EXTRACTIVE selection", "verbatim sentences only —",
            "an abstractive summary would", "break every quote downstream"]),
    ]
    rag, x = [], -1900
    for title, col, lines in stages:
        rag.append(shape(board, x, 1420, 620, 320, h(title, *lines), col, size=15))
        x += 690
    for a, b in zip(rag, rag[1:]):
        connect(board, a, b, color=ACCENT)
    connect(board, ids[3], rag[0], color=ACCENT)

    dim = shape(board, -1000, 1840, 1900, 380, h(
        "▸ THE FIX THAT MATTERED — DIMENSION-DIRECTED RETRIEVAL",
        "Old path: one generic objective query per paper, keep top-8 of ~63 chunks.",
        "30 of 100 matrix cells came back empty <strong>while the evidence sat in the corpus.</strong>",
        "New path: each paper is searched <strong>once per required dimension</strong> — its own synonyms,",
        "metric tokens and section hints — and the paper's window is allocated <strong>round-robin</strong>",
        "across axes so no axis can starve the others.",
        "<strong>retrieval recall 36.7% → 86.7%</strong> — measured, not claimed (evals/evidence_bench.py)"),
        WARN, MARK, 15)
    scr = shape(board, 1050, 1840, 1900, 380, h(
        "▸ WHAT ENTERS THE CORPUS AT ALL — SCREENING",
        "Ranked <strong>within each source pool</strong> (arXiv, Semantic Scholar), then interleaved —",
        "never globally sorted by citation_count, which silently discarded the entire arXiv",
        "literature (arXiv cannot populate that field). A shipped bug, now pinned by",
        "tests/test_screening_pools.py.",
        "Human-in-the-loop keep/drop + reason · year and citation floors.",
        "<em>Verified ≠ relevant: the gate proves grounding, screening proves topicality.</em>"),
        OK, "#eaf0ea", 15)
    connect(board, rag[3], dim, color=WARN, dashed=True)
    connect(board, ids[3], scr, color=OK, dashed=True)

    # ── 6 · gate ──────────────────────────────────────────────────────────
    print("  · 6    verification gate")
    frame(board, 0, 2700, 5000, 780, "6 · THE VERIFICATION GATE — deterministic, blocking")

    layers = [
        ("Layer 1 · Citation resolution", "the cited chunk must exist in THIS project's corpus", STEEL),
        ("Layer 2 · Quote exact-match", "char-exact verbatim span, ≥12 chars, inside that chunk", WARN),
        ("Layer 3 · NLI entailment", "DeBERTa-v3-MNLI, local — catches quote-out-of-context", ACCENT),
    ]
    lids, y = [], 2480
    for title, sub, col in layers:
        lids.append(shape(board, -1700, y, 900, 180, h(title, sub), col, size=15))
        y += 220

    gate = shape(board, -450, 2700, 560, 560, h(
        "GATE", "Is the claim entailed", "by its own cited source?"),
        ACCENT, TINT[ACCENT], 20, form="rhombus")
    for lid in lids:
        connect(board, lid, gate)

    passed = shape(board, 500, 2500, 900, 240, h(
        "✅ PASS", "persist Claim + ClaimEvidence",
        "chunk_id · verbatim quote · NLI label + score",
        "→ rendered with a click-to-source footnote"), OK)
    regen = shape(board, 500, 2820, 430, 200, h(
        "♻️ FAIL → regenerate", "bounded, with feedback"), WARN)
    gap = shape(board, 970, 2820, 430, 200, h(
        "⚠️ FAIL → labeled gap", "never papered over"), BAD)
    connect(board, gate, passed, "pass", OK)
    connect(board, gate, regen, "fail", WARN)
    connect(board, gate, gap, "still failing", BAD)
    connect(board, regen, ids[6], color=WARN, dashed=True)

    cells = shape(board, 1900, 2700, 1200, 620, h(
        "ABSENCE OF EVIDENCE ≠ EVIDENCE OF ABSENCE",
        "Each study × required dimension resolves to ONE of four states:",
        "• <strong>reported</strong> — a verified finding exists &nbsp;<em>(about the study)</em>",
        "• <strong>not_reported</strong> — the study omits it &nbsp;<em>(about the study)</em>",
        "• <strong>not_applicable</strong> — the axis cannot apply &nbsp;<em>(about the study)</em>",
        "• <strong>extraction_uncertain</strong> — <em>OUR limit, not the study's</em>",
        "",
        "<strong>THE RULE THAT NEVER RELAXES:</strong> claiming not_reported requires",
        "EVIDENCE OF SEARCH — full text in hand, N distinct queries, M passages",
        "examined. Anything thinner falls to extraction_uncertain."), ACCENT, PAPER, 15)
    connect(board, gate, cells, color=ACCENT, dashed=True)

    # ── 7 · memory ────────────────────────────────────────────────────────
    print("  · 7    memory")
    frame(board, 0, 3760, 5000, 700,
          "7 · MEMORY — six kinds, each on the store that fits its lifetime")
    text(board, 0, 3540, 4400,
         "<p><strong>Agent memory is never evidence.</strong> It orients planning; it never becomes a "
         "citation. The grounding invariant stays intact: claims cite verified source spans, "
         "not memory.</p>", 18)

    mems = [
        ("Working / run state", STEEL, "LangGraph PipelineState", [
            "Typed dict threaded through every node,",
            "checkpointed to Postgres after each step.",
            "A crashed worker RESUMES from the last",
            "node — it does not restart the run."], "Postgres JSONB + LangGraph"),
        ("Short-term ephemeral", WARN, "Redis — disposable by rule", [
            "progress Pub/Sub → SSE · token buckets",
            "(free-tier RPM) · LLM prompt-hash cache",
            "· idempotency keys · job queue + locks.",
            "Anything here must be rebuildable."], "Redis 7"),
        ("Long-term semantic", OK, "the project corpus", [
            "Chunk vectors keyed by chunk_id, always",
            "project-filtered. TIERED: hot vectors are",
            "capped and evictable; text and claims live",
            "in Postgres forever. Chunks backing a",
            "verified claim are NEVER evicted."], "Qdrant + Postgres"),
        ("Episodic + preference", ACCENT, "agent memory across runs", [
            "episodic — one line per completed run",
            "preference — user-pinned facts",
            "recall(): local-embedding cosine, degrades",
            "to keyword + recency. Folded into PLAN",
            "as orientation only."], "Postgres + bge-small"),
        ("Verified knowledge", OK, "what the system KNOWS", [
            "Claim · ClaimEvidence · Citation ·",
            "graph_nodes/edges. Every row carries a",
            "chunk_id, a verbatim quote and an NLI",
            "score. The only surface the report is",
            "allowed to render."], "Postgres — system of record"),
        ("Conversational scope", STEEL, "ad-hoc chat context", [
            "User selects papers, claims or prior",
            "answers anywhere in the app → resolved",
            "down to real documents + chunks. The",
            "throwaway context runs the SAME gate, so",
            "it stays verifiable, not a side channel."], "chat_context.py"),
    ]
    mids, x = [], -1900
    for title, col, sub, lines, stack in mems:
        mids.append(shape(board, x, 3760, 620, 420,
                          h(title, f"<em>{sub}</em>", *lines, f"<strong>{stack}</strong>"),
                          col, size=14))
        x += 690
    connect(board, mids[3], ids[1], "recalled at planning", ACCENT, dashed=True)
    connect(board, ids[7], mids[3], "records episodic memory", ACCENT, dashed=True)
    connect(board, passed, mids[4], color=OK, dashed=True)
    connect(board, rag[1], mids[2], color=OK, dashed=True)

    # ── 8-11 · platform ───────────────────────────────────────────────────
    print("  · 8-11 platform")
    frame(board, 0, 4700, 5000, 780, "8–11 · PLATFORM — models, data, observability, the artifact")

    llm = shape(board, -1700, 4700, 950, 620, h(
        "8 · LLM LAYER — routed fleet ($0 tier)",
        "One entry point: <strong>llm/router.py</strong>",
        "1. Redis prompt-hash cache — regens are free",
        "2. token-bucket throttle — waits, never violates RPM",
        "3. per-STEP provider chain, instant failover",
        "4. schema-validated JSON + one repair retry",
        "5. circuit breaker on 401/402/403 (300s cooldown)",
        "",
        "Groq llama-3.3-70b · NVIDIA · Gemini Flash",
        "DeepSeek · OpenRouter (spillover)",
        "",
        "<em>A weak model costs recall, never correctness — the gate",
        "stands between every model and the reader.</em>"), ACCENT, PAPER, 15)

    data = shape(board, -600, 4700, 880, 620, h(
        "9 · DATA LAYER",
        "<strong>Postgres 16 / Supabase</strong> — system of record",
        "RLS multi-tenancy · alembic · JWKS auth (RS256)",
        "",
        "<strong>Qdrant 1.12</strong> — vectors by chunk_id, rebuildable",
        "",
        "<strong>Redis 7</strong> — queue · cache · locks · pub/sub",
        "",
        "<strong>Blob store + PDF library</strong>",
        "Docker Compose — one-command local stack",
        "",
        "<em>Custody rule: Postgres is durable truth, Qdrant is",
        "rebuildable, Redis is disposable.</em>"), STEEL)

    obs = shape(board, 500, 4700, 950, 620, h(
        "10 · OBSERVABILITY & EVALUATION",
        "OpenTelemetry · Prometheus · Grafana · Tempo · Loki",
        "LangSmith · Sentry · PII scrubbing + audit log",
        "",
        "<strong>Evals are ship gates, not vibes:</strong>",
        "run_evals.py — golden set, must pass to merge",
        "evidence_bench.py — recall + mislabeled_not_reported",
        "extraction_ab.py — live A/B over an ingested corpus",
        "run_ragas.py · 17 pytest suites · GitHub Actions CI",
        "",
        "<em>Fill rate is not the objective — a fabricated cell is",
        "worse than a correctly labeled hole.</em>"), OK)

    art = shape(board, 1670, 4700, 950, 620, h(
        "11 · THE ARTIFACT",
        "Analysis plan — the reasoning, shown",
        "Evidence matrix — studies × dimensions, rendered",
        "BEFORE anyone's synthesis of them",
        "Sections → sub-themes → claims",
        "Metric callouts (concrete quantity + NLI ≥ 0.85)",
        "Inline footnotes colored by confidence",
        "Works Cited — verbatim span, page range, NLI score",
        "Methods funnel — found → screened → ingested →",
        "cited, and what was REFUSED",
        "",
        "<strong>Every sentence is click-to-source.</strong>"), ACCENT, PAPER, 15)

    connect(board, ids[8], art, color=ACCENT)
    connect(board, ids[0], llm, color=STEEL, dashed=True)
    connect(board, mids[4], data, color=STEEL, dashed=True)
    connect(board, art, obs, color=STEEL, dashed=True)

    text(board, 0, 5120, 4400,
         "<p><strong>DESIGN LAW — agents propose, deterministic verifiers dispose.</strong> "
         "Enforced by graph topology, not by convention. LLMs never have final authority "
         "over what a reader sees.</p>", 22)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the Veriscope architecture board in Miro.")
    ap.add_argument("--board-id", help="add to an existing board instead of creating one")
    ap.add_argument("--name", default="Veriscope — Architecture Flow", help="new board name")
    args = ap.parse_args()

    token = os.environ.get("MIRO_ACCESS_TOKEN")
    if not token:
        sys.exit("Set MIRO_ACCESS_TOKEN first — see the docstring at the top of this file.")
    session.headers.update({"Authorization": f"Bearer {token}",
                            "Content-Type": "application/json"})

    if args.board_id:
        board = args.board_id
        print(f"Adding to existing board {board}")
    else:
        created = call("POST", "/boards", json={
            "name": args.name,
            "description": "Verifiable-by-construction research agent — architecture flow, "
                           "traced from the HTTP entry point.",
            "policy": {"sharingPolicy": {"access": "private", "teamAccess": "edit"}},
        })
        board = created["id"]
        print(f"Created board {board}")

    build(board)
    print(f"\n✅ Done → https://miro.com/app/board/{board}/")


if __name__ == "__main__":
    main()
