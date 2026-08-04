# Veriscope — System Overview

> **Research you can prove.** A verifiable-by-construction research agent: every
> sentence it shows you is quote-checked against a real source, or it isn't shown.

This document is the single, transparent reference for **what Veriscope is, what
it does, how it works, and how it is measured.** It mirrors the in-app **About**
section.

---

## 1. What it is

Most AI research tools fabricate — plausible summaries with citations that are
subtly wrong, sources that don't exist, numbers no paper reported. You end up
re-verifying everything by hand and the time saving evaporates.

**Veriscope flips the default: nothing reaches you unless it survives a
verification gate.** A multi-agent pipeline searches real papers (arXiv,
Semantic Scholar), drafts a report, and **drops any
claim that cannot be (1) matched to a verbatim quote in a real source chunk and
(2) entailed by that chunk.** Citations render only from resolved references, so
**fabricated citations are structurally impossible**; when the corpus can't
answer, it **refuses** instead of guessing.

## 2. Core guarantees

| Guarantee | How it's enforced |
|---|---|
| **Quote-match** | Every claim carries a verbatim quote that must exact-match its cited chunk, character-for-character. |
| **Entailment** | An NLI model checks the claim is *entailed* by the source — not just that a matching string exists. |
| **No fabricated citations** | References render only from the `citations` table, populated after resolution. A made-up citation has no row, so it cannot render. |
| **Honest refusal** | No supporting evidence → the system refuses and states what's missing, rather than inventing an answer. |

## 3. How it works — the pipeline

```
clarify → plan → research → outline → draft_sections → [replan?] → assemble → build_graph
             ↑_________________________________________________|
```

1. **Clarify** — an intent guard rejects non-research asks; the question is
   decomposed into 2–5 answerable sub-questions.
2. **Plan** — source-specific search queries for arXiv / Semantic Scholar,
   informed by the project's **cross-session memory** (what it already
   researched) so it goes deeper instead of re-treading.
3. **Research** — a specialist agent searches & ingests papers: PDFs are
   downloaded, parsed, chunked, embedded. Partial failures become honest
   *coverage notes*, never silent gaps.
4. **Outline** — a report structure where each section maps to **one distinct,
   non-overlapping sub-question**, so no finding is restated across sections.
5. **Draft + verify** — each section is drafted as discrete claims; every claim
   runs the **quote-match + NLI gate**. Failures regenerate with feedback, then
   trigger a **bounded replan**. Only survivors are persisted.
6. **Assemble** — deterministic (no LLM): resolves citations, writes the report.
7. **Build graph** — cross-source edges + an episodic memory of the run.

Every node **checkpoints** full state, so an interrupted run **resumes** from
where it stopped.

## 4. Features

- **Deep research runs** — a verified report with click-to-source evidence for
  every sentence, plus a live, streamed view of the running pipeline.
- **Grounded chat** — ask follow-ups over your corpus; it refuses over guessing.
- **Cross-paper comparison** — compare papers side-by-side; every cell is drafted
  from that paper alone and quote-checked (click any cell for its source).
- **Persistent library** — corpus, findings, notes and unfinished runs persist;
  a **welcome-back** surface resumes exactly where you left off.
- **Discovery map** — explore the corpus by similarity; select papers to compare.
- **Standing monitor** — keeps watching for new papers matching your open
  questions and surfaces them for one-click add.
- **RAG evaluation dashboard** — six metrics, every number traced to its evidence.

## 5. Evaluation — measured, not claimed

The **Metrics** dashboard scores each report. Every metric is computed from the
same evidence the verification gate produced, so it is **auditable**.

| Metric | Definition |
|---|---|
| **Citation Accuracy** | Fraction of claims whose quote exactly matches its cited span. Gate-enforced → ~100%. |
| **Answer Faithfulness** | Fraction of claims *entailed* by their cited source (NLI) — real support, not just a matching string. |
| **Answer Relevance** | Cosine similarity between the question and the assembled answer (local embeddings). |
| **Context Precision** | Of chunks retrieved per section, the fraction topically relevant — low retrieval noise. |
| **Context Recall** | Fraction of claims for which a retrieved chunk genuinely supports them — the retriever surfaced the needed evidence. |
| **Latency** | End-to-end run wall time with a per-node breakdown and LLM-call count. |

**Graceful degradation:** with the local ML stack off, the deterministic metrics
(citation accuracy, latency) still compute; the ML-dependent ones are reported as
*unavailable* rather than faked.

There is also an **offline release gate** (`python -m evals.run_evals`) that runs
the real grounded path against a frozen mini-corpus and fails CI if fabricated
citations > 0, claim support rate < 0.98, or refusal correctness < 0.95.

## 6. Tech stack

| Layer | Choice |
|---|---|
| Orchestration | LangGraph multi-agent pipeline, checkpoint/resume |
| API | FastAPI (async), Server-Sent Events for live progress |
| System of record | Postgres (durable truth); Qdrant vectors + Redis state rebuildable from it |
| Retrieval | Hybrid dense + BM25, RRF fusion, cross-encoder rerank, query transform + HyDE |
| Verification | Deterministic quote-match + NLI entailment model |
| Frontend | React + Vite + TypeScript |

## 7. Roadmap / TODO

- **Practitioner sources (GitHub + engineering blogs).** The specialist agents
  (`app/agents/sources.py: search_github / search_blogs`) are implemented and
  kept intact, but **disabled** (`practitioner_sources_enabled = False`) — they
  mixed evidence classes and added wall time for little gain on scholarly
  questions. Re-enable when the practitioner track earns its place.
- **Map citation edges.** Reference edges via the Semantic Scholar references
  API are gated off (`map_citation_edges_enabled = False`) because that endpoint
  is rate-limited without a key and made the map hang. The map now renders fast
  from local similarity edges only. Re-enable with an S2 API key.

## 8. Run it

```bash
cp .env.example backend/.env            # add free LLM keys
docker compose --profile app up --build # whole app at http://localhost:8080
```

Auth is off by default (open demo); see the README for enabling Supabase sign-in.
