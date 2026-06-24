# Grounded Research Assistant — Architecture v2.1

Status: implemented. Supersedes the v1 LangGraph pipeline.

## v2.1 addendum (implemented changes over v2)

1. **Four-provider LLM fleet, complexity-routed** (replaces the 2-provider
   pair): Groq for fast low-stakes steps, Gemini for structured mid-tier
   JSON, DeepSeek for synthesis/judging (strongest free reasoning),
   OpenRouter as spillover. Chains live in `app/llm/router.py:ROUTING`;
   unconfigured providers are skipped automatically.
2. **Evidence-class separation**: scholarly sources (paper/upload) and
   practitioner sources (repo/blog) never share a drafting context.
   Report sections carry `track: academic|technical`; the technical track
   is a clearly-labeled "Implementation landscape" section. Chat claims
   draw only on scholarly evidence; practitioner hits are attached
   separately as `technical_context`.
3. **Tiered corpus retention** (small-infra strategy): external scholarly
   APIs are the global index (never duplicated locally); only the project
   working set is embedded (hot tier, `CORPUS_MAX_EMBEDDED_CHUNKS` cap);
   text + verified claims + quotes persist in Postgres forever (cold tier,
   ~KB per paper); evicted vectors rebuild on demand via the reindex job.
   Chunks backing verified claims are never evicted.
4. **Supabase auth, properly**: frontend signs in with the publishable key
   via supabase-js; backend verifies access tokens against the project
   JWKS endpoint (RS256/ES256), with the legacy HS256 secret as fallback.
   The publishable key is never used for verification.
5. **arXiv PDF fallback**: Semantic Scholar hits without an open-access
   PDF but with a known arXiv id fetch full text from arXiv directly.

## 1. Product definition

A persistent research workspace with a deep-research pipeline inside it.
Two user-facing capabilities, one shared corpus:

1. **Deep research run** (evolved v1 pipeline): query -> multi-source research -> verified report.
   Every run ingests into the project corpus instead of evaporating after 24h.
2. **Grounded chat** (`/api/chat` evolved): Q&A over everything the project has ever ingested,
   with click-to-source provenance and refusal when evidence is absent.

### Non-negotiable guarantees (from complaint-evidence analysis)
- G1: Every claim shown traces to a source span (doc, page, char offsets). No span -> no claim.
- G2: Zero fabricated citations. References render only from verified citation objects.
- G3: Closed corpus by default. External info enters only via explicit, labeled search steps.
- G4: Refusal over fabrication. "Your corpus does not cover this" is a valid, good answer.
- G5: Honest gaps. Reports state what could not be verified instead of papering over it.

## 2. Design laws

1. **Agents propose, deterministic verifiers dispose.** LLMs never have final authority.
2. **Verification gates; it never merely observes.** v1's fatal flaw: `verify_node` computed
   grounding_score and unsupported_claims[] AFTER report generation, then shipped anyway.
   v2: failing claims are stripped, regenerated, or surfaced as explicit gaps — enforced by
   graph topology, not by convention.
3. **Loops, not a one-shot DAG.** plan is revisitable. verify/report have conditional edges
   back to plan for the failing sub-question only, with hard budget caps.
4. **Citations are structured objects end to end.** The LLM never authors `[N]` markers;
   numbering is generated at render time from claim->chunk links.
5. **Synthesis reads chunks, not prior LLM prose.** No triple compression
   (chunks -> rag_answer -> synthesis). Each synthesis unit gets raw chunk text + span IDs.
6. **Evals before features.** Per-stage metrics so "results are bad" is debuggable.

## 3. Stack (maximum reuse of v1)

| Layer            | Choice                              | Status vs v1 |
|------------------|-------------------------------------|--------------|
| API              | FastAPI                             | kept         |
| Orchestration    | LangGraph                           | kept, new topology |
| Vector store     | Qdrant (vectors + BM25 corpus)      | kept         |
| System of record | Supabase Postgres (+ auth, RLS)     | promoted: now stores documents, chunks-metadata, claims, citations, answers, runs, graph |
| Cache/queue      | Redis                               | kept, ephemeral only (progress, throttle buckets, LLM cache) |
| PDF parse        | pymupdf4llm (+ OCR fallback later)  | kept, page cap removed |
| Embeddings       | sentence-transformers, local        | kept/confirmed (free) |
| Rerank           | cross-encoder, local                | kept (relevance only — NOT entailment) |
| Entailment       | local NLI model (DeBERTa-v3-MNLI class) | NEW (free, replaces cross-encoder misuse) |
| LLMs             | Gemini Flash + Groq, free tier only | kept, re-routed (see section 7) |
| External search  | arXiv, Semantic Scholar, GitHub, Tavily whitelist | kept |

Rule of custody: Supabase = durable truth. Qdrant = vectors keyed by chunk_id (rebuildable).
Redis = disposable. Anything in Redis must be reconstructable from Supabase + Qdrant.

## 4. Data model (Supabase)

- `projects` (workspace unit; RLS per user)
- `documents` (source_type: paper|repo|blog, metadata, dedup keys: sha256, doi/arxiv_id, fuzzy title+authors; preprint/published linked as versions, not collapsed)
- `chunks` (document_id, section, page, char_start, char_end, text; embedding lives in Qdrant under same chunk_id)
- `claims` (text, answer_id/report_id, status: verified|failed|gap)
- `claim_evidence` (claim_id -> chunk_id, quote, quote_match_ok bool, nli_label, nli_score)
- `citations` (resolved identifier, resolver: corpus|crossref|openalex|arxiv, verified_at)
- `runs` (pipeline executions: plan json, per-node status, budgets spent, checkpoint state)
- `answers` (grounded chat responses, linked claims)
- `graph_nodes` / `graph_edges` (persisted GraphBuilder output; Redis only caches)
- `audit_log`, `feedback`

## 5. LangGraph topology v2

```
clarify -> plan -> research_parallel -> ingest_index -> outline
   ^                                                      |
   |                                            per-section loop:
   |                                   retrieve -> draft -> GATE
   |                                       ^town          |
   |                                       |  fail (<=2 regen)
   |                                       +--------------+
   |                                                      | still failing
   +---------------- replan(sub-question, <=1) <----------+
                                                          | pass / budget spent
                                              assemble (deterministic)
                                                  -> build_graph -> END
```

- clarify, plan, research_parallel (paper/code/blog agents), build_graph: carried from v1.
- ingest_index: v1 paper-agent internals promoted to a deterministic shared pipeline.
  Changes: no top-N cap before relevance scoring (cap AFTER scoring); no 20-page parse limit
  (parse fully, per-section fallback on parser errors); abstract-only sources labeled as such.
- outline: planner proposes report sections per question (replaces v1 fixed schema of
  consensus[]/contested[]/gaps[] — that rubric is available as one template, not forced).
- draft: one synthesis unit per section over <=K chunks, raw chunk text in, claims+span refs out.
- GATE (deterministic, blocking) — see section 6.
- Budgets: per-run caps on LLM calls, tokens, wall-clock, regen attempts, replans.
  Checkpoint to `runs` after every node; crashed runs resume, never restart.

## 6. Verification gate (free-tier compatible)

Three layers, all cheap, all deterministic-or-local:

1. **Citation resolver**: every reference resolves against the corpus or CrossRef/OpenAlex/arXiv.
   Unresolvable -> structurally unrenderable (UI accepts only verified citation objects).
2. **Quote exact-match**: the drafting LLM must return, per claim, a verbatim quote from the
   cited chunk. Code string-matches the quote (normalized whitespace) against the chunk text.
   No verbatim match -> claim fails. This is the key trick that makes a weak free model
   trustworthy: it cannot fake a quote that survives exact matching.
3. **NLI entailment** (local DeBERTa-class model): claim vs cited chunk. Contradiction or
   low-entailment -> claim fails even with a matching quote (catches quote-out-of-context).

Fail handling: regenerate section (<=2) -> replan sub-question (<=1) -> emit explicit gap:
"No verifiable support found for X across N sources searched."

Why not cross-encoder for this (v1 mistake): cross-encoders score similarity, not entailment;
"X improves Y" vs "X does not improve Y" score near-identically. Cross-encoder stays for rerank.

## 7. Free-tier LLM strategy

| Step                         | Model                | Mitigation for weakness |
|------------------------------|----------------------|-------------------------|
| clarify, query expansion     | Groq (Llama 70B class) | low stakes |
| screening / relevance notes  | Gemini Flash         | schema-validated JSON, retry once |
| section drafting             | Gemini Flash         | small units (<=K chunks), quote requirement, gate |
| verification judge (backup)  | Gemini Flash         | only adjudicates NLI borderline band; must cite quote, code-checked |
| embeddings / rerank / NLI    | local models         | free, no API limits |

- **Throttling**: token-bucket per provider in Redis honoring free-tier RPM/RPD; pipeline is
  async-job shaped, so slow is acceptable, exceeding limits is not.
- **Caching**: LLM call cache keyed by (model, prompt hash) in Redis; re-runs and regens reuse.
- **Fallback chain**: Gemini <-> Groq on 429/outage; identical JSON schemas both sides.
- Design accepts: lower eloquence. Design does not accept: lower truthfulness — truthfulness
  is enforced by layers that don't depend on model quality.

## 8. API surface

Kept: `/api/pipeline` `/api/status` `/api/report` `/api/chat` `/api/graph` `/api/clarification`
New: `/api/projects` `/api/documents` (upload/import/list/delete) `/api/claims/{id}/evidence`
     `/api/search/refind` ("where did I read this" over project corpus)
Changed: `/api/chat` is grounded-with-refusal over the persistent corpus; `/api/report`
returns claims as objects with evidence links, prose rendered client-side or at render time.

## 9. Edge cases (mechanisms, by zone)

Ingestion: encrypted/corrupt PDFs quarantined with reason, never block the batch; scanned ->
OCR fallback; huge imports chunked + resumable; duplicate uploads idempotent by hash;
paywalled/abstract-only sources labeled (never silently degraded); non-English tagged.
Answering: empty corpus -> onboarding; out-of-corpus question -> refusal + labeled external
search offer; contradictory sources -> both sentences side by side; deleted doc -> tombstone,
old answers show "source removed"; updated doc -> stale flags on dependent answers;
broad question -> map-reduce over ranked chunks, provenance preserved.
Agents: runaway -> budget kill with partial results + explicit gaps; tool failure -> checkpoint
resume; invalid tool args -> schema reject, one retry, loud fail; agent crash in
research_parallel -> remaining agents proceed, coverage noted in report.
LLM ops: 429 -> backoff + provider switch; prompt injection from PDFs -> document text is data
(fenced), imperative text in chunks cannot trigger tools; injection-pattern screen on chunks.
Product: flat pricing if/when monetized, no credits; renewal reminders; self-serve cancel.

## 10. Eval harness (Phase 0, runs in CI)

Golden set: ~30 questions over a frozen mini-corpus with human-verified answers + spans.
Per-stage metrics: retrieval recall@k, rerank MRR, claim support rate, quote-match rate,
fabricated citation count, refusal correctness, end-to-end groundedness.
Release gates: fabricated citations = 0 (build fails on one), claim support >= 98%,
refusal correctness >= 95%. Drift dashboard from production spot-checks later.

## 11. Build phases

- **Phase 0 — trust infrastructure**: repo scaffold, Supabase schema, eval harness skeleton,
  port v1 chunker/retrieval, local NLI + quote-match gate as a library with tests.
- **Phase 1 — pipeline v2**: LangGraph new topology on persistent schema, structured claims,
  budgets + checkpoints, report with evidence links. (Maximum v1 code reuse lives here.)
- **Phase 2 — workspace**: grounded chat over accumulated corpus, refind search, document
  upload/Zotero import, graph persisted.
- **Phase 3 — leverage**: contradiction surfacing, session memory (if validated), audience
  rewriting, collaboration.

## 12. v1 -> v2 changes summary

| v1                                          | v2 |
|---------------------------------------------|----|
| verify_node observes, ships anyway          | blocking gate with regen/replan/gap edges |
| one-shot DAG, plan never revisited          | conditional edges back to plan, budgeted |
| inline [N] string citations, dual renumbered tracks | claim->chunk objects, render-time numbering |
| synthesis from rag_answer (compressed)      | synthesis from raw chunks per small section |
| fixed report schema (consensus/contested/...) | per-question outline; old rubric = one template |
| cross-encoder as truth check                | cross-encoder rerank only; NLI + quote match for truth |
| top-N cap before relevance, 20-page parse cap | cap after scoring; full parse with fallbacks |
| Redis session state, 24h TTL, disposable    | Supabase system of record; Redis ephemeral |
| no evals                                    | Phase 0 harness, CI release gates |
| Gemini Flash for synthesis, unmitigated     | same free models + structural mitigations (sec. 7) |
