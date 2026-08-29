// Temporary visual harness for the live-run surface. Not shipped.
import { createRoot } from "react-dom/client";
import "../styles.css";
import { RunLive } from "../components/RunLive";
import type { ProgressEvent, Run, RunStatus } from "../types";

const t0 = Date.now() / 1000 - 1147;
const E = (elapsed: number, kind: any, node: string, message: string, extra: any = {}): ProgressEvent =>
  ({ at: t0 + elapsed, elapsed, kind, node, status: "running", message, ...extra });

const events: ProgressEvent[] = [
  E(0, "stage", "clarify", "Understanding your question…"),
  E(9, "stage", "plan", "Planning targeted searches across sources…"),
  E(21, "stage", "evidence_schema", "Deciding what evidence this question requires…"),
  E(34, "search", "research", "Searching for “graph retrieval augmented generation architecture”…"),
  E(35, "search", "research", "Searching for “GraphRAG community summarization evaluation”…"),
  E(38, "ingest", "research", "Ingesting 28 papers — downloading & parsing PDFs (some may lack accessible full text)…", { papers_total: 28 }),
  E(96, "ingest", "research", "7/28 · read full text (2024) — “From Local to Global: A Graph RAG Approach to Query-Focused Summarization”", { papers_done: 7, papers_total: 28 }),
  E(151, "ingest", "research", "14/28 · read abstract-only (2023) — “Knowledge Graph Augmented Language Models for Complex Reasoning”", { papers_done: 14, papers_total: 28, full_text: false }),
  E(233, "corpus", "research", "Indexed 26 papers into the corpus.", { papers_ingested: 26 }),
  E(240, "extract", "extract_evidence", "Reading 26 papers into a structured evidence matrix - frameworks, baselines, datasets & results...", { papers_total: 26 }),
  E(388, "extract", "extract_evidence", "12/26 papers extracted · 74 verified findings across 9 comparison dimensions", { papers_done: 12, papers_total: 26, findings: 74, dimensions: 9 }),
  E(596, "extract", "extract_evidence", "26/26 papers extracted · 168 verified findings across 10 comparison dimensions", { papers_done: 26, papers_total: 26, findings: 168, dimensions: 10 }),
  E(612, "recover", "extract_evidence", "Completeness audit: 31 unresolved cell(s) across 18 studies — re-reading each paper for exactly what is missing…", { open_cells: 31 }),
  E(770, "recover", "extract_evidence", "Recovered 19 previously-missing finding(s) so far — each re-verified against its source", { recovered: 19 }),
  E(801, "stage", "report_architect", "Choosing the report structure that fits the evidence found…"),
  E(866, "stage", "draft_sections", "Drafting & verifying 1/6: Architectural paradigms in leading GraphRAG frameworks"),
  E(931, "verify", "draft_sections", "“Architectural paradigms in leading GraphRAG fra”: 9 claims passed the gate, 2 refused as unsupported", { passed: 9, refused: 2, claims_verified: 9, claims_refused: 2 }),
  E(944, "stage", "draft_sections", "Drafting & verifying 2/6: Retrieval cost and latency under multi-hop queries"),
  E(1043, "refuse", "draft_sections", "“Retrieval cost and latency under multi-hop quer”: 0 claims passed the gate, 5 refused as unsupported", { passed: 0, refused: 5, claims_verified: 9, claims_refused: 7 }),
  E(1058, "stage", "plan", "Planning targeted searches across sources…"),
  E(1102, "stage", "draft_sections", "Drafting & verifying 3/6: Benchmark results against standard RAG baselines"),
  E(1147, "verify", "draft_sections", "“Benchmark results against standard RAG baseline”: 11 claims passed the gate", { passed: 11, refused: 0, claims_verified: 20, claims_refused: 7, sections_done: 3, sections_total: 6 }),
];

const status: RunStatus = {
  run_id: "r1", status: "running", current_node: "draft_sections", error: "",
  report_id: null, budgets_spent: { llm_calls: 41, seconds: 866 },
  live: { node: "draft_sections", status: "running", sections_done: 3, sections_total: 6,
          coverage_notes: ["1 paper had no accessible PDF and was indexed from its abstract alone, so its results could not be read."] },
  events, started_epoch: t0, server_now: t0 + 1147, running: true, elapsed_seconds: 1147,
};

const run: Run = {
  id: "r1", query: "Compare GraphRAG frameworks against standard RAG", status: "running",
  current_node: "draft_sections", report_id: null,
  budgets_spent: { llm_calls: 41, seconds: 866 }, created_at: "",
  started_epoch: t0, server_now: t0 + 1147, running: true, elapsed_seconds: 1147,
};

createRoot(document.getElementById("root")!).render(
  <div className="content-narrow" style={{ padding: 28, maxWidth: 880, margin: "0 auto" }}>
    <div className="run-row active">
      <div className="run-head">
        <p className="run-query">{run.query}</p>
      </div>
      <RunLive run={run} status={status} />
      <div className="run-foot"><span className="mono">19:07 elapsed · 41 llm calls</span></div>
    </div>
  </div>
);
