import { useEffect, useState } from "react";
import { api } from "../api";
import type { MetricValue, ReportMetrics } from "../types";
import { Empty, Spinner } from "./ui";

// Traced RAG-evaluation dashboard. Every number is derived from the same
// evidence the verification gate produced, and each card exposes its exact
// definition — transparency is the point.

const ORDER: {
  key: keyof ReportMetrics["metrics"];
  label: string;
  glyph: string;
  good: number; // ratio threshold considered "good"
}[] = [
  { key: "citation_accuracy", label: "Citation Accuracy", glyph: "❝", good: 0.95 },
  { key: "faithfulness", label: "Answer Faithfulness", glyph: "✓", good: 0.9 },
  { key: "answer_relevance", label: "Answer Relevance", glyph: "◎", good: 0.6 },
  { key: "context_precision", label: "Context Precision", glyph: "◑", good: 0.5 },
  { key: "context_recall", label: "Context Recall", glyph: "◐", good: 0.6 },
  { key: "latency", label: "Latency", glyph: "◷", good: 0 },
];

function Ring({ pct, good, color }: { pct: number; good: boolean; color: string }) {
  const r = 30;
  const c = 2 * Math.PI * r;
  const off = c * (1 - Math.max(0, Math.min(1, pct)));
  return (
    <svg width="76" height="76" viewBox="0 0 76 76" className="metric-ring">
      <circle cx="38" cy="38" r={r} fill="none" stroke="var(--line-2)" strokeWidth="7" />
      <circle
        cx="38" cy="38" r={r} fill="none" stroke={color} strokeWidth="7"
        strokeDasharray={c} strokeDashoffset={off} strokeLinecap="round"
        transform="rotate(-90 38 38)" style={{ transition: "stroke-dashoffset .8s ease" }}
      />
      <text x="38" y="43" textAnchor="middle" className="metric-ring-num" fill="var(--text)">
        {Math.round(pct * 100)}
      </text>
    </svg>
  );
}

function MetricCard({ m, label, glyph, good }: {
  m: MetricValue; label: string; glyph: string; good: number;
}) {
  const [open, setOpen] = useState(false);
  // if (m.unit === "seconds") {
  //   return (
  //     <div className="metric-card latency">
  //       <div className="metric-card-head">
  //         <span className="metric-glyph">{glyph}</span>
  //         <b>{label}</b>
  //         <button className="metric-info" onClick={() => setOpen((o) => !o)}>ⓘ</button>
  //       </div>
  //       <div className="metric-latency-val mono">
  //         {m.available ? `${Math.round(m.value ?? 0)}s` : "n/a"}
  //         {m.llm_calls ? <span className="metric-latency-sub"> · {m.llm_calls} LLM calls</span> : null}
  //       </div>
  //       {m.per_node && Object.keys(m.per_node).length > 0 && (
  //         <div className="metric-nodes">
  //           {(() => {
  //             const entries = Object.entries(m.per_node);
  //             const max = Math.max(...entries.map(([, v]) => v), 0.001);
  //             return entries.map(([node, secs]) => (
  //               <div key={node} className="metric-node-row">
  //                 <span className="metric-node-name">{node.replace("_", " ")}</span>
  //                 <span className="metric-node-bar">
  //                   <span className="metric-node-fill" style={{ width: `${(secs / max) * 100}%` }} />
  //                 </span>
  //                 <span className="mono metric-node-secs">{secs}s</span>
  //               </div>
  //             ));
  //           })()}
  //         </div>
  //       )}
  //       {open && <p className="metric-def">{m.definition}</p>}
  //     </div>
  //   );
  // }
  const val = m.value ?? 0;
  const isGood = m.available && val >= good;
  const color = !m.available ? "var(--text-3)" : isGood ? "var(--ok)" : val >= good * 0.7 ? "var(--warn)" : "var(--bad)";
  return (
    <div className="metric-card">
      <div className="metric-card-head">
        <span className="metric-glyph">{glyph}</span>
        <b>{label}</b>
        <button className="metric-info" onClick={() => setOpen((o) => !o)}>ⓘ</button>
      </div>
      <div className="metric-body">
        {m.available ? (
          <Ring pct={val} good={isGood} color={color} />
        ) : (
          <div className="metric-na">n/a<small>needs local ML</small></div>
        )}
        <div className="metric-verdict">
          {m.available ? (
            <span className={`metric-tag ${isGood ? "ok" : val >= good * 0.7 ? "warn" : "bad"}`}>
              {isGood ? "strong" : val >= good * 0.7 ? "fair" : "weak"}
            </span>
          ) : (
            <span className="metric-tag na">unavailable</span>
          )}
        </div>
      </div>
      {open && <p className="metric-def">{m.definition}</p>}
    </div>
  );
}

export default function MetricsView({
  projectId,
  reportId,
}: {
  projectId: string;
  reportId?: string | null;
}) {
  const [data, setData] = useState<ReportMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [none, setNone] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setError("");
      setNone(false);
      try {
        let rid = reportId ?? null;
        if (!rid) {
          const runs = await api.listRuns(projectId);
          rid = runs.find((r) => r.report_id)?.report_id ?? null;
        }
        if (!rid) {
          if (alive) setNone(true);
          return;
        }
        const m = await api.getReportMetrics(rid);
        if (alive) setData(m);
      } catch (e: any) {
        if (alive) setError(e.message ?? String(e));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [projectId, reportId]);

  if (loading) return <p><Spinner /> computing evaluation metrics…</p>;
  if (none)
    return (
      <Empty glyph="◷" title="No report to evaluate yet">
        Run a deep-research pass first. Once a report exists, this dashboard
        scores it on citation accuracy, faithfulness, answer relevance, context
        precision & recall, and latency — every number traced to its evidence.
      </Empty>
    );
  if (error) return <p style={{ color: "var(--bad)" }}>{error}</p>;
  if (!data) return null;

  return (
    <div className="metrics-view">
      <div style={{ marginBottom: 16 }}>
        <span className="overline">RAG evaluation · traced to evidence</span>
        <h2 style={{ margin: "4px 0 2px", fontFamily: "var(--serif)", fontWeight: 600 }}>
          {data.report_title}
        </h2>
        <p className="mono" style={{ margin: 0, color: "var(--text-3)", fontSize: 12 }}>
          {data.claims_total} verified claims · {data.sections_verified}/{data.sections_total} sections grounded
          {!data.ml_available && " · local ML off — showing deterministic metrics only"}
        </p>
      </div>

      <div className="metrics-grid">
        {ORDER.map((o) => (
          <MetricCard key={o.key} m={data.metrics[o.key]} label={o.label} glyph={o.glyph} good={o.good} />
        ))}
      </div>

      <div className="overline" style={{ margin: "26px 0 8px" }}>
        Evidence trace — every claim, its cited source, quote-match & entailment
      </div>
      <div className="metrics-trace-wrap">
        <table className="metrics-trace">
          <thead>
            <tr>
              <th>Claim</th>
              <th>Source</th>
              <th>Quote match</th>
              <th>Entailment (NLI)</th>
            </tr>
          </thead>
          <tbody>
            {data.trace.map((t) => (
              <tr key={t.claim_id}>
                <td className="mt-claim">{t.text}</td>
                <td className="mt-src">
                  {t.doc_title}
                  {t.page > 0 && <span className="mono"> · p{t.page}</span>}
                </td>
                <td>
                  <span className={`mt-badge ${t.quote_ok ? "ok" : "bad"}`}>
                    {t.quote_ok ? "✓ exact" : "✗"}
                  </span>
                </td>
                <td>
                  <span className={`mt-badge ${t.nli_label === "entailment" ? "ok" : t.nli_label === "contradiction" ? "bad" : "neutral"}`}>
                    {t.nli_label === "skipped" ? "quote-only" : `${t.nli_label} ${t.nli_score.toFixed(2)}`}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
