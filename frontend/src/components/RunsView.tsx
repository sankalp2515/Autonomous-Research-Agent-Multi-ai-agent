import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import type { Run, RunStatus } from "../types";
import { Empty, Spinner, statusStamp } from "./ui";

const NODES = ["clarify", "plan", "research", "outline", "draft_sections", "assemble", "build_graph"];
const NODE_LABELS: Record<string, string> = {
  clarify: "clarify", plan: "plan", research: "research", outline: "outline",
  draft_sections: "draft + gate", assemble: "assemble", build_graph: "graph",
};

function Timeline({ status }: { status: RunStatus }) {
  const liveNode = status.live?.node ?? status.current_node;
  const doneIdx =
    status.status === "completed" || status.status === "completed_with_gaps"
      ? NODES.length
      : Math.max(NODES.indexOf(liveNode), 0);
  return (
    <div className="timeline">
      {NODES.map((node, i) => {
        let cls = "";
        if (status.status === "failed" && i === doneIdx) cls = "failed";
        else if (i < doneIdx) cls = "done";
        else if (i === doneIdx && ["running", "queued"].includes(status.status)) cls = "active";
        else if (i <= doneIdx) cls = "done";
        return (
          <div key={node} className={`t-node ${cls}`}>
            <div className="t-dot" />
            <div className="t-label">{NODE_LABELS[node]}</div>
          </div>
        );
      })}
    </div>
  );
}

export default function RunsView({
  projectId,
  onOpenReport,
}: {
  projectId: string;
  onOpenReport: (reportId: string) => void;
}) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [statuses, setStatuses] = useState<Record<string, RunStatus>>({});
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [resume, setResume] = useState<{
    title: string; verified: number; total: number;
    gaps: { q: string; note: string }[]; reportId: string;
  } | null>(null);
  const [clarifyQs, setClarifyQs] = useState<string[] | null>(null);
  const [clarifyAns, setClarifyAns] = useState<string[]>([]);
  const [clarifying, setClarifying] = useState(false);
  const [rejected, setRejected] = useState("");

  const activeRunId = runs.find((r) => ["queued", "running"].includes(r.status))?.id;

  // Live SSE stream for the active run — sub-second progress pushes feed the
  // activity log, instead of waiting on the poll interval.
  useEffect(() => {
    if (!activeRunId) return;
    const stop = api.streamStatus(
      activeRunId,
      (msg) =>
        setStatuses((prev) => {
          const cur = prev[activeRunId] ?? ({
            run_id: activeRunId, status: "running", current_node: "", error: "",
            report_id: null, budgets_spent: {}, live: null, events: [],
          } as RunStatus);
          const events = [...(cur.events ?? []), { node: msg?.node ?? "", status: msg?.status ?? "", at: Date.now() / 1000, message: msg?.message }].slice(-30);
          return { ...prev, [activeRunId]: { ...cur, live: msg, events } };
        }),
      () => refresh()
    );
    return stop;
  }, [activeRunId]);

  async function refresh() {
    try {
      const list = await api.listRuns(projectId);
      setRuns(list);
      const active = list.filter((r) => ["queued", "running"].includes(r.status));
      const detailed = await Promise.all(
        list.slice(0, 6).map((r) => api.runStatus(r.id).catch(() => null))
      );
      setStatuses((prev) => {
        const next = { ...prev };
        for (const s of detailed) if (s) next[s.run_id] = s;
        return next;
      });
      return active.length > 0;
    } catch {
      return false;
    }
  }

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let alive = true;
    async function loop() {
      const hasActive = await refresh();
      if (!alive) return;
      timer = setTimeout(loop, hasActive ? 2500 : 12000);
    }
    loop();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // Resume panel: load the latest completed report's summary + open gaps.
  useEffect(() => {
    const latest = runs.find((r) => r.report_id);
    if (!latest?.report_id) {
      setResume(null);
      return;
    }
    if (resume?.reportId === latest.report_id) return;
    let alive = true;
    api
      .getReport(latest.report_id)
      .then((rep) => {
        if (!alive) return;
        const gaps = rep.sections
          .filter((s) => s.status === "gap")
          .map((s) => ({ q: s.sub_question, note: s.gap_note }));
        setResume({
          title: rep.title,
          verified: rep.confidence.sections_verified ?? 0,
          total: rep.confidence.sections_total ?? rep.sections.length,
          gaps,
          reportId: latest.report_id!,
        });
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs]);

  async function startWith(q: string) {
    if (!q.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      await api.startPipeline(projectId, q.trim());
      setQuery("");
      await refresh();
    } catch (err: any) {
      setError(String(err.message ?? err));
    } finally {
      setBusy(false);
    }
  }

  async function launchRefined() {
    const extras = (clarifyQs ?? [])
      .map((q, i) => (clarifyAns[i]?.trim() ? `- ${q} → ${clarifyAns[i].trim()}` : ""))
      .filter(Boolean);
    const augmented = extras.length
      ? `${query.trim()}\n\nAdditional context:\n${extras.join("\n")}`
      : query.trim();
    setClarifyQs(null);
    await startWith(augmented);
  }

  // Launch flow: every run first passes through clarify, which (a) rejects
  // off-topic / non-research asks and (b) surfaces clarifying questions to
  // sharpen the research before it runs (Elicit-style).
  async function start(e: FormEvent) {
    e.preventDefault();
    if (query.trim().length < 8 || clarifying || busy) return;
    setClarifying(true);
    setError("");
    setRejected("");
    setClarifyQs(null);
    try {
      const r = await api.clarify(projectId, query.trim());
      if (!r.allowed) {
        setRejected(r.reason);
        return;
      }
      if (r.questions.length) {
        setClarifyQs(r.questions);
        setClarifyAns(r.questions.map(() => ""));
        return;
      }
      await startWith(query.trim());
    } catch (err: any) {
      setError(String(err.message ?? err));
    } finally {
      setClarifying(false);
    }
  }

  return (
    <div className="content-narrow">
      {resume && (
        <div className="resume">
          <span className="overline">Continue where you left off</span>
          <h3>{resume.title}</h3>
          <p className="resume-sub">Your most recent verified report in this project.</p>
          <div className="resume-stats">
            <div className="resume-stat">
              <b>{resume.verified}/{resume.total}</b>
              <span>sections grounded</span>
            </div>
            <div className="resume-stat">
              <b>{resume.gaps.length}</b>
              <span>open gaps</span>
            </div>
          </div>
          <button className="btn btn-ghost" style={{ padding: "6px 14px", fontSize: 12.5 }}
                  onClick={() => onOpenReport(resume.reportId)}>
            Open report →
          </button>
          {resume.gaps.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div className="resume-gaps-label">
                Open questions — research a gap in one click
              </div>
              {resume.gaps.map((g, i) => (
                <button key={i} className="gap-chip" onClick={() => startWith(g.q)}
                        disabled={busy} title={g.note || g.q}>
                  <span className="gi">◎</span>{" "}
                  {g.q.length > 96 ? g.q.slice(0, 94) + "…" : g.q}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <form onSubmit={start} className="panel card" style={{ marginBottom: 26 }}>
        <span className="overline">New deep research run</span>
        <textarea
          className="textarea"
          style={{ marginTop: 10 }}
          placeholder="Research question — e.g. 'What are the current approaches to reducing hallucination in retrieval-augmented generation, and what are their trade-offs?'"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12, gap: 10 }}>
          <span style={{ fontSize: 12, color: "var(--text-3)" }}>
            clarify → plan → research → outline → draft + verification gate → assemble
          </span>
          <button className="btn btn-accent" disabled={busy || clarifying || query.trim().length < 8}>
            {clarifying ? <Spinner /> : busy ? <Spinner /> : "Launch run"}
          </button>
        </div>
        {rejected && (
          <div className="reject-box">
            <strong>Not a research question.</strong> {rejected}
          </div>
        )}
        {clarifyQs && (
          <div className="clarify-box">
            <span className="overline">A couple of questions to sharpen your research — answer what helps</span>
            {clarifyQs.map((q, i) => (
              <div key={i} className="clarify-q">
                <p>{q}</p>
                <input className="input" placeholder="Your answer…" value={clarifyAns[i] ?? ""}
                       onChange={(e) => setClarifyAns((a) => a.map((x, xi) => (xi === i ? e.target.value : x)))} />
              </div>
            ))}
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 10 }}>
              <button type="button" className="btn btn-ghost" onClick={() => setClarifyQs(null)}>Cancel</button>
              <button type="button" className="btn btn-accent" onClick={launchRefined} disabled={busy}>
                {busy ? <Spinner /> : "Launch with context →"}
              </button>
            </div>
          </div>
        )}
        {error && <p style={{ color: "var(--bad)", marginBottom: 0 }}>{error}</p>}
      </form>

      {runs.length === 0 ? (
        <Empty glyph="⟁" title="No runs yet">
          A run searches arXiv, Semantic Scholar, GitHub and whitelisted blogs,
          ingests everything into this project's corpus, and drafts a report
          where every claim must survive the verification gate.
        </Empty>
      ) : (
        <div className="panel">
          {runs.map((run) => {
            const st = statuses[run.id];
            return (
              <div key={run.id} className="run-row">
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <p className="run-query" style={{ flex: 1 }}>{run.query}</p>
                  {statusStamp(run.status)}
                </div>
                {st && <Timeline status={st} />}
                {["queued", "running"].includes(run.status) && (() => {
                  // De-duplicate consecutive identical messages into a feed.
                  const msgs: string[] = [];
                  for (const ev of st?.events ?? []) {
                    const m = ev.message || ev.node;
                    if (m && m !== msgs[msgs.length - 1]) msgs.push(m);
                  }
                  const recent = msgs.slice(-6);
                  if (!recent.length) recent.push("Starting…");
                  return (
                    <div className="live-feed">
                      {recent.map((m, i) => {
                        const current = i === recent.length - 1;
                        return (
                          <div key={i} className={`live-line ${current ? "current" : "past"}`}>
                            <span className={current ? "live-pulse" : "live-dot"} />
                            <span className="live-text">{m}</span>
                            {current && (
                              <span className="live-secs mono">{run.budgets_spent?.seconds ?? 0}s</span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  );
                })()}
                <div style={{ display: "flex", gap: 18, alignItems: "center", marginTop: 8 }}>
                  <span className="mono" style={{ fontSize: 11, color: "var(--ink-faint)" }}>
                    {run.budgets_spent?.llm_calls ?? 0} llm calls ·{" "}
                    {run.budgets_spent?.seconds ?? 0}s
                    {st?.live?.sections_total
                      ? ` · sections ${st.live.sections_done}/${st.live.sections_total}`
                      : ""}
                  </span>
                  {st?.live?.coverage_notes?.length ? (
                    <span className="coverage-note" style={{ margin: 0 }}>
                      {st.live.coverage_notes[st.live.coverage_notes.length - 1]}
                    </span>
                  ) : null}
                  {run.report_id && (
                    <button
                      className="btn btn-ghost"
                      style={{ marginLeft: "auto", padding: "5px 12px" }}
                      onClick={() => onOpenReport(run.report_id!)}
                    >
                      Open report →
                    </button>
                  )}
                </div>
                {st?.error && (
                  <p style={{ color: "var(--failed)", fontSize: 13, marginBottom: 0 }}>{st.error}</p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
