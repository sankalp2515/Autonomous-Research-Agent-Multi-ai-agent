"""The verification gate. Blocking, deterministic, free-tier compatible.

Three layers per claim (ARCHITECTURE.md §6):
1. citation resolution  - the cited chunk must exist in the corpus
2. quote exact-match    - verbatim quote must exist in that chunk
3. NLI entailment       - claim must be entailed by the chunk (catches
                          quote-out-of-context); contradiction always fails

The gate OBSERVES nothing - it DECIDES. Callers must branch on the result:
verified claims ship, failed claims regenerate or become explicit gaps.
"""

import re
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.observability import GATE_CLAIMS
from app.ml.local_models import (
    nli_available, nli_entailment, nli_entailment_batch,
)
from app.verification.quote_match import match_quote, QuoteMatch

logger = get_logger("gate")


@dataclass
class ClaimInput:
    text: str
    chunk_id: str
    quote: str


@dataclass
class EvidenceResult:
    chunk_id: str
    quote: str
    quote_match: QuoteMatch
    nli_label: str = "skipped"
    nli_score: float = 0.0


@dataclass
class GateResult:
    verified: bool
    # ok | missing_chunk | quote_mismatch | unsupported_entity | nli_contradiction | nli_weak
    reason: str
    evidence: EvidenceResult | None = None


# ── Over-specification guard ─────────────────────────────────────────────
# A claim can pass quote-match + NLI yet still name a SPECIFIC entity the
# source never mentions (the real-world case: a claim attributing "the EU AI
# Act mandates X" to a technical paper that only discusses "regulatory
# constraints" generically — quote matches a generic sentence, NLI scores it
# mild-neutral, and it slips through). We deterministically extract specific
# named references from the claim and require each to appear in the cited
# chunk. Case-insensitive, so merely Title-casing a concept the source states
# in lower case still passes — only genuinely-new specifics fail.

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’.&+/-]*")
# Words allowed *inside* a proper-noun run (and trimmed from its edges).
# Deliberately excludes "and"/"&": "EU and AI" is two references, not one name.
_RUN_CONNECTORS = {"of", "for", "the", "de"}
# Acronyms too generic to be worth requiring in the source.
_UBIQUITOUS_ACRONYMS = {
    "AI", "ML", "NLP", "LLM", "LLMS", "GPU", "CPU", "API", "IT", "US", "USA",
    "UK", "EU", "AGI", "RL", "OK", "URL", "HTTP", "PDF",
}


def _has_possessive(tok: str) -> bool:
    return tok.endswith("'s") or tok.endswith("’s")


def _strip_possessive(tok: str) -> str:
    return tok[:-2] if _has_possessive(tok) else tok


def _extract_entities(text: str) -> list[str]:
    """Specific named references worth checking: multi-word proper-noun phrases
    and standalone acronyms (>=3 chars, not ubiquitous). Possessives terminate
    a run so "IBM's AI Fairness 360" yields IBM and "AI Fairness", not a merged
    phantom. Single Title-case words (often just sentence starts) are ignored."""
    toks = [(_strip_possessive(t), _has_possessive(t)) for t in _WORD_RE.findall(text)]
    ents: list[str] = []
    i, n = 0, len(toks)
    while i < n:
        word, poss = toks[i]
        if not (word[:1].isupper()):
            i += 1
            continue
        run = [word]
        j = i + 1
        if not poss:  # a possessive ends the run right here
            while j < n:
                nxt, nxt_poss = toks[j]
                if nxt[:1].isupper():
                    run.append(nxt)
                    j += 1
                    if nxt_poss:
                        break
                elif nxt.lower() in _RUN_CONNECTORS and j + 1 < n and toks[j + 1][0][:1].isupper():
                    run.append(nxt)
                    j += 1
                else:
                    break
        while run and run[0].lower() in _RUN_CONNECTORS:
            run.pop(0)
        while run and run[-1].lower() in _RUN_CONNECTORS:
            run.pop()
        # A phrase is only "specific" if it has a substantive token — not just
        # ubiquitous acronyms/connectors (so "EU" or "US of A" aren't entities).
        substantive = any(
            t.lower() not in _RUN_CONNECTORS and not (t.isupper() and t in _UBIQUITOUS_ACRONYMS)
            for t in run
        )
        if len(run) >= 2 and substantive:
            ents.append(" ".join(run))
        elif len(run) == 1:
            w = run[0]
            if w.isupper() and w.isalpha() and len(w) >= 3 and w not in _UBIQUITOUS_ACRONYMS:
                ents.append(w)
        i = max(j, i + 1)
    return ents


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).lower()


def unsupported_entities(claim_text: str, chunk_text: str) -> list[str]:
    """Entities named in the claim but absent from the cited chunk (phrase or
    its acronym). Empty list => nothing over-specified."""
    chunk_norm = _norm(chunk_text)
    missing: list[str] = []
    seen: set[str] = set()
    for ent in _extract_entities(claim_text):
        if _norm(ent) in chunk_norm:
            continue
        acronym = "".join(w[0] for w in ent.split() if w[:1].isupper()).lower()
        if len(acronym) >= 2 and re.search(rf"\b{re.escape(acronym)}\b", chunk_norm):
            continue
        key = ent.lower()
        if key not in seen:
            seen.add(key)
            missing.append(ent)
    return missing


@dataclass
class GateReport:
    results: list[GateResult] = field(default_factory=list)

    @property
    def verified_count(self) -> int:
        return sum(1 for r in self.results if r.verified)

    @property
    def failed(self) -> list[int]:
        return [i for i, r in enumerate(self.results) if not r.verified]

    @property
    def support_rate(self) -> float:
        return self.verified_count / len(self.results) if self.results else 0.0


async def verify_claim(claim: ClaimInput, chunk_text: str | None) -> GateResult:
    settings = get_settings()

    # Layer 1: citation resolution.
    if chunk_text is None:
        GATE_CLAIMS.labels("failed_citation").inc()
        return GateResult(False, "missing_chunk")

    # Layer 2: verbatim quote.
    qm = match_quote(claim.quote, chunk_text, fuzzy_threshold=settings.quote_fuzzy_threshold)
    evidence = EvidenceResult(claim.chunk_id, claim.quote, qm)
    if not qm.ok:
        GATE_CLAIMS.labels("failed_quote").inc()
        logger.info("gate: quote mismatch",
                    extra={"chunk_id": claim.chunk_id, "score": round(qm.score, 3)})
        return GateResult(False, "quote_mismatch", evidence)

    # Layer 2.5: over-specification guard (deterministic).
    if settings.gate_entity_check_enabled:
        missing = unsupported_entities(claim.text, chunk_text)
        if missing:
            GATE_CLAIMS.labels("failed_entity").inc()
            logger.info("gate: unsupported entity",
                        extra={"chunk_id": claim.chunk_id, "entities": missing[:5]})
            return GateResult(False, "unsupported_entity", evidence)

    # Layer 3: entailment (quote context, not just quote presence).
    if nli_available():
        label, score = await nli_entailment(chunk_text, claim.text)
        evidence.nli_label, evidence.nli_score = label, score
        if label == "contradiction" and score >= settings.nli_contradiction_threshold:
            GATE_CLAIMS.labels("failed_nli").inc()
            logger.info("gate: contradiction",
                        extra={"chunk_id": claim.chunk_id, "score": round(score, 3)})
            return GateResult(False, "nli_contradiction", evidence)
        if label == "neutral" and score >= 0.85:
            # Strongly neutral = the chunk says nothing about this claim,
            # despite a matching quote. Out-of-context quoting; fail it.
            GATE_CLAIMS.labels("failed_nli").inc()
            return GateResult(False, "nli_weak", evidence)

    GATE_CLAIMS.labels("verified").inc()
    return GateResult(True, "ok", evidence)


def _apply_nli(evidence: EvidenceResult, label: str, score: float,
               contradiction_threshold: float) -> GateResult:
    """Layer-3 decision, shared by the single and batched paths so they can
    never diverge."""
    evidence.nli_label, evidence.nli_score = label, score
    if label == "contradiction" and score >= contradiction_threshold:
        GATE_CLAIMS.labels("failed_nli").inc()
        return GateResult(False, "nli_contradiction", evidence)
    if label == "neutral" and score >= 0.85:
        GATE_CLAIMS.labels("failed_nli").inc()
        return GateResult(False, "nli_weak", evidence)
    GATE_CLAIMS.labels("verified").inc()
    return GateResult(True, "ok", evidence)


async def verify_claims(
    claims: list[ClaimInput], chunk_lookup: dict[str, str]
) -> GateReport:
    """Batched gate: layers 1-2 (citation + quote) are cheap Python and run
    inline; every claim that survives them is scored by NLI in a SINGLE batched
    forward pass, instead of one serialized model call per claim. Decisions are
    identical to verify_claim — only the inference is coalesced."""
    settings = get_settings()
    report = GateReport()
    results: list[GateResult | None] = [None] * len(claims)
    nli_jobs: list[tuple[int, str, str, EvidenceResult]] = []

    for i, claim in enumerate(claims):
        chunk_text = chunk_lookup.get(claim.chunk_id)
        if chunk_text is None:  # layer 1
            GATE_CLAIMS.labels("failed_citation").inc()
            results[i] = GateResult(False, "missing_chunk")
            continue
        qm = match_quote(claim.quote, chunk_text,
                         fuzzy_threshold=settings.quote_fuzzy_threshold)  # layer 2
        evidence = EvidenceResult(claim.chunk_id, claim.quote, qm)
        if not qm.ok:
            GATE_CLAIMS.labels("failed_quote").inc()
            results[i] = GateResult(False, "quote_mismatch", evidence)
            continue
        if settings.gate_entity_check_enabled and unsupported_entities(claim.text, chunk_text):
            GATE_CLAIMS.labels("failed_entity").inc()
            results[i] = GateResult(False, "unsupported_entity", evidence)
            continue
        if nli_available():
            nli_jobs.append((i, chunk_text, claim.text, evidence))  # defer layer 3
        else:
            GATE_CLAIMS.labels("verified").inc()
            results[i] = GateResult(True, "ok", evidence)

    if nli_jobs:  # layer 3, batched
        scored = await nli_entailment_batch([(p, h) for _, p, h, _ in nli_jobs])
        for (i, _p, _h, evidence), (label, score) in zip(nli_jobs, scored):
            results[i] = _apply_nli(evidence, label, score,
                                    settings.nli_contradiction_threshold)

    report.results = [r for r in results if r is not None]
    logger.info(
        "gate report",
        extra={
            "claims": len(claims),
            "verified": report.verified_count,
            "support_rate": round(report.support_rate, 3),
        },
    )
    return report
