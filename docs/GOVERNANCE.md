# Veriscope — Governance, Compliance & Risk

> Honest self-assessment of how Veriscope handles the governance dimensions that
> matter for an autonomous, stochastic AI agent. Where a control is partial or
> absent, this document says so plainly and states what we would add first. A
> grounded "not yet, and here's the plan" is more useful than a checkbox.

Veriscope is a verification-gated research agent. It makes **stochastic
(non-deterministic) decisions** — LLM-routed planning, query expansion, drafting
and structuring — so it is squarely in scope for AI governance. The design
philosophy throughout is: **agents propose, deterministic verifiers dispose.**
The model's creativity is never trusted as authority; trust comes from the
non-stochastic gate around it.

---

## 1. Hallucination management — **strong (this is the product thesis)**

| Control | Status | How |
|---|---|---|
| 🎯 Grounding | ✅ Done | Every shown claim must quote-match a source span (normalized exact match) before it can ship. No span → no claim. (`app/verification/quote_match.py`) |
| 📚 Citation requirement | ✅ Done + resolved | References render only from resolved citation objects (corpus / CrossRef / OpenAlex / arXiv). A fabricated citation is structurally unrenderable. (`app/verification/citation_resolver.py`) |
| 📊 Confidence scoring | ✅ Done | Local NLI (DeBERTa-class) entailment score per claim; the UI colors each citation by support strength (strong vs moderate). |
| ✅ Multi-model validation | ⚠️ Partial | We run a multi-provider fallback chain, but we do **not** cross-check the *same* claim across two models and compare. The deterministic quote+NLI gate is the cross-check that actually matters; a second-model adjudication band is a known future add. |

**Why this is our strongest area:** truthfulness is enforced by layers that do
**not** depend on model quality (exact-match + entailment + citation resolution).
A weak free-tier model cannot fake a verbatim quote that survives exact matching,
so the gate makes the whole system trustworthy without a frontier model.

---

## 2. Security vulnerability management — **good**

| Control | Status | How |
|---|---|---|
| 🛡️ Strong system prompts | ✅ Done | Drafting system prompt fences all document text as data; intent guardrail + refusal-over-fabrication policy. |
| 🔍 Input validation | ✅ Done | Prompt-injection screen on every chunk (`_sanitize_chunk`), schema-validated JSON on every LLM step, intent guard rejects off-topic/unsafe asks before a run spends budget. |
| 📦 Sandboxing | ⚠️ Partial | The agent has **no destructive capability** — it cannot execute code, move money, or write outside its own datastores, so blast radius is small by construction. It is not formally OS-sandboxed. |
| 📊 Monitoring | ✅ Done | Prometheus `/metrics`, structured JSON logs keyed by `request_id`/`run_id`, worker heartbeat, optional Sentry. Every LLM call, provider, latency and outcome is logged. |

**Defense-in-depth note:** even if a prompt injection slipped past the screen,
a hijacked claim still has to quote-match and entail a *real* source to ship —
the verification gate is the ultimate backstop, not the prompt.

---

## 3. Governance framework — **partial (audit & transparency strong; accountability & escalation thin)**

| Control | Status | How / Gap |
|---|---|---|
| 👤 Accountability structure | ⚠️ Gap | Auth records *who* ran *what* (Supabase identity per run), but there is no formal "human accountable for agent decisions" policy. Acceptable for a single-owner tool; would need definition for org deployment. |
| 📊 Audit trails | ✅ Done | Every run, claim, piece of evidence, quote-match offset and NLI score is persisted in Postgres — the report is fully reconstructable and inspectable after the fact. |
| 📈 Performance metrics | ⚠️ Partial | Eval harness tracks fabricated-citation count, claim-support rate, refusal correctness; Prometheus tracks latency/throughput. **No user-satisfaction signal** is collected yet. |
| 🚨 Escalation procedures | ⚠️ Partial | Failure modes are handled (budget-kill with partial results + explicit gaps, crash recovery, refusal). There is no defined "agent failed → route to a human reviewer" workflow. |

---

## 4. Compliance — **weak / mostly undefined (deliberately deferred)**

| Control | Status | Honest note |
|---|---|---|
| 🔒 Data privacy | ⚠️ Weak | No formal retention policy or PII-handling doc. Risk is inherently low (corpus is public papers/repos/blogs), but it is undefined. |
| 📋 Industry standards | ⛔ N/A | No sector-specific compliance addressed — there is no production deployment to certify. |
| ⚖️ Ethical guidelines / bias | ⛔ Gap | No bias detection on source selection or synthesis. A real gap: retrieval and reranking could systematically favor highly-cited or English-language work. |
| 🔍 Transparency / explainability | ✅ Strong | Every claim is traceable to an exact quote + entailment score + resolved citation. This is arguably the best governance property of the system. |

**Why deferred, not ignored:** these are the controls that matter once there is a
real deployment with real users and real data obligations. Building them before
that point would be governance theater. They are listed here so the absence is a
*decision*, not an oversight.

---

## What we would add first (priority order)

1. **Bias/fairness audit on retrieval** — measure and report citation-count and
   language skew in selected sources; surface it in the report's confidence panel.
2. **Escalation / human-review hook** — a defined path for low-confidence or
   high-stakes outputs to be flagged for a human instead of silently shipped as a gap.
3. **Data-retention & privacy policy** — explicit TTLs, deletion guarantees,
   and a documented PII posture (even if "we ingest only public sources").
4. **Second-model adjudication band** — cross-check claims that fall in the NLI
   borderline zone against a second provider before accepting or rejecting.
5. **User-satisfaction telemetry** — close the loop between "verified" and "useful."

---

## Design laws this all rests on

1. Agents propose, deterministic verifiers dispose. LLMs never have final authority.
2. Verification **gates**; it never merely observes. Failing claims are stripped,
   regenerated, or surfaced as explicit gaps — enforced by graph topology.
3. Fail **open** on observability (tracing/metrics/auth-optional features never
   break a request); fail **closed** on trust (verification is never skipped silently).
4. Refusal over fabrication. "Your corpus does not cover this" is a valid, good answer.

See [ARCHITECTURE.md](ARCHITECTURE.md) §2 (Design laws) and §6 (Verification gate)
for the mechanisms these controls are built on.
