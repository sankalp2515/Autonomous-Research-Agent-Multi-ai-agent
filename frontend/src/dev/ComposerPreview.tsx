// Temporary visual harness for the project research composer. Not shipped.
// Stubs fetch so the real RunsView renders without a backend.
import { createRoot } from "react-dom/client";
import "../styles.css";

const RUNS = [
  { id: "r9", query: "Autonomous AI agents supply chain compliance financial forecasting integration",
    status: "completed", current_node: "build_graph", report_id: "rep1",
    budgets_spent: { llm_calls: 63, seconds: 2400 }, created_at: "2026-08-14T09:00:00+00:00",
    started_epoch: 0, server_now: 0, running: false, elapsed_seconds: 3412 },
];
const REPORT = {
  title: "Autonomous AI Agents in Supply Chain Management: Compliance and Forecasting Integration",
  sections: [], confidence: { sections_verified: 6, sections_total: 6 },
};
const NEXTQ = { questions: [
  "What are the optimal strategies for integrating autonomous AI agents with human decision-makers in supply chain management to ensure seamless compliance and forecasting?",
  "How can explainability and transparency be enhanced in machine learning models used by autonomous agents for financial forecasting in supply chains?",
  "Which regulatory frameworks most constrain autonomous agent deployment in cross-border supply chain compliance?",
  "What benchmarks exist for evaluating forecasting accuracy of autonomous agents against classical time-series baselines?",
]};

const orig = window.fetch;
window.fetch = (async (input: any, init?: any) => {
  const url = String(typeof input === "string" ? input : input.url);
  const json = (b: any) => new Response(JSON.stringify(b), { status: 200, headers: { "content-type": "application/json" } });
  if (url.includes("/runs")) return json(RUNS);
  if (url.includes("/next-questions") || url.includes("next_questions")) return json(NEXTQ);
  if (url.includes("/report")) return json(REPORT);
  return orig(input, init);
}) as typeof fetch;

const { default: RunsView } = await import("../components/RunsView");

createRoot(document.getElementById("root")!).render(
  <div className="app-main" style={{ padding: 28, maxWidth: 980, margin: "0 auto" }}>
    <RunsView projectId="p1" onOpenReport={() => {}} initial={null} />
  </div>
);
