"""How a follow-up becomes something the corpus can be searched with.

Two jobs, both cheap, both deterministic-first.

**RESOLVE.** A follow-up is not a query. "Why?", "what about latency?", "compare
those two" carry their subject in the conversation, not in the words - hand them
straight to a retriever and it searches the corpus for "why". So a short or
anaphoric turn is rewritten against the last few turns into a standalone
question. That rewrite steers RETRIEVAL ONLY: it is never shown, never quoted,
never persisted as a Claim. A wrong rewrite costs recall; it cannot cost
correctness, because everything it surfaces still faces the same gate.

**ROUTE.** Not every question is a question about the LITERATURE. "What is this
report about" is a question about VERISCOPE, and sending it to corpus retrieval
is a category error whose only possible outcome is a refusal - which is exactly
what shipped. Those questions are answered from artifacts the run already
computed (see `ask_workspace`), by template, with no LLM in the assertion path.

The router is REGEX, not a model, and deliberately conservative: it fires only
on an explicit reference to the workspace's own objects ("the report", "my
corpus", "how many papers"). Mis-routing a real literature question to the
workspace answerer would replace a grounded answer with a fact about our
bookkeeping, so ambiguity resolves to CORPUS every time.
"""

import re

from app.core.logging import get_logger

logger = get_logger("ask.intent")

ROUTE_CORPUS = "corpus"
ROUTE_WORKSPACE = "workspace"

# Workspace topics. Each is a fact about THIS PROJECT that some node already
# computed; none of them is a fact about the world, so none needs a quote.
TOPIC_OVERVIEW = "overview"    # what the report is / was about
TOPIC_FINDINGS = "findings"    # what it concluded, as D statements
TOPIC_CORPUS = "corpus"        # which papers, how many
TOPIC_GAPS = "gaps"            # where the evidence ran out
TOPIC_METHODS = "methods"      # the funnel: found -> screened -> cited

# An explicit possessive/demonstrative reference to one of our own objects.
# "the report" qualifies; a bare "report" does not - papers report things.
_OURS = r"(?:this|the|that|your|my|our)\s+"
_ARTIFACT = r"(?:report|review|analysis|run|research)"
_CORPUS_NOUN = r"(?:papers?|sources?|studies|documents?|corpus|library|workspace|project)"

_RULES: list[tuple[str, str]] = [
    # --- overview -------------------------------------------------------
    (TOPIC_OVERVIEW, r"what(?:'s| is| was)?\s+" + _OURS + _ARTIFACT + r"\s+(?:about|on)\b"),
    (TOPIC_OVERVIEW, r"what\s+(?:is|was)\s+" + _OURS + _CORPUS_NOUN + r"\s+about\b"),
    (TOPIC_OVERVIEW, r"(?:summari[sz]e|recap|overview of)\s+(?:" + _OURS + r")?" + _ARTIFACT + r"\b"),
    (TOPIC_OVERVIEW, r"what\s+(?:question|topic)\s+did\s+(?:you|we|this)\b"),
    (TOPIC_OVERVIEW, r"what\s+(?:are\s+we|am\s+i|is\s+this)\s+(?:researching|looking\s+at|working\s+on)\b"),
    # --- findings -------------------------------------------------------
    (TOPIC_FINDINGS, r"what\s+did\s+(?:you|we|the\s+\w+)\s+(?:find|conclude|discover|learn)\b"),
    (TOPIC_FINDINGS, r"what\s+(?:were|are)\s+" + _OURS
     + r"(?:key\s+|main\s+|top\s+)?(?:findings?|conclusions?|results?|takeaways?)\b"),
    (TOPIC_FINDINGS, r"what\s+does\s+" + _OURS + _ARTIFACT + r"\s+(?:say|conclude|show|find)\b"),
    # --- corpus ---------------------------------------------------------
    # ORDER MATTERS. "how many papers did you screen" is a question about the
    # funnel, not about the shelf, and the broad rule below would claim it
    # first - so the methods form is matched here, ahead of it.
    (TOPIC_METHODS, r"how\s+many\s+(?:papers?|studies|sources?)\s+"
                    r"(?:did|were|have)\b"),
    (TOPIC_CORPUS, r"how\s+many\s+" + _CORPUS_NOUN + r"\b"),
    (TOPIC_CORPUS, r"(?:which|what)\s+" + _CORPUS_NOUN + r"\s+(?:do\s+(?:i|we)|are|did|does|were)\b"),
    (TOPIC_CORPUS, r"(?:list|show|name)\s+(?:me\s+)?(?:" + _OURS + r")?" + _CORPUS_NOUN + r"\b"),
    (TOPIC_CORPUS, r"what(?:'s| is)\s+in\s+" + _OURS + _CORPUS_NOUN + r"\b"),
    # --- gaps -----------------------------------------------------------
    (TOPIC_GAPS, r"what\s+(?:are\s+the\s+)?(?:gaps?|open\s+questions?"
                 r"|limitations?\s+of\s+(?:this|the)\s+(?:report|review))\b"),
    (TOPIC_GAPS, r"what(?:'s| is|\s+was)\s+(?:missing|not\s+covered|unanswered)\b"),
    (TOPIC_GAPS, r"where\s+did\s+(?:the\s+)?evidence\s+(?:run\s+out|fall\s+short)\b"),
    # --- methods --------------------------------------------------------
    (TOPIC_METHODS, r"how\s+many\s+(?:papers?|studies)\s+did\s+(?:you|we)\s+(?:screen|find|search|look)\b"),
    (TOPIC_METHODS, r"how\s+did\s+(?:you|we)\s+(?:pick|choose|select|screen|find)\s+(?:the\s+)?(?:papers?|sources?|studies)\b"),
    (TOPIC_METHODS, r"(?:why|how)\s+(?:were|was)\s+.{0,24}\bexcluded\b"),
    (TOPIC_METHODS, r"what\s+(?:was|is)\s+" + _OURS + r"(?:methodolog|method|process|funnel)"),
]

_COMPILED = [(topic, re.compile(pat, re.I)) for topic, pat in _RULES]


def route(question: str) -> tuple[str, str]:
    """(route, topic). Ambiguity always resolves to the corpus."""
    q = " ".join((question or "").split())
    for topic, rx in _COMPILED:
        if rx.search(q):
            logger.info("ask routed to workspace", extra={"topic": topic})
            return ROUTE_WORKSPACE, topic
    return ROUTE_CORPUS, ""


# -- Follow-up resolution --------------------------------------------------
#
# Rewriting costs an LLM call, so it runs only on turns that plainly cannot
# stand alone. A fully-formed question is left ALONE - rewriting a good question
# is a way to make it worse, and the user's own words are the best query we have.

# Openers that point at something already said rather than naming it.
_ANAPHORIC = re.compile(
    r"^\s*(?:and|but|so|then|also|what\s+about|how\s+about|why|why\s+not|how\s+so|"
    r"which\s+(?:one|ones)|compare\s+(?:those|these|them)|"
    r"(?:tell|say|explain)\s+(?:me\s+)?more|more\s+(?:on|about)|go\s+deeper|"
    r"expand|elaborate|continue|same\s+(?:for|question)|what\s+else|"
    r"(?:is|are|does|do|did|can|could|would|was|were)\s+(?:it|they|that|those|these|this)\b)",
    re.I,
)
# A bare pronoun anywhere, with no noun of its own to anchor it.
_BARE_PRONOUN = re.compile(r"\b(?:it|its|they|them|their|those|these|that|this|he|she)\b", re.I)


def needs_resolution(question: str, has_history: bool) -> bool:
    """True when the turn cannot be retrieved as written."""
    if not has_history:
        return False
    q = (question or "").strip()
    if not q:
        return False
    words = q.split()
    if len(words) <= 4:
        return True
    if _ANAPHORIC.match(q):
        return True
    # A short question leaning on a pronoun ("does it beat the baseline?").
    return len(words) <= 14 and bool(_BARE_PRONOUN.search(q))


_REWRITE_SYSTEM = (
    "You rewrite the LAST turn of a research conversation into a question that "
    "stands on its own, so it can be used as a search query.\n"
    "RULES:\n"
    "1. Resolve pronouns and ellipsis using the earlier turns.\n"
    "2. Add NOTHING the conversation does not already contain. Do not answer, "
    "do not speculate, do not introduce topics, systems or numbers.\n"
    "3. If the last turn already stands alone, copy it verbatim.\n"
    "4. Output one question, in the user's own vocabulary."
)


def _transcript(history: list[dict], limit: int = 4) -> str:
    lines: list[str] = []
    for turn in (history or [])[-limit:]:
        q = (turn.get("question") or "").strip()
        a = (turn.get("answer") or "").strip()
        if q:
            lines.append("User: " + q[:400])
        if a:
            lines.append("Assistant: " + a[:600])
    return "\n".join(lines)


async def resolve_followup(question: str, history: list[dict] | None) -> str:
    """The standalone form of `question`. Never raises; falls back to the raw
    turn, which is exactly today's behaviour."""
    if not needs_resolution(question, bool(history)):
        return question
    transcript = _transcript(history or [])
    if not transcript:
        return question
    try:
        from app.agents.schemas import StandaloneQuestion
        from app.llm.router import complete_json

        res = await complete_json(
            "chat_rewrite",
            "Conversation so far:\n" + transcript + "\n\nLast turn: " + question
            + "\n\nRewrite the last turn as a self-contained question.",
            StandaloneQuestion, system=_REWRITE_SYSTEM, temperature=0.0,
        )
        out = " ".join((res.question or "").split())
        # Guard against a rewrite that lost the question or ran away with it.
        if len(out) < 8 or len(out) > 400:
            return question
        logger.info("follow-up resolved", extra={"to": out[:60]})
        return out
    except Exception as exc:
        logger.info("follow-up resolution skipped", extra={"error": str(exc)[:160]})
        return question
