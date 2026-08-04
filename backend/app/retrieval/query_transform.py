"""Stage 2 of the RAG pipeline: query transformation.

Three techniques, one LLM call (free-tier discipline):

  rewriting   - restate the question in the vocabulary a paper would use
                ("how does X work?" -> "mechanism and implementation of X")
  expansion   - alternative phrasings so retrieval isn't hostage to one wording
  HyDE        - a hypothetical ANSWER passage, embedded instead of the question.
                Questions and answers occupy different regions of embedding
                space; matching answer-shaped text against answer-shaped chunks
                measurably improves dense recall.

The hypothetical document is NEVER shown to a user and never becomes evidence -
it only steers retrieval. Everything it surfaces still has to survive the
verification gate, so a wrong hypothesis costs recall, never correctness.

Fail-open by design: if the transform call fails, retrieval proceeds with the
original query rather than erroring.
"""

from dataclasses import dataclass, field

from app.core.logging import get_logger

logger = get_logger("retrieval.transform")


@dataclass
class TransformedQuery:
    original: str
    rewritten: str = ""
    expansions: list[str] = field(default_factory=list)
    hypothetical: str = ""

    @property
    def variants(self) -> list[str]:
        """All lexical forms to search with, deduped, original first."""
        out: list[str] = []
        for q in [self.original, self.rewritten, *self.expansions]:
            q = (q or "").strip()
            if q and q.lower() not in {o.lower() for o in out}:
                out.append(q)
        return out


async def transform_query(question: str, *, domain: str = "") -> TransformedQuery:
    """Rewrite + expand + HyDE in one call. Never raises."""
    plain = TransformedQuery(original=question)
    if len(question.strip()) < 8:
        return plain
    try:
        from app.agents.schemas import QueryTransform
        from app.llm.router import complete_json

        result = await complete_json(
            "query_transform",
            f"Research question: {question}\n"
            + (f"Domain: {domain}\n" if domain else "")
            + "Produce a retrieval-optimized rewrite, 2-3 alternative phrasings "
            "using different terminology, and a short hypothetical answer "
            "passage written the way a paper would state it.",
            QueryTransform,
        )
        out = TransformedQuery(
            original=question,
            rewritten=result.rewritten or "",
            expansions=[e for e in result.expansions if e and e.strip()][:3],
            hypothetical=result.hypothetical or "",
        )
        logger.info("query transformed", extra={
            "variants": len(out.variants), "hyde": bool(out.hypothetical)})
        return out
    except Exception as exc:
        # Retrieval quality degrades to baseline; it never breaks.
        logger.info("query transform skipped", extra={"error": str(exc)[:160]})
        return plain
