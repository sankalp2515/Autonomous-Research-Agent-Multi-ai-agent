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
    # Constraints parsed from the natural-language request so they are actually
    # enforced (they were silently ignored before).
    since_year: int = Field(
        default=0,
        description="earliest publication year requested — 2022 from 'after 2022', "
        "2024 from a '2024-2026' range; 0 if none stated",
    )
    until_year: int = Field(
        default=0,
        description="latest publication year requested — 2026 from a '2024-2026' "
        "range, or 'before 2020' -> 2020; 0 if none stated (no upper bound)",
    )
    min_citations: int = Field(
        default=0,
        description="minimum citation count the user asked for, e.g. 50 from "
        "'at least 50 citations'; 0 if none stated",
    )
    # MVP scope guard: this platform searches arXiv + Semantic Scholar and is
    # aimed at COMPUTER-SCIENCE / ENGINEERING research. Flag out-of-scope asks
    # (biomedicine, neuroscience, psychology, social science, humanities, law,
    # medicine) so the user is told transparently instead of getting a hollow,
    # off-domain report.
    field: str = Field(
        default="",
        description="the academic field this question belongs to, e.g. "
        "'computer science', 'neuroscience', 'economics'",
    )
    in_scope: bool = Field(
        default=True,
        description="true if the question is answerable from arXiv + Semantic "
        "Scholar computer-science/engineering literature; false for biomedicine, "
        "neuroscience, psychology, social science, humanities, medicine, law",
    )


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
    # Which criterion the paper failed, so exclusions can be reported BY REASON
    # ("no baseline: 22, not a comparison: 12") instead of as one opaque
    # "screened out" count. A rejection whose cause is unnamed tells the reader
    # nothing about whether the corpus was well chosen.
    failed_criterion: str = Field(
        default="",
        description="when relevant=false, the NAME of the single screening "
        "criterion this paper most clearly fails, copied EXACTLY from the "
        "criteria list given to you. Empty when relevant=true.",
    )
    # ── the evidence profile (Phase 1b) ──────────────────────────────────
    # The screen already pays an LLM to read every abstract and used to throw
    # all of it away but a float. An abstract names the systems a paper
    # evaluates, the datasets it runs on and the metrics it reports — which is
    # exactly the vocabulary doc-scoped BM25 needs, and exactly the expectation
    # signal a later "this study does not report X" verdict lacks.
    #
    # This is a PRIOR, never evidence. It is never quoted, never cited and never
    # rendered; it only steers retrieval and audits our own coverage. Read only
    # off the title+abstract, so it is cheap and it may be wrong — every
    # downstream use must degrade safely when it is.
    likely_dimensions: list[str] = Field(
        default_factory=list, max_length=8,
        description="which of the listed comparison dimensions this paper's "
        "abstract suggests it REPORTS. Copy the dimension labels exactly. Empty "
        "if the abstract gives no signal — do not guess to fill the list.",
    )
    named_systems: list[str] = Field(
        default_factory=list, max_length=10,
        description="the systems/methods/models this paper evaluates, named as "
        "THIS paper names them (not as the research question names them)",
    )
    named_datasets: list[str] = Field(
        default_factory=list, max_length=10,
        description="benchmarks, datasets or corpora named in the abstract",
    )
    named_metrics: list[str] = Field(
        default_factory=list, max_length=10,
        description="metrics or measurement units named in the abstract, e.g. "
        "'F1', 'exact match', 'latency (s)', 'tokens per query'",
    )

    def profile(self) -> dict:
        """The retrieval-side view: vocabulary + expectation, no verdict."""
        return {
            "likely_dimensions": [d.strip() for d in self.likely_dimensions if d.strip()],
            "named_systems": [s.strip() for s in self.named_systems if s.strip()],
            "named_datasets": [d.strip() for d in self.named_datasets if d.strip()],
            "named_metrics": [m.strip() for m in self.named_metrics if m.strip()],
        }


class ScreeningResult(BaseModel):
    papers: list[ScreenedPaper]


class OutlineSection(BaseModel):
    heading: str
    sub_question: str = Field(
        description="the question THIS section answers for the reader. It need "
        "not be one of the original research sub-questions - merge, split or "
        "reframe them to fit the evidence that was actually found."
    )
    # Phase 2: what the section is FOR, chosen from the evidence rather than
    # from a fixed template. Free-form on purpose - a new question shape should
    # not require a code change to be expressible.
    section_type: str = Field(
        default="",
        description="the job this section does, e.g. 'bottom_line', "
        "'evidence_comparison', 'mechanism', 'tradeoff_analysis', "
        "'when_each_wins', 'timeline', 'limitations', 'open_questions'",
    )
    retrieval_brief: str = Field(
        default="",
        description="what to SEARCH the corpus for to fill this section - rich "
        "in the vocabulary the papers themselves use (system names, metrics, "
        "datasets). This is a retrieval query, not a question to the reader.",
    )
    guidance: str = ""


class Outline(BaseModel):
    title: str
    sections: list[OutlineSection] = Field(min_length=1, max_length=9)


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


class AbstractDraft(BaseModel):
    """Gated synthesis. The model writes a bottom-line verdict + a few synthesis
    sentences over the ALREADY-VERIFIED findings; every sentence is then re-run
    through the SAME quote+NLI gate (`verify_claims`) and dropped if it fails.
    So the abstract reads like flowing synthesis yet keeps the G1/G2 contract:
    nothing survives that isn't quote-matched and entailed by a real source."""
    verdict: DraftClaim = Field(
        description="ONE bottom-line sentence answering the objective directly "
        "(the reader's headline). Grounded in exactly one finding: cite its "
        "chunk_id and copy a verbatim quote from that finding's source."
    )
    sentences: list[DraftClaim] = Field(
        default_factory=list, max_length=8,
        description="2-6 synthesis sentences that connect the findings into a "
        "coherent answer — trends, the strongest quantitative results, "
        "conditions, and honest limits. Each cites one chunk_id with a verbatim "
        "quote. Keep each sentence close enough to its cited finding that the "
        "finding entails it (or it will be dropped by the gate).",
    )


class IntentCheck(BaseModel):
    allowed: bool = Field(description="true for research/information questions; false only for unsafe or clearly off-topic chit-chat")
    reason: str = ""


class ClarifyResult(BaseModel):
    domain: str = ""
    objective: str = ""
    # THE DEFAULT IS SILENCE. This field used to be described as "1-3 short
    # questions", which made zero unreachable: the model always produced at
    # least one, the UI paused on any non-empty list, and so EVERY run was
    # interrogated before it could start — including queries that already named
    # their systems, metrics and time window. Asking a researcher to refine a
    # question they have already stated precisely is friction that teaches them
    # the system is not listening.
    questions: list[str] = Field(
        default_factory=list, max_length=3,
        description="LEAVE EMPTY unless the request is genuinely ambiguous. Only "
        "ask when two materially DIFFERENT research projects would satisfy the "
        "same words and you cannot choose between them — never to gather nice-to-"
        "have preferences, and never to confirm something the request already "
        "states. At most 3, each answerable in a few words.",
    )
    ambiguity: str = Field(
        default="specific",
        description="'specific' = one clear reading, run it as asked; "
        "'underspecified' = answerable as written but a preference would sharpen "
        "it (still run, questions optional); 'ambiguous' = two or more materially "
        "different interpretations, asking is warranted",
    )
    # Surfaced to the user BEFORE the run so constraints + scope are visible up
    # front (chips + an honest scope notice), never discovered after a wasted run.
    field: str = Field(default="", description="academic field of the question")
    in_scope: bool = Field(
        default=True,
        description="true if answerable from arXiv + Semantic Scholar CS/engineering "
        "literature; false for biomedicine, neuroscience, psychology, social science, "
        "humanities, medicine, law",
    )
    since_year: int = Field(default=0, description="earliest year requested (2024 from '2024-2026'); 0 if none")
    until_year: int = Field(default=0, description="latest year requested (2026 from '2024-2026'); 0 if none")
    min_citations: int = Field(default=0, description="minimum citations requested, e.g. 50; 0 if none")


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


class SubTheme(BaseModel):
    heading: str = Field(
        description="a short thematic sub-header (2-5 words) grouping several findings"
    )
    findings: list[int] = Field(
        default_factory=list,
        description="indices of the verified findings that belong under this sub-header",
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
    subthemes: list[SubTheme] = Field(
        default_factory=list, max_length=4,
        description="When kind='prose' AND the findings span 2-4 distinct "
        "sub-topics, group them under short sub-headers (each finding index "
        "used at most once). This is a pure reorganization of verified findings "
        "into '###' sub-sections — never new prose. Leave empty for a single "
        "flat prose block.",
    )


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
    subquestions: list[str] = Field(
        default_factory=list, max_length=4,
        description="If the question is COMPOUND or comparative (asks about two "
        "or more things, a mechanism AND its trade-offs, or X versus Y), "
        "decompose it into 2-4 atomic sub-questions each retrievable on its own. "
        "For a simple single-fact question, return an empty list — do not invent "
        "sub-questions where there is only one.",
    )


class NextQuestions(BaseModel):
    questions: list[str] = Field(
        default_factory=list, max_length=4,
        description="2-4 specific, distinct follow-up research questions a "
        "researcher would naturally pursue next",
    )


# ── Phase 1: the evidence matrix ─────────────────────────────────────────
# The unit of analysis in a literature review is the STUDY, not the chunk. The
# chunk-level claim gate (DraftClaim) proves a sentence is grounded, but it can
# never express "5 of 10 studies report X", nor fill a study x dimension grid —
# the two things that make Elicit's output read as research rather than as a
# list of quotes. These schemas add a per-paper extraction pass whose every
# field is still quote-grounded, so the grounding contract is EXTENDED, not
# relaxed: each finding carries its own chunk_id + verbatim quote and is run
# through the same verify_claims gate before it can enter the matrix.

class EvidenceContext(BaseModel):
    """Qualifiers a quantitative result needs before it can be compared."""
    dataset: str = Field(default="", description="evaluation dataset/benchmark, e.g. 'HotpotQA'")
    task: str = Field(default="", description="the task, e.g. 'multi-hop QA'")
    baseline: str = Field(default="", description="what it was measured AGAINST, e.g. 'Vector RAG'")
    model: str = Field(default="", description="the backbone model, e.g. 'GPT-4o'")
    condition: str = Field(
        default="",
        description="the experimental condition that qualifies it, e.g. "
        "'top_k=10', 'zero-shot', '20 few-shot examples', 'A100 GPU'",
    )


class StudyFinding(BaseModel):
    """One extracted result from one paper, grounded like any other claim."""
    dimension: str = Field(
        description="which comparison axis this answers — e.g. 'multi-hop "
        "accuracy', 'latency', 'token cost', 'simple-query performance', "
        "'limitation'. Reuse the SAME wording across papers when the axis is "
        "the same, so results line up into columns."
    )
    text: str = Field(description="the finding as one self-contained sentence")
    metric: str = Field(default="", description="metric name, e.g. 'F1', 'accuracy'")
    value: str = Field(
        default="",
        description="the headline number with its unit/direction, e.g. "
        "'+31.79%', '9.03s', '-13.4pp'; empty if the finding is qualitative",
    )
    chunk_id: str = Field(description="id of the SOURCE block supporting it")
    quote: str = Field(
        description="VERBATIM quote (>=12 chars) copied exactly from that SOURCE block"
    )
    # P1-E: the context that decides whether this number may be compared with
    # another study's. Without it, "89.2" and "89.2" look like corroboration
    # even when one is F1 on HotpotQA and the other Recall@10 on MuSiQue.
    context: "EvidenceContext" = Field(
        default_factory=lambda: EvidenceContext(),
        description="what this number was measured ON. Fill every field the "
        "paper states and leave the rest EMPTY — a guessed dataset is worse "
        "than an unqualified number, because it fabricates comparability.",
    )


class StudyRecord(BaseModel):
    """Structured extraction for a single paper — the row of the matrix."""
    frameworks: list[str] = Field(
        default_factory=list, max_length=12,
        description="systems/methods this paper EVALUATES, named as the paper "
        "names them (e.g. 'GraphRAG', 'LightRAG', 'HippoRAG2')",
    )
    baselines: list[str] = Field(
        default_factory=list, max_length=8,
        description="what they are compared AGAINST (e.g. 'NaiveRAG', 'BM25')",
    )
    datasets: list[str] = Field(
        default_factory=list, max_length=10,
        description="evaluation datasets/benchmarks (e.g. 'HotpotQA', 'MuSiQue')",
    )
    # Stays at 10. Raising it to 16 was tried alongside a "aim for 6-12 findings"
    # instruction and MEASURED on the calibration corpus: 92 verified findings
    # instead of 67, but fewer distinct comparison axes answered (37 vs 42 of
    # 180) and +27% wall time. The extra findings restated the axes the paper
    # leads with. Volume is not coverage; see _EXTRACT_SYSTEM rule 8.
    findings: list[StudyFinding] = Field(default_factory=list, max_length=10)
    no_relevant_content: bool = Field(
        default=False,
        description="true if this paper genuinely does not address the "
        "objective — refusal is preferred over inventing a row",
    )


class DimensionAlias(BaseModel):
    raw: str = Field(description="a dimension label exactly as extracted")
    canonical: str = Field(
        description="the shared axis it belongs to, chosen from the canonical "
        "list; copy the canonical label character-for-character"
    )


class DimensionMap(BaseModel):
    """Consolidates per-paper dimension labels into shared comparison axes.

    Extraction runs per paper, so papers invent near-duplicate labels for the
    same axis ('accuracy', 'accuracy improvement', 'multi-hop accuracy'). Left
    alone that produces a wide, mostly-empty grid — each study filling a column
    only it uses — which is precisely the half-empty comparison table this whole
    rework set out to eliminate. This pass ONLY renames labels: no claim text,
    quote, chunk_id or gate result is touched, so G1/G2 are untouched.
    """
    canonical: list[str] = Field(
        max_length=8,
        description="4-7 axes that between them cover the findings, named the "
        "way this literature names them (e.g. 'multi-hop accuracy', 'latency', "
        "'token cost', 'limitations')",
    )
    aliases: list[DimensionAlias] = Field(default_factory=list, max_length=60)


# ── P0-A: the question-specific evidence schema ──────────────────────────
# WHY. Extraction used to be steered by ONE generic string — the run objective —
# for every paper and every comparison axis at once. The model was asked "read
# this paper for `compare GraphRAG vs standard RAG`" and given whichever 8 chunks
# that one query happened to rank. Nothing in the system ever said "this question
# needs LATENCY, and latency is measured in ms/QPS and lives in the Efficiency
# section". So evidence the corpus demonstrably contained was never retrieved,
# and the resulting hole in the matrix rendered as if the STUDY had been silent.
#
# This schema is the missing declaration of what the question REQUIRES. It is
# generated once per run from the research question (never hardcoded — a new
# question shape must not need a code change), and it drives three things:
#   1. dimension-directed retrieval (synonyms + metrics + section hints),
#   2. the completeness audit (which cells are REQUIRED, hence auditable),
#   3. not_applicable classification (each dimension states when it doesn't apply).
#
# REPRODUCIBILITY. Reports must be comparable run to run, so generation is
# deterministic-by-construction: temperature 0, and `normalized()` lower-cases,
# de-duplicates and sorts every list so two semantically identical schemas are
# byte-identical.

class EvidenceDimension(BaseModel):
    """One comparison axis the question requires evidence on."""
    name: str = Field(
        description="the axis as this literature names it, lower-case, 1-4 "
        "words, e.g. 'retrieval latency', 'token usage', 'multi-hop accuracy'"
    )
    kind: str = Field(
        default="quantitative",
        description="'quantitative' if studies report it as a NUMBER (accuracy, "
        "latency, cost), 'qualitative' otherwise (limitations, design choices)",
    )
    description: str = Field(
        default="", description="one line: what a study must report to fill this axis"
    )
    synonyms: list[str] = Field(
        default_factory=list, max_length=12,
        description="terminology expansion — every phrasing a paper might use for "
        "this axis. For latency: 'response time', 'inference time', 'query time', "
        "'throughput', 'QPS', 'milliseconds', 'ms'. Be generous: this is the "
        "retrieval vocabulary, and a missing synonym is a missed finding.",
    )
    metrics: list[str] = Field(
        default_factory=list, max_length=8,
        description="unit/metric tokens that mark a real measurement, e.g. 'ms', "
        "'s', 'QPS', 'F1', 'EM', '%', 'tokens', 'USD', 'GB'",
    )
    location_hints: list[str] = Field(
        default_factory=list, max_length=8,
        description="paper SECTION names where this axis is usually reported, "
        "e.g. 'Results', 'Experiments', 'Efficiency Analysis', 'Cost Analysis', "
        "'Ablation', 'Limitations'",
    )
    not_applicable_when: str = Field(
        default="",
        description="when this axis genuinely does not apply to a study, e.g. "
        "'the paper is a survey with no system of its own' or 'the method builds "
        "no index'. Used to distinguish NOT APPLICABLE from NOT REPORTED.",
    )
    # PRINTED IN THE REPORT. A systematic review is reproducible only if the
    # reader can see the extraction instruction, not just the extracted value —
    # this is the field that makes the method inspectable rather than merely
    # audited. It is the same text the extractor is given, never a paraphrase
    # written for presentation.
    extraction_instruction: str = Field(
        default="",
        description="the reader-facing extraction instruction for this column, "
        "as an imperative sentence a human reviewer could follow, listing what "
        "must be collected. E.g. 'Extract all accuracy comparisons between the "
        "systems under study, including the metric used, the dataset, the "
        "numeric result for each arm, and any case where the baseline won.' "
        "This is PUBLISHED as the declared method, so describe what is actually "
        "collected — not why the axis matters.",
    )


class ScreeningCriterion(BaseModel):
    """One inclusion criterion, published verbatim as the review's protocol.

    Generated from the QUESTION (a new question shape must not need a code
    change) but used verbatim in the screening prompt, so what the reader sees
    is what the screen actually applied — not a description of it.
    """
    name: str = Field(
        description="short Title Case label, 2-3 words, e.g. 'Direct Comparison', "
        "'Quantitative Evidence', 'Controlled Setup'"
    )
    question: str = Field(
        description="the yes/no question asked of each candidate's title+abstract, "
        "written for a human reviewer and naming the concrete systems, metrics or "
        "conditions this question requires"
    )


class ResearchEvidenceSchema(BaseModel):
    """What evidence THIS research question needs — generated per run."""
    research_type: str = Field(
        default="comparison",
        description="the intellectual shape of the question: 'comparison', "
        "'decision', 'mechanism', 'evolution', 'evaluation' or 'survey'",
    )
    entities: list[str] = Field(
        default_factory=list, max_length=12,
        description="the systems/methods/options being compared or investigated, "
        "named as the literature names them",
    )
    required_dimensions: list[EvidenceDimension] = Field(
        default_factory=list, max_length=8,
        description="axes the question CANNOT be answered without. Every study "
        "is audited against these, so keep the list tight (3-6).",
    )
    optional_dimensions: list[EvidenceDimension] = Field(
        default_factory=list, max_length=6,
        description="axes that enrich the answer but are not auditable gaps",
    )
    context_variables: list[str] = Field(
        default_factory=list, max_length=10,
        description="what a NUMBER must be qualified by before two studies are "
        "comparable, e.g. 'dataset', 'task', 'baseline', 'model', 'top_k', "
        "'hardware'",
    )
    # Derived here rather than in the screening node so screening costs no extra
    # LLM call: this node already runs at temperature 0, already knows the
    # entities, and already runs BEFORE research (where screening happens).
    screening_criteria: list[ScreeningCriterion] = Field(
        default_factory=list, max_length=6,
        description="the 4-5 inclusion criteria a candidate's title+abstract must "
        "satisfy to enter the corpus. Name the concrete systems/conditions this "
        "question needs. ALWAYS include one criterion requiring that the study "
        "report NUMBERS rather than only qualitative description, and one "
        "requiring that it be a distinct (non-duplicate) study.",
    )

    def normalized(self) -> "ResearchEvidenceSchema":
        """Canonical form — same question in, same schema out (reproducibility).

        Lower-cases and de-duplicates every vocabulary list and sorts them, so a
        run-to-run reordering by the model cannot change the retrieval queries or
        the audit set."""
        def _clean(items: list[str], limit: int) -> list[str]:
            seen, out = set(), []
            for raw in items or []:
                s = " ".join((raw or "").split()).strip().lower()
                if s and s not in seen:
                    seen.add(s)
                    out.append(s)
            return sorted(out)[:limit]

        def _dim(d: "EvidenceDimension") -> "EvidenceDimension":
            return EvidenceDimension(
                name=" ".join((d.name or "").split()).strip().lower()[:60],
                kind=("quantitative" if (d.kind or "").lower().startswith("quant")
                      else "qualitative"),
                description=(d.description or "").strip()[:200],
                synonyms=_clean(d.synonyms, 12),
                metrics=_clean(d.metrics, 8),
                location_hints=_clean(d.location_hints, 8),
                not_applicable_when=(d.not_applicable_when or "").strip()[:200],
                # Reader-facing prose: whitespace-normalized but NOT lower-cased
                # or sorted like the retrieval vocabulary — it is published as
                # written, and case carries meaning in system names.
                extraction_instruction=" ".join(
                    (d.extraction_instruction or "").split())[:400],
            )

        req, seen_names = [], set()
        for d in self.required_dimensions:
            nd = _dim(d)
            if nd.name and nd.name not in seen_names:
                seen_names.add(nd.name)
                req.append(nd)
        opt = []
        for d in self.optional_dimensions:
            nd = _dim(d)
            if nd.name and nd.name not in seen_names:
                seen_names.add(nd.name)
                opt.append(nd)
        req.sort(key=lambda d: d.name)
        opt.sort(key=lambda d: d.name)
        # Criteria are published verbatim, so they are de-duplicated and
        # whitespace-normalized but keep their authored case and ORDER — the
        # order is the order the screen applies and the report prints.
        crit, seen_crit = [], set()
        for c in self.screening_criteria or []:
            name = " ".join((c.name or "").split())[:60]
            question = " ".join((c.question or "").split())[:400]
            key = name.lower()
            if name and question and key not in seen_crit:
                seen_crit.add(key)
                crit.append(ScreeningCriterion(name=name, question=question))

        return ResearchEvidenceSchema(
            research_type=(self.research_type or "comparison").strip().lower()[:40],
            entities=_clean(self.entities, 12),
            required_dimensions=req,
            optional_dimensions=opt,
            context_variables=_clean(self.context_variables, 10),
            screening_criteria=crit[:6],
        )


# ── P0-C: the completeness probe ─────────────────────────────────────────
# After first-pass extraction, every REQUIRED dimension a study did not fill is
# unresolved. Unresolved is NOT the same as absent, and the old matrix conflated
# them. This probe re-reads the paper with retrieval aimed at exactly those
# dimensions and returns, per dimension, one of four honest states.

class DimensionProbe(BaseModel):
    dimension: str = Field(description="the axis being resolved, copied verbatim")
    status: str = Field(
        description="'reported' if this paper DOES report it (then fill text/"
        "quote/chunk_id); 'not_reported' ONLY if the paper measurably does not "
        "report it despite covering the topic; 'not_applicable' if the axis "
        "cannot apply to this study; 'uncertain' if you cannot tell from the "
        "passages shown. NEVER guess 'not_reported' to look decisive — "
        "'uncertain' is the correct answer when the sources are inconclusive."
    )
    text: str = Field(default="", description="if reported: the finding as one sentence")
    metric: str = Field(default="", description="if reported: metric name")
    value: str = Field(default="", description="if reported: the headline number with unit")
    chunk_id: str = Field(
        default="",
        description="if reported: the SOURCE block id. If not_reported AND the "
        "paper explicitly says so ('we do not measure latency'), cite that block.",
    )
    quote: str = Field(
        default="",
        description="VERBATIM quote (>=12 chars) from that SOURCE block. Required "
        "whenever chunk_id is set — a paraphrase is dropped by the gate.",
    )
    rationale: str = Field(
        default="", description="one line explaining a not_reported / "
        "not_applicable / uncertain verdict"
    )
    # Recovered findings are ordinary evidence and must carry the same
    # qualifiers as first-pass ones. Without this they parse into the synthesis
    # layer as context-free numbers, which silently excludes exactly the
    # findings the recovery pass worked hardest to obtain.
    context: EvidenceContext = Field(
        default_factory=lambda: EvidenceContext(),
        description="if reported: what this number was measured ON (dataset, "
        "task, baseline, model, condition). Fill only what the paper states.",
    )


class DimensionProbeResult(BaseModel):
    """One recovery pass over ONE paper, covering all its unresolved axes."""
    probes: list[DimensionProbe] = Field(default_factory=list, max_length=10)
