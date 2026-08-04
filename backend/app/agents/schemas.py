"""Pydantic schemas for every LLM step. Identical on both providers;
the router validates against these and rejects anything malformed.

Prompt-injection defense note: document text reaches models only inside
fenced SOURCE blocks, and model outputs are constrained to these schemas -
imperative text inside a PDF has no schema field through which to act.
"""

from pydantic import BaseModel, Field


class Clarification(BaseModel):
    domain: str = Field(description="research domain, e.g. 'machine learning'")
    objective: str = Field(description="what the user actually wants to learn")
    sub_questions: list[str] = Field(min_length=1, max_length=6)


class SourceQueries(BaseModel):
    arxiv: list[str] = Field(default_factory=list, max_length=4)
    semantic_scholar: list[str] = Field(default_factory=list, max_length=4)
    github: list[str] = Field(default_factory=list, max_length=3)
    blogs: list[str] = Field(default_factory=list, max_length=3)


class Plan(BaseModel):
    queries: SourceQueries
    rationale: str = ""


class ScreenedPaper(BaseModel):
    index: int
    relevant: bool
    reason: str = Field(description="one-sentence visible reasoning")
    score: float = Field(ge=0, le=1)


class ScreeningResult(BaseModel):
    papers: list[ScreenedPaper]


class OutlineSection(BaseModel):
    heading: str
    sub_question: str = Field(description="which sub-question this section answers")
    guidance: str = ""


class Outline(BaseModel):
    title: str
    sections: list[OutlineSection] = Field(min_length=1, max_length=8)


class DraftClaim(BaseModel):
    text: str = Field(description="one factual claim, a single sentence")
    chunk_id: str = Field(description="id of the SOURCE block supporting it")
    quote: str = Field(
        description="VERBATIM quote (>=12 chars) copied exactly from that SOURCE block"
    )


class SectionDraft(BaseModel):
    claims: list[DraftClaim] = Field(default_factory=list, max_length=12)
    insufficient_evidence: bool = Field(
        default=False,
        description="true if the provided sources cannot support this section",
    )
    gap_note: str = ""


class IntentCheck(BaseModel):
    allowed: bool = Field(description="true for research/information questions; false only for unsafe or clearly off-topic chit-chat")
    reason: str = ""


class ClarifyResult(BaseModel):
    domain: str = ""
    objective: str = ""
    questions: list[str] = Field(default_factory=list, max_length=3,
                                 description="1-3 short questions whose answers would sharpen the research")


class ChatAnswer(BaseModel):
    claims: list[DraftClaim] = Field(default_factory=list, max_length=10)
    refuse: bool = Field(default=False,
                         description="true if the corpus does not cover the question")
    refusal_reason: str = ""


# ── Adaptive presentation (Elicit-style) ─────────────────────────────────
# A section's verified claims can be reorganized into a comparison table when
# they compare several entities along shared attributes. This is a pure
# REORGANIZATION of already-verified claims (by index), never new prose — so
# every table cell remains gate-verified and click-to-source.

class TableRow(BaseModel):
    label: str = Field(description="the entity this row compares, e.g. a method or model name")
    cells: dict[str, list[int]] = Field(
        default_factory=dict,
        description="column header -> indices of the verified findings that belong in that cell",
    )


class SectionPresentation(BaseModel):
    kind: str = Field(
        description="'table' ONLY if the findings compare 3+ distinct entities "
        "across shared attributes; otherwise 'prose'"
    )
    columns: list[str] = Field(
        default_factory=list, max_length=4,
        description="attribute column headers, e.g. ['What it is','Why it helps','Limitation']",
    )
    rows: list[TableRow] = Field(default_factory=list, max_length=8)


class QueryTransform(BaseModel):
    """Stage-2 query transformation, produced in a SINGLE call (three separate
    calls would triple free-tier spend for the same information)."""
    rewritten: str = Field(
        description="the question rewritten as a precise, self-contained "
        "retrieval query using the terminology a paper would use"
    )
    expansions: list[str] = Field(
        default_factory=list, max_length=3,
        description="2-3 alternative phrasings using synonyms/related terms, "
        "each a standalone query covering a different angle",
    )
    hypothetical: str = Field(
        default="",
        description="HyDE: a short, plausible ANSWER passage (2-4 sentences) as "
        "it might appear in a paper. Never presented to the user - embedded "
        "only, so retrieval matches answer-shaped text instead of question-shaped text.",
    )


class NextQuestions(BaseModel):
    questions: list[str] = Field(
        default_factory=list, max_length=4,
        description="2-4 specific, distinct follow-up research questions a "
        "researcher would naturally pursue next",
    )
