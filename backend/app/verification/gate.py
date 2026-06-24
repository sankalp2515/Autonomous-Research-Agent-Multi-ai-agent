"""The verification gate. Blocking, deterministic, free-tier compatible.

Three layers per claim (ARCHITECTURE.md §6):
1. citation resolution  - the cited chunk must exist in the corpus
2. quote exact-match    - verbatim quote must exist in that chunk
3. NLI entailment       - claim must be entailed by the chunk (catches
                          quote-out-of-context); contradiction always fails

The gate OBSERVES nothing - it DECIDES. Callers must branch on the result:
verified claims ship, failed claims regenerate or become explicit gaps.
"""

from dataclasses import dataclass, field

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.observability import GATE_CLAIMS
from app.ml.local_models import nli_available, nli_entailment
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
    reason: str  # ok | missing_chunk | quote_mismatch | nli_contradiction | nli_weak
    evidence: EvidenceResult | None = None


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


async def verify_claims(
    claims: list[ClaimInput], chunk_lookup: dict[str, str]
) -> GateReport:
    report = GateReport()
    for claim in claims:
        chunk_text = chunk_lookup.get(claim.chunk_id)
        report.results.append(await verify_claim(claim, chunk_text))
    logger.info(
        "gate report",
        extra={
            "claims": len(claims),
            "verified": report.verified_count,
            "support_rate": round(report.support_rate, 3),
        },
    )
    return report
