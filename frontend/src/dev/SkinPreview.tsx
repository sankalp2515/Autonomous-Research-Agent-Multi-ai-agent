// Visual harness for the app shell and report reader. Not shipped (not an
// entry in vite.config's build inputs). Serves fixture data from an in-page
// fetch mock so both skins can be compared without the backend or a sign-in:
//   npm run dev -- --mode skinpreview   ->  /skin-preview.html?skin=glass
//                                          /skin-preview.html?skin=editorial
// The fixture is illustrative, not a real run: numbers are internally
// consistent (claims, funnel, composition add up) so the screen reads true.

const projectId = "p-demo";
const reportId = "r-demo";

const chunk = (doc: string, text: string) => ({
  chunk_id: `k-${doc}-${text.length}`, chunk_text: text, section: "Results", pages: [6, 7],
  document: { id: doc, title: TITLES[doc], url: "https://arxiv.org/abs/2501.00001", source_type: "paper", status: "ready", abstract_only: false },
});

const TITLES: Record<string, string> = {
  d1: "Large language models for title and abstract screening: a validation study",
  d2: "Zero-shot screening for systematic reviews with instruction-tuned models",
  d3: "Active learning versus LLM screening on 26 review datasets",
  d4: "When do LLM screeners miss studies? An error analysis",
};

function claim(id: string, text: string, doc: string, quote: string, passage: string, score = 0.94) {
  return {
    claim_id: id, text, status: "verified",
    evidence: [{ ...chunk(doc, passage), quote, quote_char_start: passage.indexOf(quote),
      quote_char_end: passage.indexOf(quote) + quote.length, nli_label: "entailment", nli_score: score }],
  };
}

const P1 = "Across the 12 review datasets, the model screened titles and abstracts with a median recall of 0.96 while excluding 61% of records, reducing screening time by 45% relative to dual human screening.";
const P2 = "In the zero-shot setting recall fell to 0.88 on the clinical reviews, where inclusion depended on outcome definitions not stated in the abstract.";
const P3 = "Active learning reached 95% recall after screening 38% of records on average, compared with 52% for the LLM-first workflow on the same datasets.";
const P4 = "Most missed studies (17 of 23) reported the eligible outcome only in the full text, so no abstract-level screener could have identified them.";

const sections = [
  { heading: "How much screening work is saved", sub_question: "Do LLM screeners reduce workload without losing included studies?",
    status: "verified", track: "academic", gap_kind: "no_evidence", gap_note: "", section_type: "evidence_comparison",
    claim_ids: ["c1", "c2", "c3"],
    claims: [
      claim("c1", "On 12 review datasets an LLM screener kept a median recall of 0.96 while excluding 61% of records.", "d1", "median recall of 0.96 while excluding 61% of records", P1),
      claim("c2", "That workload reduction cut screening time by 45% against dual human screening.", "d1", "reducing screening time by 45% relative to dual human screening", P1, 0.91),
      claim("c3", "Active learning reached 95% recall after screening 38% of records, against 52% for an LLM-first workflow.", "d3", "Active learning reached 95% recall after screening 38% of records", P3, 0.89),
    ] },
  { heading: "Where recall breaks down", sub_question: "Which studies do LLM screeners miss, and why?",
    status: "verified", track: "academic", gap_kind: "no_evidence", gap_note: "", section_type: "limitations",
    claim_ids: ["c4", "c5"],
    claims: [
      claim("c4", "Zero-shot recall fell to 0.88 on clinical reviews whose inclusion depended on outcome definitions.", "d2", "recall fell to 0.88 on the clinical reviews", P2, 0.93),
      claim("c5", "17 of 23 missed studies reported the eligible outcome only in the full text.", "d4", "Most missed studies (17 of 23) reported the eligible outcome only in the full text", P4, 0.97),
    ] },
  { heading: "Cost per review", sub_question: "What does LLM screening cost per review?",
    status: "gap", track: "academic", gap_kind: "no_evidence", claim_ids: [], claims: [], section_type: "open_questions",
    gap_note: "No study in this corpus reports cost per review; 4 of 4 were checked for it." },
];

const matrix = [
  { doc_id: "d1", title: TITLES.d1, year: 2025, full_text: true, findings: [{ claim_id: "c1", dimension: "recall", metric: "recall", value: "0.96", text: "", quote: "", context: { dataset: "12 reviews", task: "abstract screening" } }],
    cells: { recall: { state: "reported", claim_ids: ["c1"] }, cost: { state: "not_reported", coverage: { queries: 3, examined: 14, chunks: 6 } } } },
  { doc_id: "d2", title: TITLES.d2, year: 2024, full_text: true, findings: [{ claim_id: "c4", dimension: "recall", metric: "recall", value: "0.88", text: "", quote: "", context: { dataset: "clinical reviews", task: "abstract screening" } }],
    cells: { recall: { state: "reported", claim_ids: ["c4"] }, cost: { state: "extraction_uncertain", coverage: {} } } },
  { doc_id: "d3", title: TITLES.d3, year: 2025, full_text: true, findings: [{ claim_id: "c3", dimension: "workload", metric: "records screened at 95% recall", value: "38%", text: "", quote: "", context: { dataset: "26 review datasets", task: "abstract screening" } }],
    cells: { workload: { state: "reported", claim_ids: ["c3"] }, cost: { state: "not_reported", coverage: { queries: 2, examined: 11, chunks: 5 } } } },
  { doc_id: "d4", title: TITLES.d4, year: 2026, full_text: true, findings: [{ claim_id: "c5", dimension: "error analysis", metric: "missed studies", value: "17 of 23", text: "", quote: "", context: {} }],
    cells: { "error analysis": { state: "reported", claim_ids: ["c5"] }, cost: { state: "not_reported", coverage: { queries: 3, examined: 9, chunks: 4 } } } },
];

const report = {
  id: reportId, created_at: "2026-11-24T10:12:00Z",
  title: "LLM-assisted screening in systematic reviews",
  question: "Do LLM-assisted screening tools reduce systematic review workload without losing included studies?",
  outline: sections.map((s) => s.heading),
  sections,
  references: Object.entries(TITLES).map(([id, title], i) => ({
    document_id: id, title, url: "https://arxiv.org/abs/2501.0000" + (i + 1), source_type: "paper",
    year: [2025, 2024, 2025, 2026][i], authors: [["Okafor", "Lindqvist"], ["Mehta"], ["van Dijk", "Rao"], ["Haddad", "Ibarra"]][i], abstract_only: false, citations: [41, 88, 17, 3][i],
  })),
  confidence: {
    sections_verified: 2, sections_total: 3, low_confidence: false, llm_calls: 41,
    coverage_notes: ["1 candidate returned without a screening verdict and was excluded rather than admitted unassessed."],
    composition: { verified: 5, derived: 2, inferred: 0, note: "" },
    derived_statements: [
      { type: "D", kind: "coverage", text: "4 of the 4 studies report recall or workload.", dimension: "recall", doc_ids: ["d1", "d2", "d3", "d4"], basis: "4 studies" },
      { type: "D", kind: "comparability", text: "No two of them measured recall the same way — the same metric on the same dataset and task — so these numbers cannot be pooled or ranked against each other.", dimension: "recall", doc_ids: ["d1", "d2"], basis: "2 studies" },
    ],
    evidence_matrix: matrix,
    evidence_schema: {
      research_type: "evaluation",
      required_dimensions: [{ name: "recall", kind: "quantitative" }, { name: "cost", kind: "quantitative" }],
      screening_criteria: [{ name: "Empirical evaluation", question: "Does it evaluate an LLM screener on real review data?" },
                           { name: "Reports recall", question: "Does it report recall or missed studies?" }],
    },
    synthesis: { studies_total: 4, dimensions: [] },
    plan: { objective: "Assess whether LLM screening saves work without losing studies", sub_questions: [], sections: [] },
    funnel: {
      ladder: { discovered: 214, screened: 213, eligible: 9, ingested: 6, full_text_available: 5, extracted: 4, included_in_synthesis: 4, cited_in_report: 4 },
      found: 214, screened: 213, screened_in: 9, screened_out: 204, screen_unassessed: 1,
      screen_excluded_by_criterion: { "Empirical evaluation": 151, "Reports recall": 53 },
      excluded_by_reason: { screened_out: 204, screen_no_verdict: 1, no_retrievable_text: 1, abstract_only: 1 },
      cells_total: 8, cells_reported: 4, cells_not_reported: 3, cells_not_applicable: 0, cells_uncertain: 1,
      required_dimensions: ["recall", "cost"], claims_verified: 5, claims_refused: 3,
      sub_questions: 3, sub_questions_grounded: 2, papers_ingested: 6, sources_cited: 4,
    },
    refusal_reasons: { nli_weak: 2, quote_mismatch: 1 },
    refused_claims: [], scope: { in_scope: true, field: "information science", since_year: 2023, until_year: 0, min_citations: 0 },
    report_genre: "evaluation", study_characteristics: {}, practical_implications: [],
  },
};

const runs = [{
  id: "run-1", query: report.question, status: "completed", current_node: "done", report_id: reportId,
  budgets_spent: { llm_calls: 41, seconds: 1288 }, created_at: "2026-11-24T09:50:00Z",
  started_at: "2026-11-24T09:50:00Z", elapsed_seconds: 1288,
}];

const claimById = Object.fromEntries(sections.flatMap((s) => s.claims).map((c) => [c.claim_id, c]));

const routes: [RegExp, unknown | ((path: string) => unknown)][] = [
  [/^\/api\/claims\/[^/]+\/evidence$/, (path: string) => claimById[path.split("/")[3]] ?? null],
  [/^\/api\/projects$/, [{ id: projectId, name: "Screening automation", description: "", org_id: null, documents: 6, runs: 1, created_at: "2026-11-20T08:00:00Z" }]],
  [/^\/api\/projects\/[^/]+\/runs$/, runs],
  [/^\/api\/report\/[^/]+\/contradictions$/, { contradictions: [] }],
  [/^\/api\/report\/[^/]+\/next-questions$/, { questions: ["Which review types lose the most recall?", "How does dual screening compare with LLM plus one human?"] }],
  [/^\/api\/report\/[^/]+$/, report],
  [/^\/api\/projects\/[^/]+\/resume$/, null],
  [/^\/api\/invites\/accept$/, { joined: 0, orgs: [] }],
  [/^\/api\/orgs$/, []],
];

const realFetch = window.fetch.bind(window);
window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
  const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
  if (!path.startsWith("/api/")) return realFetch(input, init);
  const hit = routes.find(([re]) => re.test(path));
  const found = hit ? hit[1] : undefined;
  const body = hit ? (typeof found === "function" ? found(path) : found)
    : (init?.method && init.method !== "GET" ? {} : []);
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
};

sessionStorage.setItem("vs_entered", "1");
if (!window.location.hash) window.location.hash = `#/p/${projectId}/report`;
import("../main");
