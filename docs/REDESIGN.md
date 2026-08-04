# Veriscope 2.0 — Redesign & Roadmap

Status: planning. Captures the system-design + user-flow redesign and the
phased backlog. Companion to [ARCHITECTURE.md](ARCHITECTURE.md) (current system)
and [GOVERNANCE.md](GOVERNANCE.md) (trust & security posture).

## Positioning

**The research-automation workspace that does the 30–40% grunt work *and*
proves every claim — built for the applied-ML & software-engineering
researchers Elicit under-serves.** Not "Elicit but verified" — a different job:
*find → screen → extract → verify → reproduce*, in one place.

- **Primary user:** applied-ML / SWE researchers (repos are first-class
  artifacts; reproducibility matters; papers alone ignore real-world constraints).
- **Secondary user:** academic researchers, served via domain-adaptive prompts.
- **Moat (validated in QA):** provenance. A citation opens the *exact quoted
  span* + an NLI entailment score, not the abstract Elicit shows.

## The core user flow — hybrid (Quick + Deep)

Two modes over **one project workspace** (corpus + screening + extractions +
report + notes + monitor + memory — one home for scattered research).

**Quick — "Find & Screen"** (default, interactive, Elicit-tempo):
1. Composer: question + source scope + **time window** (defaults to *newest
   prioritized*).
2. **Domain ask** → sets a domain rubric/system prompt (SWE→MSR/reproducibility,
   biomed→PICO, ML→benchmarks/ablations).
3. **Real clarification pause** — 1–3 targeted questions that block until
   answered or skipped.
4. **Instant screened table** streams in: Relevance · Authority · Recency ·
   Reproducibility columns + summary. Sort / filter.
5. **Steer**: filter, add **verified extraction columns** (each cell
   quote-checked), grounded chat, save to corpus.
6. **Compile → Verified Report** from the curated set.

**Deep — "Verified Report"** (thorough, hands-off): domain prompt →
clarification → the quality-critic retrieval loop → verified drafting → report.

## Agent system

Deterministic graph topology (budgets enforced, verification always runs) with
a **bounded quality-critic feedback loop** and **memory-driven adaptation** —
no LLM orchestrator, no online-learning in the control plane.

```
   memory (episodic/semantic/preference) ─┐  (recalled at planning time)
                                          ▼
 clarify(domain+pause) → plan → RETRIEVE ⇄ SCREEN ⇄ CRITIC ─┐
                                   ▲   refine queries (bounded) │
                                   └─────────────────────◄──────┘
                → verified DRAFT (gate) → assemble → report
```

- **Critic ⇄ retrieve/screen** loop attacks hallucination-from-bad-data.
- **Adaptation** = memory + feedback (learn low-quality venues, prior findings,
  preferences), not code edits.

## Data quality & recency (highest priority)

- **Recency prior** in ranking, **on by default** — newer work wins near-ties.
- **Time window** control; when unset, recency is prioritized. Every source
  shows its **year**, and the report shows the **time span it actually covers**
  — transparency, not a promise.
- **Authority prior** (citations/venue) so obscure 0-citation papers don't lead.
- **Reproducibility check** (planned): score whether a paper/repo documents data
  retrieval, scripts, environment, dataset — the MSR "33% no retrieval info"
  pain, and a feature Elicit lacks.

## Evidence classes by audience

Scholarly and practitioner sources are **never blended**. For the applied/SWE
user, repos/blogs are first-class practitioner + reproducibility artifacts; for
the academic user, papers-first with SLR/PICO framing. Same engine, different
surface.

## Phased backlog

**Phase 1 — Stabilize & Open-Source** *(no new infra)*
Recency ranking (default) + time-window control + per-source year & span
(transparency) · real clarification pause · hide dev-metrics / researcher-facing
node labels · remove redundant run box · memory recalled at planning + Memory
panel · `.env.example`, LICENSE, remove interview doc from repo, OSS scaffolding
· this doc.

**Phase 2 — The Interactive Workspace** *(the wedge; MVP needs no new infra)*
Quick "Find & Screen" mode + screened table · verified extraction columns ·
reproducibility check · quality-critic loop · domain-adaptive prompts ·
repos-first-class / evidence-by-audience · compile-from-curated · calm
progressive UI · full-text depth (start) · Alembic.

**Phase 3 — Scale to rival Elicit** *(needs infra + funding)*
Full-text ingestion at scale + authority-ranked index · model-server split ·
horizontal deploy (managed stores, read replicas, S3, TLS, supervision) ·
reproducibility bundle export · Zotero import · docs site · corpus scale.

## Honest limits

We won't beat Elicit on corpus size or full-text pipeline without funding.
Phase 1–2 compete on the **wedge** (verified, authority- & recency-ranked,
reproducibility-aware, SWE-first), which is defensible because Elicit
structurally chose abstract-grounding, relevance-only ranking, and papers-only.
