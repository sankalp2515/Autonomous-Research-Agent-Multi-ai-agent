export interface Project {
  id: string;
  name: string;
  description: string;
  org_id?: string | null;
  documents: number;
  runs: number;
  created_at: string;
}

export interface Org { id: string; name: string; personal: boolean; role: string }
export interface OrgMember { user_id: string; role: string; email?: string; name?: string }
export interface OrgInvite { id: string; email: string; role: string }

export interface Doc {
  id: string;
  title: string;
  source_type: string;
  status: string;
  status_reason: string;
  url: string;
  year: number | null;
  authors: string[];
  abstract_only: boolean;
  full_text_available: boolean;
  created_at: string;
}

export interface Evidence {
  chunk_id: string;
  document_id: string;
  document_title: string;
  section: string;
  page_start: number;
  page_end: number;
  quote: string;
  quote_char_start: number;
  quote_char_end: number;
  nli_label: string;
  nli_score: number;
  abstract_only: boolean;
  source_type: string;
}

export interface Claim {
  id: string;
  text: string;
  evidence: Evidence;
}

export interface TechnicalHit {
  document_id: string;
  document_title: string;
  source_type: string;
  snippet: string;
}

export interface ChatResult {
  answer_id: string;
  refused: boolean;
  refusal_reason: string;
  coverage_note: string;
  claims: Claim[];
  technical_context: TechnicalHit[];
}

export interface ChatTurn {
  question: string;
  result: ChatResult | null;
  error?: string;
}

// The run clock is computed SERVER-side against one reference `now`.
// budgets_spent.seconds is only rewritten at a node checkpoint, so it freezes
// for minutes inside a long node; the client ticks forward from elapsed_seconds
// instead of deriving a start time from a timestamp it may misparse.
export interface RunClock {
  started_epoch?: number;
  server_now?: number;
  running?: boolean;
  elapsed_seconds?: number;
}

export interface Run extends RunClock {
  id: string;
  query: string;
  status: string;
  current_node: string;
  report_id: string | null;
  budgets_spent: { llm_calls?: number; seconds?: number };
  created_at: string;
}

// What the pipeline is doing right now. `kind` is emitted by the backend at the
// publish site — the feed never infers it by pattern-matching our own prose.
export type ProgressKind =
  | "stage" | "search" | "ingest" | "corpus" | "extract"
  | "recover" | "verify" | "refuse" | "error" | "done";

export interface ProgressEvent {
  node?: string;
  status?: string;
  kind?: ProgressKind;
  message?: string;
  at?: number;             // epoch seconds, stamped by the publisher
  elapsed?: number;        // run seconds at publish time
  llm_calls?: number;
  sections_done?: number;
  sections_total?: number;
  papers_done?: number;
  papers_total?: number;
  papers_ingested?: number;
  full_text?: boolean;
  findings?: number;
  dimensions?: number;
  open_cells?: number;
  recovered?: number;
  section?: string;
  passed?: number;
  refused?: number;
  claims_verified?: number;
  claims_refused?: number;
  coverage_notes?: string[];
  report_id?: string;
  error?: string;
}

export interface RunStatus extends RunClock {
  run_id: string;
  status: string;
  current_node: string;
  error: string;
  report_id: string | null;
  budgets_spent: { llm_calls?: number; seconds?: number };
  live: ProgressEvent | null;
  events: ProgressEvent[];
}

export interface EvidenceDetail {
  claim_id: string;
  text: string;
  status: string;
  evidence: {
    chunk_id: string;
    quote: string;
    quote_char_start: number;
    quote_char_end: number;
    nli_label: string;
    nli_score: number;
    chunk_text: string;
    section: string;
    pages: number[];
    document: {
      id?: string;
      title?: string;
      url?: string;
      source_type?: string;
      status: string;
      abstract_only?: boolean;
    };
  }[];
}

export interface SectionLayout {
  kind: string; // "table"
  columns: string[];
  rows: { label: string; cells: Record<string, number[]> }[];
}

// Pure reorganization of a section's VERIFIED claims into "###" sub-sections.
// `findings` indexes into `claims` — no new prose is authored.
export interface SubTheme {
  heading: string;
  findings: number[];
}

export interface ReportSection {
  heading: string;
  sub_question: string;
  status: string;
  gap_note: string;
  // Whose limitation closed this section. "no_evidence" is a statement about
  // the CORPUS; "drafting_failed" is a statement about VERISCOPE. They must
  // never be rendered in the same words — a reader trained to read the gap slot
  // as "the literature is silent here" would otherwise read our outage as a
  // finding about the field.
  gap_kind?: "no_evidence" | "drafting_failed";
  track?: string; // academic | technical
  layout?: SectionLayout | null; // optional comparison table over verified claims
  subthemes?: SubTheme[]; // optional ### grouping of verified claims
  claims: EvidenceDetail[];
}

// The planning / chain-of-thought step, surfaced at the top of the report.
export interface AnalysisPlan {
  objective: string;
  sub_questions: string[];
  sections: { heading: string; sub_question: string; status: string; track: string }[];
}

export interface AbstractSentence {
  text: string;
  chunk_id: string;
  quote: string;
  nli_label: string;
  nli_score: number;
  source: string;
  url: string;
  page: number;
}

// One quote-verified extraction from one paper, tagged with the comparison
// axis it answers so findings from different papers line up into columns.
export interface EvidenceFinding {
  claim_id: string;
  dimension: string;
  text: string;
  metric: string;
  value: string;
  chunk_id: string;
  quote: string;
  nli_label: string;
  nli_score: number;
}

// What one study x required-dimension cell MEANS. The matrix used to have two
// states — a finding, or an em-dash — and the em-dash was captioned as "this
// study did not report it". On a real run about half of those cells were empty
// because retrieval never reached the page, so the report was publishing a
// limitation of ours as a fact about the literature. These four states keep the
// two apart; `extraction_uncertain` is a statement about Veriscope, never about
// the paper.
export type CellState =
  | "reported"
  | "not_reported"
  | "not_applicable"
  | "extraction_uncertain";

export interface EvidenceCell {
  state: CellState;
  claim_ids?: string[];
  // True when the finding was missed by the first pass and recovered by the
  // dimension-targeted second read.
  recovered?: boolean;
  // Grounded span for an explicit in-paper statement of absence (quote-matched).
  chunk_id?: string;
  quote?: string;
  // Why we could not resolve it (uncertain cells only) — our reason, not the
  // paper's.
  reason?: string;
  // How hard we looked. This is what licenses a `not_reported` verdict.
  coverage?: { queries?: number; examined?: number; chunks?: number };
}

// One row of the evidence matrix — a STUDY, read on its own terms.
export interface EvidenceRow {
  doc_id: string;
  title: string;
  year: number | null;
  frameworks: string[];
  baselines: string[];
  datasets: string[];
  findings: EvidenceFinding[];
  // Present from the completeness-audit release onward; absent on older
  // reports, which fall back to rendering findings only.
  cells?: Record<string, EvidenceCell>;
}


// A D (derived) statement: a sentence about the BODY of evidence — study
// counts, comparability, disagreement — that no single paper states and no
// quote can ground. `doc_ids` is its provenance: the matrix rows the arithmetic
// ran over. It is never rendered with a footnote, because a citation to one
// paper would misrepresent where it came from.
export interface DerivedStatement {
  type: "D";
  kind: string; // coverage | comparability | contradiction | standing
  text: string;
  dimension: string;
  doc_ids: string[];
  basis: string;
}

// P1 G/H/I — cross-study synthesis, computed deterministically from the
// evidence matrix. Evidence strength here comes from COUNTS OF STUDIES and
// their comparability, never from NLI entailment: entailment says a sentence is
// faithful to its source, which is a different question from how well
// established a finding is.
export type KnowledgeState =
  | "strongly_supported"
  | "moderately_supported"
  | "emerging"
  | "contested"
  | "insufficient_evidence"
  | "unknown";

export interface StudyContradiction {
  dimension: string;
  metric: string;
  dataset: string;
  task: string;
  unit: string;
  a_study: string; a_value: string; a_claim_id: string; a_context: string;
  b_study: string; b_value: string; b_claim_id: string; b_context: string;
  relative_gap: number;
  // Recorded differences that could explain the gap without anyone being wrong.
  moderators: string[];
  explained: boolean;
}

export interface DimensionSynthesis {
  dimension: string;
  studies: number;
  findings: number;
  quantified: number;
  comparable_sets: number;
  largest_comparable_set: number;
  datasets: string[];
  tasks: string[];
  models: string[];
  baselines: string[];
  // Pooled PER SYSTEM — a range spanning two systems describes neither, and
  // the gap between them is usually the finding.
  value_spans: { metric: string; dataset: string; task: string; unit: string;
    system?: string; median?: number; values?: number[]; doc_ids?: string[];
                 studies: number; min: number; max: number }[];
  contradictions: StudyContradiction[];
  unexplained_contradictions: number;
  corpus_coverage: number;
  state: KnowledgeState;
  // What evidence produced the state — never a bare score.
  basis: string;
}

export interface ResearchGap {
  kind: "under_measured" | "single_study" | "no_comparable_evidence" | "contested";
  dimension: string;
  studies: number;
  corpus_studies: number;
  // The counts that make this a gap. Never optional: it is what separates a
  // finding from "more research is needed".
  basis: string;
  severity: "high" | "medium" | "low";
}

// What KIND of evidence the corpus is, before any claim drawn from it.
export interface EvidenceDimensionSpec {
  name: string;
  kind?: string;
  description?: string;
  synonyms?: string[];
  metrics?: string[];
  not_applicable_when?: string;
  // The verbatim instruction the extractor was given for this column. Printed
  // as the review's declared method — this is what makes it reproducible
  // rather than merely audited.
  extraction_instruction?: string;
}

// A statement the verification gate rejected. Kept and published rather than
// counted: every one of these reads plausibly and cites a real source, so the
// list is the only way a reader can judge what the gate is actually doing —
// including the cases where it was wrong.
export interface RefusedClaim {
  stage: string;          // extraction | recovery | drafting | abstract
  section: string;
  text: string;
  quote: string;
  chunk_id: string;
  reason: string;         // quote_mismatch | nli_contradiction | nli_weak | ...
  nli_label: string;
  nli_score: number;
  source_span: string;
}

export interface StudyCharacteristics {
  studies: number;
  year_span: { min: number; max: number } | null;
  years: [number, number][];
  full_text: number | null;
  ingested: number | null;
  frameworks: { name: string; studies: number }[];
  datasets: { name: string; studies: number }[];
  baselines: { name: string; studies: number }[];
  models: { name: string; studies: number }[];
  framework_concentration: number;
}

// S3 — one row of a comparison table: everything this corpus measured about one
// system, INSIDE a single measurement context.
export interface ComparisonRow {
  system: string;
  key: string;
  // Every spelling folded into this row. Rendered on demand so a wrong merge is
  // visible to the reader rather than silent.
  aliases: string[];
  studies: number;
  doc_ids: string[];
  claim_ids: string[];
  min: number;
  max: number;
  median: number;
  values: number[];
}

// S3 — a comparison table. The unit is the MEASUREMENT CONTEXT, not the report:
// every number inside one table shares dimension, metric, dataset, task, unit
// and level-vs-delta, which is exactly the definition of comparable the
// synthesis layer uses. A grid of systems x dimensions would instead invite
// comparing F1 on HotpotQA against Recall@10 on MuSiQue down a column.
export interface ComparisonTable {
  dimension: string;
  metric: string;
  dataset: string;
  task: string;
  unit: string;
  // True when these numbers are CHANGES (deltas) rather than levels.
  signed: boolean;
  systems: number;
  studies: number;
  // How many studies measured two or more of these systems THEMSELVES. Zero
  // means no study compared them — the table juxtaposes numbers that share only
  // a benchmark name, and must say so.
  within_study: number;
  rows: ComparisonRow[];
}

export interface EntityDimensionCoverage {
  dimension: string;
  studies: number;
  findings: number;
  quantified: number;
}

// S3 — what the corpus measured about one system, across all contexts. The
// counterpart to the tables: a system with too little evidence to appear in any
// comparison is still accounted for here.
export interface EntityCoverage {
  key: string;
  system: string;
  aliases: string[];
  studies: number;
  doc_ids: string[];
  dimensions: EntityDimensionCoverage[];
}

export interface Synthesis {
  studies_total: number;
  gaps?: ResearchGap[];
  dimensions: DimensionSynthesis[];
  comparisons?: ComparisonTable[];
  entity_coverage?: EntityCoverage[];
  state_counts: Record<string, number>;
  contradictions_total: number;
  contradictions_unexplained: number;
  note: string;
}

export interface Report {
  id: string;
  title: string;
  // The question the researcher asked. Preferred over `title` (generated) and
  // over confidence.plan.objective (a purpose statement, not a question).
  question?: string;
  outline: string[];
  confidence: {
    sections_verified?: number;
    sections_total?: number;
    coverage_notes?: string[];
    llm_calls?: number;
    plan?: AnalysisPlan;
    low_confidence?: boolean;
    scope?: {
      in_scope?: boolean;
      field?: string;
      min_citations?: number;
      since_year?: number;
    };
    // Gated-synthesis abstract: verdict + synthesis sentences whose every
    // sentence re-passed the quote+NLI gate (null when it couldn't be grounded).
    abstract?: {
      verdict: AbstractSentence | null;
      sentences: AbstractSentence[];
      drafted?: number;
      verified?: number;
    } | null;
    // Phase 1 — the evidence matrix: one row per STUDY. Every finding here
    // already passed the same quote + NLI gate as a report claim.
    evidence_matrix?: EvidenceRow[];
    synthesis?: Synthesis;
    // Phase 3 — D (derived) statements. NOT quote-grounded and not claiming to
    // be: each is computed by template from the study counts in the matrix,
    // with no LLM in the path, and carries the rows its arithmetic ran over.
    // Its gate is that recomputation reproduces it. Render it as prose, but
    // never with a source citation — it says what no single paper says.
    derived_statements?: DerivedStatement[];
    // What kinds of sentence this report is made of. Replaces the
    // "verified against sources" badge.
    composition?: { verified: number; derived: number; inferred: number; note?: string };
    study_characteristics?: StudyCharacteristics;
    // The research genre the architect designed this report for.
    report_genre?: string;
    // Verified claims carrying a condition/cost/failure mode. A SELECTION of
    // gate-passed claims — never authored prose.
    practical_implications?: { claim_id: string; text: string }[];
    // Methods funnel — real tallies of the gate's work.
    funnel?: {
      found?: number;
      screened?: number;
      screened_out?: number;
      extracted_studies?: number;
      extracted_findings?: number;
      extraction_refused?: number;
      papers_ingested?: number;
      sources_cited?: number;
      claims_verified?: number;
      claims_refused?: number;
      filler_removed?: number;
      sub_questions?: number;
      sub_questions_grounded?: number;
      // Completeness audit over the required dimensions.
      cells_total?: number;
      cells_reported?: number;
      cells_not_reported?: number;
      cells_not_applicable?: number;
      cells_uncertain?: number;
      cells_open_before_recovery?: number;
      cells_recovered?: number;
      required_dimensions?: string[];
      // The research ladder, stage by stage. Kept separate rather than reduced
      // to one "coverage" number: the stages fail for different reasons and a
      // reader judging the review needs to see which.
      ladder?: {
        discovered?: number;
        screened?: number;
        eligible?: number;
        ingested?: number;
        full_text_available?: number;
        extracted?: number;
        included_in_synthesis?: number;
        cited_in_report?: number;
      };
      excluded_by_reason?: Record<string, number>;
      exclusions?: { title: string; stage: string; reason: string }[];
      // How many papers each screening criterion removed.
      screen_excluded_by_criterion?: Record<string, number>;
    };
    // The evidence schema this run was audited against — published so the
    // reader can see WHICH axes every study was checked for, and the verbatim
    // instruction used to extract each one.
    evidence_schema?: {
      research_type?: string;
      entities?: string[];
      required_dimensions?: EvidenceDimensionSpec[];
      optional_dimensions?: EvidenceDimensionSpec[];
      context_variables?: string[];
      screening_criteria?: { name: string; question: string }[];
    };
    // Every statement the gate refused, with the span it was checked against.
    refused_claims?: RefusedClaim[];
    refusal_reasons?: Record<string, number>;
  };
  sections: ReportSection[];
  references: {
    document_id: string;
    title: string;
    url: string;
    source_type: string;
    year: number | null;
    authors: string[];
    abstract_only: boolean;
    citations?: number;
  }[];
  created_at: string;
}

export interface MapNode {
  id: string;
  title: string;
  year: number | null;
  authors: string[];
  source_type: string;
  url: string;
  arxiv_id: string | null;
  citations: number;
  abstract_only: boolean;
  // Precomputed server-side so the client never re-solves the force layout.
  x?: number;
  y?: number;
  cluster?: number;
}
export interface MapEdge { src: string; dst: string; weight: number; kind?: string }
export interface MapData { nodes: MapNode[]; edges: MapEdge[]; clusters?: number; w?: number; h?: number }

export interface ClarifyResult {
  allowed: boolean;
  reason: string;
  objective: string;
  questions: string[];
  // 'specific' | 'underspecified' | 'ambiguous'. A specific query is launched
  // without ever pausing — clarification is a response to real ambiguity, not
  // a toll gate on every run.
  ambiguity?: string;
  field?: string;
  in_scope?: boolean;
  scope_note?: string;
  since_year?: number;
  until_year?: number;
  min_citations?: number;
}

// A screening candidate — a paper found but NOT yet ingested. The researcher
// keeps/drops these before anything enters the corpus.
export interface Candidate {
  source: string;
  external_id: string;
  title: string;
  abstract: string;
  authors: string[];
  year: number | null;
  url: string;
  pdf_url: string;
  doi: string | null;
  arxiv_id: string | null;
  citation_count: number;
  venue: string;
  score: number;
  recommend: "keep" | "drop";
  reason: string;
  domain_fit: string;
}

export interface ScreenResult {
  objective: string;
  field: string;
  in_scope: boolean;
  since_year: number;
  until_year: number;
  min_citations: number;
  found: number;
  candidates: Candidate[];
  // Per required axis, how many kept candidates even MENTION it. Counted from
  // titles and abstracts, so it is an upper bound on what extraction can find —
  // shown before the run so an unanswerable axis is a decision, not a surprise.
  axis_coverage?: {
    axis: string;
    candidates_mentioning: number;
    candidates_kept: number;
    share: number;
    verdict: string;
    terms: string[];
  }[];
  screening_criteria?: { name: string; question: string }[];
}

export interface Note {
  id: string;
  title: string;
  body: string;
  tags: string[];
  source_ref: string;
  claim_id: string | null;
  updated_at: string;
}

export interface Watch {
  id: string;
  query: string;
  active: boolean;
  last_checked: string | null;
}

export interface Alert {
  id: string;
  title: string;
  url: string;
  abstract: string;
  authors: string[];
  year: number | null;
  score: number;
  arxiv_id: string | null;
  has_pdf: boolean;
}

export interface MonitorData {
  watches: Watch[];
  alerts: Alert[];
}

export interface SavedItem {
  id: string;
  claim_id: string;
  text: string;
  note: string;
  source: string;
  page: number;
  quote: string;
  created_at: string;
}

export interface Contradiction {
  score: number;
  a: { claim_id: string; text: string; source: string; page: number };
  b: { claim_id: string; text: string; source: string; page: number };
}

export interface RefindHit {
  chunk_id: string;
  document_id: string;
  document_title: string;
  section: string;
  page_start: number;
  page_end: number;
  snippet: string;
  score: number;
  abstract_only: boolean;
}

export interface CompareCell {
  claim: string;
  quote: string;
  chunk_id: string;
  claim_id: string;
  page: number;
  verified: boolean;
}

export interface Comparison {
  id: string;
  title: string;
  dimensions: string[];
  include_in_report: boolean;
  created_at: string;
  documents: { id: string; title: string; year: number | null; url: string }[];
  matrix: { dimension: string; cells: Record<string, CompareCell | null> }[];
}

export interface ComparisonSummary {
  id: string;
  title: string;
  dimensions: string[];
  document_count: number;
  include_in_report: boolean;
  created_at: string;
}

export interface Recommendation {
  id: string;
  title: string;
  year: number | null;
  authors: string[];
  url: string;
  citations: number;
  score: number;
}

export interface ResumeData {
  project_id: string;
  doc_count: number;
  comparison_count: number;
  new_alerts: number;
  unfinished_runs: {
    run_id: string;
    query: string;
    status: string;
    current_node: string;
    resumable: boolean;
    created_at: string;
  }[];
  last_activity: string;
  last_activity_at: string;
  open_gaps: string[];
  latest_report_id: string | null;
  suggestions: { kind: string; label: string; run_id?: string }[];
}

export interface MetricValue {
  value: number | null;
  unit: "ratio" | "seconds";
  definition: string;
  available: boolean;
  per_node?: Record<string, number>;
  llm_calls?: number;
}

export interface ReportMetrics {
  report_id: string;
  report_title: string;
  claims_total: number;
  sections_verified: number;
  sections_total: number;
  ml_available: boolean;
  metrics: {
    citation_accuracy: MetricValue;
    faithfulness: MetricValue;
    answer_relevance: MetricValue;
    context_precision: MetricValue;
    context_recall: MetricValue;
    latency: MetricValue;
  };
  trace: {
    claim_id: string;
    text: string;
    section: string;
    quote: string;
    quote_ok: boolean;
    nli_label: string;
    nli_score: number;
    doc_title: string;
    page: number;
  }[];
}

export interface GraphData {
  nodes: { id: string; type: string; label: string }[];
  edges: { src: string; dst: string; relation: string; weight: number }[];
}

// Per-project observability dashboard (GET /api/projects/:id/dashboard).
export interface Dashboard {
  project_id: string;
  trust: {
    verified_claims: number;
    evidence_rows: number;
    fabricated_citations: number;
    quote_match_rate: number | null;
    avg_entailment_score: number | null;
    entailment_rate: number | null;
    contradictions_shipped: number;
    reports: number;
    section_gap_rate: number | null;
    chat_answers: number;
    chat_refusal_rate: number | null;
  };
  cost: {
    tokens_in: number;
    tokens_out: number;
    tokens_total: number;
    llm_calls: number;
    avg_tokens_per_run: number;
    est_cost_usd: number | null;
    cost_note: string;
  };
  latency: {
    runs_measured: number;
    p50_seconds: number | null;
    p95_seconds: number | null;
    avg_seconds: number | null;
    per_node_avg_seconds: Record<string, number>;
  };
  retrieval: {
    available: boolean;
    report_id?: string;
    context_precision?: number | null;
    context_recall?: number | null;
    answer_relevance?: number | null;
    faithfulness?: number | null;
    note?: string;
  };
  corpus: {
    documents_by_status: Record<string, number>;
    documents_total: number;
    abstract_only: number;
    chunks_total: number;
    chunks_embedded: number;
    chunks_cold: number;
  };
  providers: {
    provider: string;
    configured: boolean;
    circuit_open: boolean;
    rpm: number;
  }[];
  runs: {
    id: string;
    query: string;
    status: string;
    seconds: number | null;
    tokens: number;
    llm_calls: number | null;
    report_id: string | null;
    gaps: number;
    resumable: boolean;
    created_at: string;
  }[];
}
