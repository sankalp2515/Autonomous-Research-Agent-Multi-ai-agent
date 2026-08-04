# -*- coding: utf-8 -*-
"""Generates the Veriscope interview-prep .docx (STAR format)."""
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

INDIGO = RGBColor(0x4F, 0x46, 0xE5)
INK = RGBColor(0x16, 0x18, 0x1D)
GREEN = RGBColor(0x0E, 0x6A, 0x52)
GREY = RGBColor(0x55, 0x5A, 0x66)

doc = Document()

# Base style
normal = doc.styles["Normal"]
normal.font.name = "Calibri"
normal.font.size = Pt(10.5)
normal.font.color.rgb = INK
for h, sz in [("Heading 1", 16), ("Heading 2", 13)]:
    st = doc.styles[h]
    st.font.name = "Calibri"
    st.font.size = Pt(sz)
    st.font.color.rgb = INK


def heading(text, level=1):
    doc.add_heading(text, level=level)


def para(text, italic=False, color=None, size=10.5, space_after=6):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.italic = italic
    r.font.size = Pt(size)
    if color:
        r.font.color.rgb = color
    p.paragraph_format.space_after = Pt(space_after)
    return p


def bullet(text):
    p = doc.add_paragraph(style="List Bullet")
    p.add_run(text)
    return p


def question(qtext):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run("Q.  " + qtext)
    r.bold = True
    r.font.size = Pt(11.5)
    r.font.color.rgb = INDIGO


def star(s, t, a, r):
    for label, text in [("Situation", s), ("Task", t), ("Action", a), ("Result", r)]:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.left_indent = Inches(0.15)
        lr = p.add_run(label + " — ")
        lr.bold = True
        lr.font.color.rgb = GREEN if label == "Result" else GREY
        lr.font.size = Pt(10.5)
        p.add_run(text).font.size = Pt(10.5)


def answer(text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.15)
    p.paragraph_format.space_after = Pt(6)
    p.add_run(text).font.size = Pt(10.5)


# ───────────────────────── Title ─────────────────────────
t = doc.add_paragraph()
t.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = t.add_run("Veriscope — Interview Preparation")
r.bold = True
r.font.size = Pt(22)
r.font.color.rgb = INDIGO
sub = doc.add_paragraph()
sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
rs = sub.add_run("Every likely interview question, answered with the STAR method\n"
                 "Project: a verification-gated, multi-agent AI research assistant")
rs.italic = True
rs.font.size = Pt(11)
rs.font.color.rgb = GREY

para("")
para("How to use this document", color=INDIGO, size=12)
answer("STAR = Situation, Task, Action, Result. Behavioural questions use full STAR. "
       "Technical questions give a structured answer (often S/T/A/R-shaped) so you can "
       "narrate context, what you did, and the measurable outcome. Memorise the numbers in "
       "the cheat sheet at the end — quantified answers are what land offers. Speak in the "
       "first person (“I built…”) and keep each answer to 60–90 seconds.")

doc.add_page_break()

# ───────────────────────── 30-second pitch ─────────────────────────
heading("0. The 30-second project pitch")
answer("“I built Veriscope, an AI research assistant that is verifiable by construction. "
       "Most AI research tools fabricate — plausible summaries with citations that don’t "
       "hold up — so I designed a system where every generated claim must quote-match a real "
       "source passage and pass an NLI entailment check before the user ever sees it. Claims that "
       "fail are dropped or shown as honest gaps, and references render only from resolved "
       "citations, so fabricated citations are structurally impossible. It’s a full-stack "
       "build: a LangGraph multi-agent pipeline, hybrid RAG, a verification gate, and it runs "
       "entirely on free-tier LLMs through a throttled, cached, fallback-chained router.”")

# ───────────────────────── 1. Behavioural ─────────────────────────
doc.add_page_break()
heading("1. Behavioural questions (full STAR)")

question("Tell me about a challenging project you built end to end.")
star(
    "AI research tools are widely distrusted — I analysed ~55 real user complaints and found the "
    "dominant failure was fabricated citations and unsupported numbers, which forces users to re-verify "
    "everything by hand.",
    "I set out to build a research assistant whose output you could trust without re-checking — the "
    "guarantee being that no claim reaches the user unless it is provably grounded in a real source.",
    "I designed a verification gate (verbatim quote-match + NLI entailment + citation resolution) sitting "
    "between the LLMs and the user, wrapped a LangGraph multi-agent pipeline around it (clarify → plan "
    "→ parallel search → ingest → outline → draft+gate → assemble), and built hybrid RAG, "
    "ingestion, eval harness, and a React UI — all on free-tier LLMs.",
    "A full run produces a report where every sentence is click-traceable to a highlighted source quote; the "
    "eval harness enforces zero fabricated citations and ≥98% claim support. It demonstrably ships a "
    "trustworthy report end to end on real papers.")

question("Describe a difficult production bug you debugged and fixed.")
star(
    "The background worker kept dying silently during research runs — no Python traceback, runs stuck "
    "forever — and the machine had 15 GB RAM free, so it wasn’t obvious memory pressure.",
    "I had to find why a process was vanishing mid-run with no error and make runs reliably complete.",
    "I traced it to the embedding phase: the paper agent ingests up to 25 papers concurrently, and each "
    "called the same PyTorch model from multiple threads. Concurrent inference on a shared Torch model "
    "segfaults the process — a native crash that bypasses Python exceptions. I serialised all local-model "
    "inference behind a single lock and bounded ingest concurrency.",
    "I reproduced the exact failure (24 concurrent inference calls) and confirmed zero crashes after the fix; "
    "a full pipeline then completed end to end with 17 verified claims. I also added a worker heartbeat and "
    "startup orphan-recovery so a crash can never strand runs again.")

question("Tell me about a significant technical trade-off you made.")
star(
    "I had no budget for paid LLM APIs, only free tiers with strict rate limits and weaker models prone to "
    "hallucination.",
    "I needed trustworthy output despite cheap, fallible models.",
    "Instead of relying on a smarter model, I made trust structural: the verification gate enforces grounding "
    "with deterministic quote-matching plus a local NLI model, so correctness doesn’t depend on model "
    "quality. I added a 4-provider router with token-bucket throttling, prompt-hash caching, fallback chains, "
    "and hard per-call timeouts.",
    "The system is trustworthy on free models — a weak model can hallucinate a paraphrase but cannot fake a "
    "verbatim quote that survives exact matching. Accepted lower eloquence; never lower truthfulness.")

question("Tell me about working with ambiguous or unclear requirements.")
star(
    "The brief was vague: “build an AI research tool researchers would want.” No spec, no users to "
    "interview at hand.",
    "I had to define what to build and justify it rather than guess.",
    "I grounded the requirements in evidence — collected ~55 verbatim complaints across Reddit, Capterra and "
    "academic forums, clustered them, and found trust (fabrication) was the #1 pain by a wide margin. I wrote a "
    "one-line product thesis (“research is a trust problem, not a retrieval problem”) and derived every "
    "feature from it.",
    "Every core decision — the gate, refusal-over-fabrication, evidence-class separation — traces to real "
    "evidence, not assumptions, which kept scope focused and defensible.")

question("Tell me about a time you improved a system’s reliability.")
star(
    "Runs were getting orphaned: when a worker died, the run row stayed “running” forever and the UI "
    "showed nothing — users thought the product was broken.",
    "I needed runs to survive worker crashes and restarts.",
    "I made the worker crash-safe: atomic Redis job claim (LMOVE) so multiple workers never double-process, "
    "per-node checkpoints so runs resume from where they died, a startup orphan-recovery that rebuilds the queue "
    "from the database (the source of truth), bounded LLM-call timeouts, and a heartbeat for visibility.",
    "A worker death no longer strands runs — a restart auto-resumes them — and the heartbeat plus per-call "
    "timing logs make any future stall diagnosable from the last log line.")

question("Tell me about receiving critical feedback and acting on it.")
star(
    "During testing, the reviewer said the report “didn’t feel like a report” and that “Ask this "
    "paper” returned the same claim-card format as the main report — confusing and low-value.",
    "I had to make the output genuinely readable and fit each surface, without breaking the grounding guarantee.",
    "I redesigned the report into a scannable, Gemini-style document (key findings, confidence-coloured inline "
    "citations, contradiction surfacing) and reframed “Ask this paper” as conversational, page-anchored "
    "Q&A scoped to one document — keeping quote-verification throughout.",
    "The feedback directly shaped two redesigns; the constraint I held was that readability improvements could "
    "never introduce ungrounded prose, which kept the trust invariant intact.")

question("Tell me about learning something new quickly to ship.")
star(
    "I hadn’t used LangGraph, NLI-based verification, or contextual retrieval before starting.",
    "I needed working multi-agent orchestration with conditional loops and a real entailment check, fast.",
    "I learned LangGraph’s state/conditional-edge model to build replan-on-insufficient-evidence loops, picked "
    "a DeBERTa-v3 NLI model for entailment (after rejecting cross-encoders, which score similarity not truth), and "
    "implemented Anthropic’s contextual-retrieval idea deterministically (prepend title+section to each chunk) "
    "to avoid a costly per-chunk LLM call.",
    "All three landed in the working system; the NLI choice in particular proved correct — it cleanly separates "
    "entailment/contradiction/neutral where a cross-encoder would have scored them near-identically.")

question("Tell me about prioritising under tight constraints.")
star(
    "Limited compute, free-tier rate limits, and a finite build budget meant I couldn’t do everything.",
    "I had to sequence features for maximum value and avoid half-built work.",
    "I always built the trust infrastructure first (gate + eval harness before any user-facing answer), shipped a "
    "verifiable thin slice, then layered leverage features (monitor agent, map, notebook) once the foundation was "
    "proven. I deferred large items (deployment, collaboration) honestly rather than half-building them.",
    "The result was a coherent, working system at every stage rather than a pile of incomplete features — and a "
    "clear, honest roadmap of what remained.")

# ───────────────────────── 2. Technical deep-dive ─────────────────────────
doc.add_page_break()
heading("2. Technical deep-dive")

question("How does your RAG pipeline work, end to end?")
answer("Ingestion: PDFs are parsed with PyMuPDF4LLM, section-aware chunked with page+char offsets, deduplicated "
       "(sha256 → DOI/arXiv → fuzzy title), and embedded. Retrieval is hybrid: BM25 (lexical) + dense "
       "vectors (Qdrant) fused with Reciprocal Rank Fusion, reranked by a cross-encoder, with a citation-count "
       "prior as a tie-breaker and a per-document diversity cap so corpus-wide questions span many papers. Each "
       "chunk is embedded alongside its document title + section (deterministic ‘contextual retrieval’) so "
       "an isolated sentence stays findable. Generation drafts claims that must cite a retrieved chunk; the gate "
       "verifies each before it ships.")

question("How do you prevent hallucinations? Walk me through the verification gate.")
answer("Three layers per claim: (1) citation resolution — the cited chunk must exist; (2) verbatim quote "
       "exact-match — the drafting model must return a quote of ≥12 chars copied from the cited chunk, which "
       "pure-Python normalised matching checks (handles curly quotes, ligatures, PDF hyphenation); (3) NLI "
       "entailment — a local DeBERTa model confirms the claim is entailed by the chunk, catching "
       "quote-out-of-context. Failing claims are dropped, regenerated (≤2), or escalated to an explicit gap. "
       "The gate BLOCKS — it never just observes — which was the core fix versus my earlier design where it "
       "scored hallucinations and shipped them anyway.")

question("Why quote-match + NLI rather than just embedding similarity or a cross-encoder?")
answer("Embedding/cross-encoder similarity measures relatedness, not truth: ‘X improves Y’ and ‘X does "
       "not improve Y’ score nearly identically, so they can’t catch a negated or fabricated claim. Quote "
       "exact-match is a hard, cheap, deterministic guarantee a weak model can’t fake; NLI then validates the "
       "quote is used in-context. Together they give grounding that doesn’t depend on model quality — which "
       "is what makes free-tier LLMs trustworthy.")

question("How does the multi-agent pipeline work, and why LangGraph?")
answer("A LangGraph DAG: clarify → plan → research (parallel paper/code/blog agents via asyncio.gather) "
       "→ ingest → outline → draft+gate → assemble → graph. The key design is conditional edges: "
       "draft_sections loops back to plan when evidence is insufficient (bounded by replan budgets), and clarify "
       "routes to END if an intent guard rejects an off-topic query. I chose LangGraph for explicit state, "
       "checkpointable nodes (crash-resume), and first-class conditional/looping edges — versus a linear chain "
       "that can’t recover or re-plan. Every node checkpoints to Postgres and streams progress to the UI.")

question("How do you run this on free-tier LLMs without hitting limits?")
answer("A central router is the only entry point: per-step provider chains ordered by task complexity (fast models "
       "for classification, stronger for synthesis), Lua token-bucket throttles per provider honouring RPM limits, "
       "prompt-hash response caching so regens/replays are free, Gemini↔Groq↔DeepSeek↔OpenRouter "
       "failover on 429/outage with identical JSON schemas, a one-shot JSON repair retry, and a hard per-call "
       "timeout so a hang fails over instead of stalling. Unconfigured providers are skipped, so it degrades to "
       "whatever keys exist.")

question("How do you evaluate the system? What stops a regression?")
answer("A groundedness eval harness runs the real grounded-chat path over a frozen mini-corpus with known answers "
       "and enforces release gates: fabricated citations must equal 0 (one fails the build), claim-support rate "
       "≥98%, refusal correctness ≥95%. It exits non-zero on a breach, so it gates CI — I wired it as "
       "a scheduled GitHub Actions job. Plus per-stage metrics (retrieval recall, quote-match rate, gate outcomes) "
       "via Prometheus.")

question("Why separate papers from repos/blogs in the report?")
answer("Evidence laundering: if a peer-reviewed finding and a Medium post flow through the same synthesis, the "
       "output prose flattens them and the blog claim inherits credibility it never earned — destroying the "
       "provenance signal the reader needs. So it’s structural, not stylistic: retrieval takes a source-type "
       "filter, report sections carry an academic/technical track, the UI shows them in separate tabs, and chat "
       "answers claim only on scholarly evidence with practitioner hits listed separately.")

question("How does the standing monitor agent work?")
answer("Each project has watches seeded from its research sub-questions. A worker sweep (every ~6h) enqueues a "
       "monitor job that searches arXiv (recency-sorted) + Semantic Scholar, deduplicates against the corpus and "
       "prior alerts, scores candidates by embedding similarity to the watch (no LLM cost), and stores the "
       "relevant ones as alerts. One click ingests an alert into the corpus. It’s the proactive half — the "
       "corpus grows toward open questions without re-searching.")

question("How does the discovery Map work?")
answer("Nodes are corpus papers; edges are two real relationships — content similarity (cosine over a "
       "title+opening-chunk embedding, top-k neighbours above a threshold) and citation edges (Semantic Scholar "
       "references matched within the corpus). It’s papers-only by design, consistent with evidence-class "
       "separation. The result is cached in Redis (the citation fetch is slow), rendered as an interactive "
       "force-directed graph (pan/zoom/drag), and every node is actionable — ask it, open it, highlight "
       "neighbours — so it’s discovery, not decoration.")

# ───────────────────────── 3. System design ─────────────────────────
doc.add_page_break()
heading("3. System design & architecture")

question("Walk me through the architecture and the single most important design principle.")
answer("React/Vite UI → FastAPI (async) → Redis job queue → worker(s) running the LangGraph pipeline; "
       "Postgres is the system of record, Qdrant holds vectors, Redis is queue+cache. The one law: agents propose, "
       "deterministic verifiers dispose. LLMs operate only inside a bounded agent layer; the verification gate sits "
       "between them and the user and blocks. Everything else — storage custody, the eval gate, evidence-class "
       "separation — follows from keeping ungrounded output away from the user.")

question("Why is Postgres the source of truth and not the vector DB?")
answer("Custody rule: Postgres holds durable truth (text, claims, quotes, citations — kilobytes per paper, "
       "forever); Qdrant vectors and Redis state are rebuildable caches. This is also how a small box serves "
       "unbounded history — the external scholarly APIs are the global index, only the working set is embedded "
       "(a capped hot tier), and cold vectors rebuild on demand. Verified claims become a permanent, distilled "
       "knowledge base that costs almost nothing to store.")

question("How would you scale this to many concurrent users?")
answer("The worker already scales horizontally — job claim is an atomic Redis LMOVE, so N workers never "
       "double-process (docker compose --scale worker=N). I’d add: Postgres read replicas + connection pooling, "
       "a managed Qdrant cluster, partition the Redis queue, autoscale workers on queue depth, move embeddings/NLI "
       "to a dedicated inference service (or batch endpoint) behind the inference lock, and a CDN for the SPA. The "
       "free-tier LLM throttle becomes the real bottleneck, so production would move to paid endpoints with "
       "per-tenant rate budgets.")

question("How do you handle the worker queue and crash safety?")
answer("Jobs are claimed atomically (LMOVE main→processing), retried up to 3 times, then dead-lettered. I "
       "switched from blocking BLMOVE to a non-blocking poll after BLMOVE’s server-side block raced the client "
       "socket timeout and killed idle workers. Runs checkpoint per node; on startup the worker rebuilds the queue "
       "from non-terminal run rows (orphan recovery). A heartbeat logs queue depth so a dead worker is the clearest "
       "possible signal.")

# ───────────────────────── 4. Production / Observability / Security ─────────────────────────
doc.add_page_break()
heading("4. Production, observability & security")

question("What does your observability stack look like?")
answer("Prometheus metrics at /metrics for the things that matter to THIS system — gate outcomes "
       "(verified/failed-quote/failed-nli), LLM calls + tokens by provider/step, pipeline node timings, ingest "
       "counts. Structured JSON logs traced by request_id/run_id, a worker heartbeat, hard LLM-call timeouts, and "
       "live SSE progress to the UI. Optional Sentry (error tracking) and Langfuse (per-call LLM cost/latency/quality "
       "traces), both env-gated no-ops when unset.")

question("How is the system secured?")
answer("Supabase auth verified server-side via JWKS (RS256/ES256, no shared secret); per-IP rate limiting on the "
       "API (fail-open); security headers (X-Frame-Options DENY, nosniff, Referrer-Policy); and a prompt-injection "
       "screen — retrieved document text is treated as data and fenced, with imperative ‘ignore previous "
       "instructions’ patterns neutralised before entering the model context. The verification gate is the "
       "ultimate backstop: even a hijacked claim must quote-match and entail a real source.")

question("How did you set up CI/CD?")
answer("GitHub Actions: on every push, backend lint + unit tests and a frontend type-check + build. A separate "
       "manual/scheduled workflow spins up Postgres/Redis/Qdrant and runs the groundedness eval gate, failing on a "
       "release-gate breach. The app itself is containerised (one Dockerfile serves API and worker), with a compose "
       "profile to run the whole stack and scale workers.")

# ───────────────────────── 5. Product & decisions ─────────────────────────
doc.add_page_break()
heading("5. Product thinking & decisions")

question("Why did you build this? What problem does it solve?")
answer("AI research tools fabricate, and users learn to distrust them — so they re-verify everything and the "
       "time saving disappears. I validated this with ~55 real complaints where fabrication was the dominant theme. "
       "Veriscope solves the trust problem directly: it makes fabrication structurally impossible and refuses rather "
       "than guesses, so the output is usable without re-checking.")

question("What metric would define success for this product?")
answer("Not ‘papers found’ — that’s the wrong metric. The real one is time-from-question-to-"
       "confident-answer, with a trust proxy: the share of claims a user clicks through to verify (it should fall "
       "over time as trust builds). The north-star behaviour is unprompted repeat use — if adoption needs "
       "evangelism, you solved the wrong problem.")

question("What would you do differently, or what’s still missing?")
answer("Honestly: no live deployment yet, an interactive clarification pause could be deeper, the Map’s citation "
       "layer is bounded/cached rather than exhaustive, and there’s no real user research beyond public "
       "complaints (I was explicit about that limitation). I’d deploy a hosted demo, add comparison-table "
       "extraction (Elicit’s signature feature), and instrument product analytics to actually measure activation "
       "and retention.")

question("What was the biggest technical risk, and how did you de-risk it?")
answer("That the verification gate would reject so many claims the reports would be empty — grounding is "
       "worthless if nothing survives it. I de-risked with the quote-requirement design (a model CAN quote "
       "accurately if forced to), a regenerate-then-replan-then-gap fallback, and the eval harness measuring "
       "support rate. A real run produced 17 verified claims at ≥98% support, confirming the gate is strict "
       "but not strangling.")

# ───────────────────────── 6. Role-fit & reflection ─────────────────────────
doc.add_page_break()
heading("6. Role-fit & reflection")

question("Is this an AI Engineer or an ML Engineer project? Be honest.")
answer("Primarily AI / GenAI Engineer: LLM application architecture, multi-agent orchestration, RAG, a verification "
       "system, prompt design, LLM routing and evals. I used pre-trained models (embeddings, cross-encoder, NLI) "
       "rather than training or fine-tuning, so I wouldn’t call it ML Engineering — there’s no training "
       "pipeline or model registry. The product reasoning behind it is PM-grade, which I’d frame as a "
       "differentiator: I can ship a real AI system and articulate why it’s built that way.")

question("What did you learn from this project?")
answer("That for LLM systems, trust is an architecture decision, not a model decision — you engineer it with "
       "deterministic verification, not by hoping for a better model. I also learned how much of ‘AI "
       "engineering’ is actually systems engineering: crash-safe workers, idempotent jobs, observability, and "
       "concurrency bugs (the Torch segfault) decide whether the clever AI part ever runs reliably.")

question("If I gave you a week, what would you add next?")
answer("Deploy a hosted demo (highest leverage — lets anyone try it), wire the eval gate into CI as a hard gate, "
       "and add comparison-table extraction across papers. Then citation-weighted ranking everywhere and an "
       "interactive clarification pause, so the system feels collaborative like Elicit while staying grounded.")

# ───────────────────────── Cheat sheet ─────────────────────────
doc.add_page_break()
heading("7. Quick-reference cheat sheet (memorise these)")
facts = [
    "Thesis: research is a TRUST problem, not a retrieval problem.",
    "Verification gate = quote exact-match + NLI entailment + citation resolution (it BLOCKS, never observes).",
    "Guarantees: G1 every claim → source span; G2 zero fabricated citations; G3 closed corpus; G4 refusal over "
    "fabrication; G5 honest gaps.",
    "Hybrid RAG: BM25 + dense (Qdrant) + RRF fusion + cross-encoder rerank + contextual embeddings + citation prior "
    "+ per-doc diversity.",
    "Pipeline (LangGraph, 7 nodes): clarify → plan → research∥ → ingest → outline → "
    "draft+gate⇄replan → assemble.",
    "Free-tier router: 4 providers, token-bucket throttle, prompt-hash cache, failover, hard per-call timeout.",
    "Eval gates: fabricated citations = 0, claim support ≥ 98%, refusal correctness ≥ 95%.",
    "Stack: FastAPI · LangGraph · Postgres · Qdrant · Redis · PyMuPDF4LLM · React/TS.",
    "Key bug fixed: concurrent Torch inference segfault → single inference lock + bounded concurrency.",
    "Custody: Postgres = truth; Qdrant + Redis = rebuildable caches; tiered retention for small infra.",
    "Differentiators: verification gate, eval harness, monitor agent, citation+similarity Map, evidence-class "
    "separation.",
]
for f in facts:
    bullet(f)

para("")
foot = doc.add_paragraph()
foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
fr = foot.add_run("Tip: lead every technical answer with the WHY (the trust thesis), then the HOW. "
                  "Quantify. Stay in the first person.")
fr.italic = True
fr.font.color.rgb = GREY
fr.font.size = Pt(9.5)

import os
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Veriscope_Interview_Prep.docx")
doc.save(out)
print("SAVED", os.path.abspath(out))
