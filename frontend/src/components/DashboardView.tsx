import { useEffect, useState } from "react";
import { api } from "../api";
import type { Dashboard } from "../types";
import { Empty, Spinner } from "./ui";

// Per-project observability dashboard. Trust leads (it is the product); then
// cost/tokens, latency, retrieval quality, corpus, provider health, run history.
// Every number is read from the system of record; genuinely-unmeasured signals
// show "n/a" rather than a fabricated value — the same honesty as the report.

const card: React.CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--line-2)",
  borderRadius: 10,
  padding: 16,
};

function pctStr(v: number | null | undefined): string {
  return v == null ? "n/a" : `${Math.round(v * 100)}%`;
}

function Stat({
  label, value, tone, sub,
}: {
  label: string;
  value: string;
  tone?: "ok" | "warn" | "bad" | "muted";
  sub?: string;
}) {
  const color =
    tone === "ok" ? "var(--ok)" : tone === "bad" ? "var(--bad)"
      : tone === "warn" ? "var(--warn)" : "var(--text)";
  return (
    <div style={{ ...card, minWidth: 0 }}>
      <div className="overline" style={{ color: "var(--text-3)" }}>{label}</div>
      <div className="mono" style={{ fontSize: 26, fontWeight: 600, color, lineHeight: 1.1, marginTop: 6 }}>
        {value}
      </div>
      {sub && <div className="mono" style={{ fontSize: 11, color: "var(--text-3)", marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

function grid(min = 150): React.CSSProperties {
  return { display: "grid", gridTemplateColumns: `repeat(auto-fill, minmax(${min}px, 1fr))`, gap: 12 };
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginTop: 26 }}>
      <div className="overline" style={{ marginBottom: 10 }}>{title}</div>
      {children}
    </section>
  );
}

function NodeBars({ nodes }: { nodes: Record<string, number> }) {
  const entries = Object.entries(nodes);
  if (!entries.length) return null;
  const max = Math.max(...entries.map(([, v]) => v), 0.001);
  return (
    <div style={{ ...card, marginTop: 12 }}>
      {entries.map(([node, secs]) => (
        <div key={node} style={{ display: "flex", alignItems: "center", gap: 10, margin: "5px 0" }}>
          <span style={{ width: 120, fontSize: 12, color: "var(--text-2)" }}>{node.replace(/_/g, " ")}</span>
          <span style={{ flex: 1, height: 7, background: "var(--line-2)", borderRadius: 4, overflow: "hidden" }}>
            <span style={{ display: "block", height: "100%", width: `${(secs / max) * 100}%`, background: "var(--accent)" }} />
          </span>
          <span className="mono" style={{ width: 52, textAlign: "right", fontSize: 12 }}>{secs}s</span>
        </div>
      ))}
    </div>
  );
}

export default function DashboardView({
  projectId, onOpenReport,
}: {
  projectId: string;
  onOpenReport?: (reportId: string) => void;
}) {
  const [d, setD] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const data = await api.getDashboard(projectId);
        if (alive) setD(data);
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [projectId]);

  if (loading) return <p><Spinner /> assembling project observability…</p>;
  if (error) return <p style={{ color: "var(--bad)" }}>{error}</p>;
  if (!d) return null;

  const t = d.trust;
  const hasActivity = t.verified_claims > 0 || d.corpus.documents_total > 0 || d.runs.length > 0;
  if (!hasActivity) {
    return (
      <Empty glyph="◔" title="Nothing to report yet">
        Once you ingest sources and run a research pass, this dashboard tracks the
        project's verification health, token cost, latency, retrieval quality,
        corpus, and provider status — every number traced to the system of record.
      </Empty>
    );
  }

  return (
    <div style={{ maxWidth: 1080 }}>
      <div style={{ marginBottom: 4 }}>
        <span className="overline">Observability · project health</span>
        <h2 style={{ margin: "4px 0 2px", fontFamily: "var(--serif)", fontWeight: 600 }}>
          Project dashboard
        </h2>
        <p className="mono" style={{ margin: 0, color: "var(--text-3)", fontSize: 12 }}>
          {t.verified_claims} verified claims · {d.corpus.documents_total} sources · {d.runs.length} runs
        </p>
      </div>

      {/* TRUST — leads, because trust is the product. */}
      <Section title="Verification health — the trust guarantee">
        <div style={grid(150)}>
          <Stat
            label="Fabricated citations"
            value={String(t.fabricated_citations)}
            tone={t.fabricated_citations === 0 ? "ok" : "bad"}
            sub="structural guarantee: must be 0"
          />
          <Stat
            label="Contradictions shipped"
            value={String(t.contradictions_shipped)}
            tone={t.contradictions_shipped === 0 ? "ok" : "bad"}
            sub="NLI-rejected, never shipped"
          />
          <Stat label="Verified claims" value={String(t.verified_claims)} sub={`${t.evidence_rows} evidence spans`} />
          <Stat
            label="Quote-match rate"
            value={pctStr(t.quote_match_rate)}
            tone={t.quote_match_rate != null && t.quote_match_rate >= 0.99 ? "ok" : "warn"}
            sub="verbatim, exact"
          />
          <Stat
            label="Entailment rate"
            value={pctStr(t.entailment_rate)}
            tone={t.entailment_rate != null && t.entailment_rate >= 0.85 ? "ok" : "warn"}
            sub={t.avg_entailment_score != null ? `avg score ${t.avg_entailment_score}` : "NLI"}
          />
          <Stat
            label="Section gap rate"
            value={pctStr(t.section_gap_rate)}
            tone="muted"
            sub="honest gaps, not fabrications"
          />
          {t.chat_answers > 0 && (
            <Stat label="Chat refusal rate" value={pctStr(t.chat_refusal_rate)} tone="muted"
              sub={`${t.chat_answers} answers`} />
          )}
        </div>
      </Section>

      {/* COST & TOKENS */}
      <Section title="Cost & tokens">
        <div style={grid(150)}>
          <Stat label="Total tokens" value={d.cost.tokens_total.toLocaleString()}
            sub={`${d.cost.tokens_in.toLocaleString()} in · ${d.cost.tokens_out.toLocaleString()} out`} />
          <Stat label="LLM calls" value={d.cost.llm_calls.toLocaleString()} />
          <Stat label="Avg tokens / run" value={d.cost.avg_tokens_per_run.toLocaleString()} />
          <Stat
            label="Est. cost"
            value={d.cost.est_cost_usd == null ? "$0.00" : `$${d.cost.est_cost_usd.toFixed(2)}`}
            tone="muted"
            sub={d.cost.cost_note}
          />
        </div>
      </Section>

      {/* LATENCY */}
      <Section title="Latency">
        <div style={grid(150)}>
          <Stat label="p50 run" value={d.latency.p50_seconds == null ? "n/a" : `${d.latency.p50_seconds}s`} />
          <Stat label="p95 run" value={d.latency.p95_seconds == null ? "n/a" : `${d.latency.p95_seconds}s`} />
          <Stat label="Avg run" value={d.latency.avg_seconds == null ? "n/a" : `${d.latency.avg_seconds}s`}
            sub={`${d.latency.runs_measured} runs measured`} />
        </div>
        <NodeBars nodes={d.latency.per_node_avg_seconds} />
      </Section>

      {/* RETRIEVAL QUALITY */}
      <Section title="Retrieval quality (latest report)">
        {d.retrieval.available ? (
          <div style={grid(150)}>
            <Stat label="Context precision" value={pctStr(d.retrieval.context_precision)} tone="muted" />
            <Stat label="Context recall" value={pctStr(d.retrieval.context_recall)} tone="muted" />
            <Stat label="Answer relevance" value={pctStr(d.retrieval.answer_relevance)} tone="muted" />
            <Stat label="Faithfulness" value={pctStr(d.retrieval.faithfulness)} tone="muted" />
          </div>
        ) : (
          <div style={{ ...card, color: "var(--text-3)", fontSize: 13 }}>
            {d.retrieval.note ?? "No report metrics computed yet."}
          </div>
        )}
      </Section>

      {/* CORPUS */}
      <Section title="Corpus">
        <div style={grid(150)}>
          <Stat label="Documents" value={String(d.corpus.documents_total)}
            sub={`${d.corpus.abstract_only} abstract-only`} />
          <Stat label="Chunks embedded" value={d.corpus.chunks_embedded.toLocaleString()}
            sub={`${d.corpus.chunks_cold.toLocaleString()} cold`} />
        </div>
        <div style={{ ...card, marginTop: 12, display: "flex", flexWrap: "wrap", gap: 8 }}>
          {Object.entries(d.corpus.documents_by_status).map(([status, n]) => (
            <span key={status} className="mono" style={{
              fontSize: 12, padding: "3px 9px", borderRadius: 20,
              border: "1px solid var(--line-2)",
              color: status === "quarantined" || status === "failed" ? "var(--bad)"
                : status === "indexed" ? "var(--ok)" : "var(--text-2)",
            }}>
              {status}: {n}
            </span>
          ))}
        </div>
      </Section>

      {/* PROVIDER HEALTH */}
      <Section title="Provider health">
        <div style={{ ...card, padding: 0, overflow: "hidden" }}>
          {d.providers.map((p, i) => (
            <div key={p.provider} style={{
              display: "flex", alignItems: "center", gap: 12, padding: "10px 14px",
              borderTop: i ? "1px solid var(--line-2)" : "none",
              opacity: p.configured ? 1 : 0.5,
            }}>
              <span style={{
                width: 8, height: 8, borderRadius: "50%",
                background: !p.configured ? "var(--text-3)" : p.circuit_open ? "var(--bad)" : "var(--ok)",
              }} />
              <b style={{ width: 120 }}>{p.provider}</b>
              <span className="mono" style={{ fontSize: 12, color: "var(--text-3)" }}>
                {!p.configured ? "not configured" : p.circuit_open ? "circuit open (cooling down)" : "healthy"}
              </span>
              {p.configured && (
                <span className="mono" style={{ marginLeft: "auto", fontSize: 12, color: "var(--text-3)" }}>
                  {p.rpm} rpm
                </span>
              )}
            </div>
          ))}
        </div>
      </Section>

      {/* RUN HISTORY */}
      <Section title="Recent runs">
        <div style={{ ...card, padding: 0, overflow: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ color: "var(--text-3)", textAlign: "left" }}>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>Query</th>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>Status</th>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>Time</th>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>Tokens</th>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>Gaps</th>
              </tr>
            </thead>
            <tbody>
              {d.runs.map((r) => {
                const bad = r.status === "failed";
                const done = r.status === "completed" || r.status === "completed_with_gaps";
                return (
                  <tr
                    key={r.id}
                    onClick={() => r.report_id && onOpenReport?.(r.report_id)}
                    style={{ borderTop: "1px solid var(--line-2)", cursor: r.report_id ? "pointer" : "default" }}
                  >
                    <td style={{ padding: "8px 12px", maxWidth: 340, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {r.query || "—"}
                    </td>
                    <td style={{ padding: "8px 12px" }}>
                      <span className="mono" style={{
                        fontSize: 11, padding: "2px 8px", borderRadius: 20,
                        border: "1px solid var(--line-2)",
                        color: bad ? "var(--bad)" : done ? "var(--ok)" : "var(--warn)",
                      }}>
                        {r.status}
                      </span>
                    </td>
                    <td className="mono" style={{ padding: "8px 12px", color: "var(--text-3)" }}>
                      {r.seconds == null ? "—" : `${r.seconds}s`}
                    </td>
                    <td className="mono" style={{ padding: "8px 12px", color: "var(--text-3)" }}>
                      {r.tokens ? r.tokens.toLocaleString() : "—"}
                    </td>
                    <td className="mono" style={{ padding: "8px 12px", color: r.gaps ? "var(--warn)" : "var(--text-3)" }}>
                      {r.gaps || 0}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}
