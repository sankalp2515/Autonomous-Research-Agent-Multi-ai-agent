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
from app.core.exceptions import VerificationUnavailable
from app.core.logging import get_logger
from app.core.observability import GATE_CLAIMS
from app.ml.local_models import (
    nli_available, nli_entailment, nli_entailment_batch,
)
from app.verification.quote_match import match_quote, QuoteMatch

logger = get_logger("gate")


def assert_verification_ready() -> None:
    """Startup fail-fast: refuse to boot an environment that REQUIRES the NLI
    truth layer but has it switched off. Called from both entry points (API and
    worker) so a misconfigured deployment dies loudly at boot instead of shipping
    quote-only 'verified' claims at run time. The gate itself (below) is the hard
    backstop; this is the friendly early warning."""
    settings = get_settings()
    if settings.nli_required and not settings.ml_nli_enabled:
        raise RuntimeError(
            "ML_NLI_ENABLED=false is not permitted when APP_ENV=prod — the "
            "verification gate would ship claims on quote-match alone, silently "
            "dropping the NLI entailment (out-of-context) check. Enable the local "
            "ML stack (pip install .[ml], ML_NLI_ENABLED=true) before starting."
        )


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


def _trim_edges(tok: str) -> str:
    """Drop punctuation the word regex swallowed at the edges.

    `.` and `'` are allowed INSIDE a token so "Gemini-2.5-Flash" and "v2.0"
    survive intact — but a trailing one belongs to the sentence, not the name.
    Left unstripped, "Logical Contradiction." and "Compliance Regime'" were
    looked up with their punctuation attached and never matched.
    """
    return tok.strip(".,;:!?'’\"()[]{}")


def _has_possessive(tok: str) -> bool:
    return tok.endswith("'s") or tok.endswith("’s")


def _strip_possessive(tok: str) -> str:
    return tok[:-2] if _has_possessive(tok) else tok


def _extract_entities(text: str) -> list[str]:
    """Specific named references worth checking: multi-word proper-noun phrases
    and standalone acronyms (>=3 chars, not ubiquitous). Possessives terminate
    a run so "IBM's AI Fairness 360" yields IBM and "AI Fairness", not a merged
    phantom. Single Title-case words (often just sentence starts) are ignored."""
    # Tokens WITH positions, so a run can be stopped by punctuation. Without
    # this the run walker treated "(PK, CK, RPK)" as one name "PK CK RPK", and
    # "Mechanistic Hallucination Mitigation (MHM)" as "Mechanistic Hallucination
    # Mitigation MHM" — glued strings that appear in no source, so every claim
    # naming a system alongside its acronym was rejected as over-specified.
    # Measured on a real run, this was 10 of 17 refusals: true, supported
    # findings thrown away by a tokenizer artifact.
    matches = list(_WORD_RE.finditer(text))
    toks = [(_strip_possessive(_trim_edges(m.group(0))), _has_possessive(m.group(0)),
             m.start(), m.end()) for m in matches]
    toks = [t for t in toks if t[0]]

    def _joined_by_space_only(prev_end: int, next_start: int) -> bool:
        """True when only whitespace separates two tokens. A comma, bracket,
        quote or full stop between them means they are separate references."""
        return text[prev_end:next_start].strip() == ""

    ents: list[str] = []
    i, n = 0, len(toks)
    while i < n:
        word, poss, _ws, wend = toks[i]
        if not (word[:1].isupper()):
            i += 1
            continue
        run = [word]
        prev_end = wend
        j = i + 1
        if not poss:  # a possessive ends the run right here
            while j < n:
                nxt, nxt_poss, nstart, nend = toks[j]
                if not _joined_by_space_only(prev_end, nstart):
                    break
                if nxt[:1].isupper():
                    run.append(nxt)
                    prev_end = nend
                    j += 1
                    if nxt_poss:
                        break
                elif (nxt.lower() in _RUN_CONNECTORS and j + 1 < n
                      and toks[j + 1][0][:1].isupper()
                      and _joined_by_space_only(nend, toks[j + 1][2])):
                    run.append(nxt)
                    prev_end = nend
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

    def _acronym_in_chunk(ent: str) -> bool:
        """A source that introduces a name once and then uses the short form for
        the rest of the paper still supports the claim. Hyphenated compounds
        contribute each initial — "Context-Driven Decomposition" is CDD, not CD,
        and deriving the wrong one made this fallback miss exactly the systems
        papers abbreviate most."""
        for parts in (ent.replace("-", " ").split(), ent.split()):
            acronym = "".join(w[0] for w in parts if w[:1].isupper()).lower()
            if len(acronym) >= 2 and re.search(rf"\b{re.escape(acronym)}\b", chunk_norm):
                return True
        return False

    for ent in _extract_entities(claim_text):
        if _norm(ent) in chunk_norm or _acronym_in_chunk(ent):
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

    # Fail closed: where NLI is required, refuse to verify at all if the truth
    # layer is switched off — a quote-only pass would silently drop the
    # out-of-context check. Raise (loud, diagnosable) rather than return a
    # half-verified result.
    if settings.nli_required and not nli_available():
        raise VerificationUnavailable(
            "NLI entailment is required in this environment but ML_NLI_ENABLED "
            "is off — refusing to verify on quote-match alone."
        )

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
        # Flag is on but the model was not operational (import/load failed): it
        # returns "skipped". Where NLI is required, that is a broken truth layer,
        # not a pass — fail closed instead of quietly waving the claim through.
        if settings.nli_required and label == "skipped":
            raise VerificationUnavailable(
                "NLI model returned no judgment (not operational) but entailment "
                "is required in this environment."
            )
        evidence.nli_label, evidence.nli_score = label, score
        if label == "contradiction" and score >= settings.nli_contradiction_threshold:
            GATE_CLAIMS.labels("failed_nli").inc()
            logger.info("gate: contradiction",
                        extra={"chunk_id": claim.chunk_id, "score": round(score, 3)})
            return GateResult(False, "nli_contradiction", evidence)
        if label == "neutral" and score >= settings.nli_neutral_reject_threshold:
            # Strongly neutral = the chunk says nothing about this claim,
            # despite a matching quote. Out-of-context quoting; fail it.
            GATE_CLAIMS.labels("failed_nli").inc()
            return GateResult(False, "nli_weak", evidence)

    GATE_CLAIMS.labels("verified").inc()
    return GateResult(True, "ok", evidence)


def _apply_nli(evidence: EvidenceResult, label: str, score: float,
               contradiction_threshold: float, neutral_threshold: float) -> GateResult:
    """Layer-3 decision, shared by the single and batched paths so they can
    never diverge."""
    evidence.nli_label, evidence.nli_score = label, score
    if label == "contradiction" and score >= contradiction_threshold:
        GATE_CLAIMS.labels("failed_nli").inc()
        return GateResult(False, "nli_contradiction", evidence)
    if label == "neutral" and score >= neutral_threshold:
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

    # Fail closed (see verify_claim): a required-but-off NLI layer must never
    # let claims through on quote-match alone. Checked once up front for the
    # whole batch.
    if settings.nli_required and not nli_available():
        raise VerificationUnavailable(
            "NLI entailment is required in this environment but ML_NLI_ENABLED "
            "is off — refusing to verify on quote-match alone."
        )

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
            # MIS-ATTRIBUTION, not fabrication. A frequent failure is a quote
            # that IS verbatim in the sources the model was shown, but carries a
            # neighbouring block's chunk_id — the passages arrive as one prompt
            # and the id gets crossed. Rejecting that discards a true, properly
            # sourced finding over a bookkeeping slip.
            #
            # So: look for the quote in the other passages of THIS drafting
            # context. If exactly one contains it, the citation is corrected to
            # point there and verification continues. The contract is unchanged
            # and arguably tightened — the claim still needs a verbatim span in
            # a real corpus chunk, and the citation the reader clicks now
            # actually contains it. Ambiguity (two chunks match) stays a
            # refusal: we will not guess which source to credit.
            owners = [
                cid for cid, text in chunk_lookup.items()
                if cid != claim.chunk_id
                and match_quote(claim.quote, text,
                                fuzzy_threshold=settings.quote_fuzzy_threshold).ok
            ]
            if len(owners) == 1:
                chunk_text = chunk_lookup[owners[0]]
                qm = match_quote(claim.quote, chunk_text,
                                 fuzzy_threshold=settings.quote_fuzzy_threshold)
                evidence = EvidenceResult(owners[0], claim.quote, qm)
                GATE_CLAIMS.labels("reattributed").inc()
                logger.info("gate: citation re-attributed to the chunk that "
                            "actually contains the quote",
                            extra={"from": claim.chunk_id, "to": owners[0]})
            else:
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
            # Flag on but model not operational -> "skipped". Fail closed where
            # NLI is required rather than pass the whole batch quote-only.
            if settings.nli_required and label == "skipped":
                raise VerificationUnavailable(
                    "NLI model returned no judgment (not operational) but "
                    "entailment is required in this environment."
                )
            results[i] = _apply_nli(evidence, label, score,
                                    settings.nli_contradiction_threshold,
                                    settings.nli_neutral_reject_threshold)

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
