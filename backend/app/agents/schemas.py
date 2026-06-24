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
