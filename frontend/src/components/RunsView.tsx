import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Candidate, Run, RunStatus } from "../types";
import { Spinner, statusStamp } from "./ui";
import { Icon } from "./icons";
import ScreeningView from "./ScreeningView";
import { RunLive, formatDuration } from "./RunLive";

export default function RunsView({
  projectId,
  onOpenReport,
  initial,
  onInitialConsumed,
}: {
  projectId: string;
  onOpenReport: (reportId: string) => void;
  initial?: { text: string; scope: "all" | "papers"; sinceYear: number } | null;
  onInitialConsumed?: () => void;
}) {
  const [runs, setRuns] = useState<Run[]>([]);
  // Runs we have asked to stop but whose worker has not yet reached its
  // cancellation checkpoint. Local, because the row must stop offering
  // "Stop" the instant it is pressed rather than one poll later.
  const [stopping, setStopping] = useState<Set<string>>(new Set());
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
  const [clarifyMeta, setClarifyMeta] = useState<{ scope_note?: string; since_year?: number; until_year?: number; min_citations?: number; field?: string } | null>(null);
  const [nextQs, setNextQs] = useState<string[]>([]);
  const [launchOpts, setLaunchOpts] = useState<{ scope: "all" | "papers" | "library"; sinceYear: number }>({ scope: "all", sinceYear: 0 });
  const consumedInitial = useRef(false);
  const [showForm, setShowForm] = useState(false);
  const [screening, setScreening] = useState<{ query: string; sinceYear: number; untilYear: number; minCitations: number } | null>(null);

  // Three ways to run, one of them the default. They used to hide inside a
  // "Research options" disclosure next to the launch button — so the mode was
  // invisible until you went looking, and the only way to pick one was to press
  // a DIFFERENT launch button, which is why the footer never lined up.
  const RUN_MODES = [
    {
      id: "all" as const, label: "Search the literature", icon: Icon.research,
      note: "Clarify scope, search arXiv and Semantic Scholar, then verify the report.",
      title: "Search for new sources and build the corpus from what it finds",
    },
    {
      id: "library" as const, label: "Library + search", icon: Icon.notebook,
      note: "Reads the papers already in this project, then searches for new sources to fill the gaps.",
      title: "Include the papers already in this project (your uploads + prior runs) AND search for new sources to fill any gaps",
    },
    {
      id: "screen" as const, label: "Screen sources first", icon: Icon.sources,
      note: "Review the candidate papers and choose which ones the run may read.",
      title: "See the candidates and select the corpus yourself before the run starts",
    },
  ];
  const [mode, setMode] = useState<"all" | "library" | "screen">("all");

  // The evidence window belongs beside the question, not only on the home
  // composer: a run started from inside a project could not set it at all.
  const currentYear = new Date().getFullYear();
  const PERIODS = [
    { label: "Any time · recency prioritized", year: 0 },
    { label: `Last 2 years (since ${currentYear - 2})`, year: currentYear - 2 },
    { label: `Last 5 years (since ${currentYear - 5})`, year: currentYear - 5 },
    { label: "Since 2020", year: 2020 },
  ];

  const activeRunId = runs.find((r) => ["queued", "running"].includes(r.status))?.id;
  const loadedStatus = useRef<Set<string>>(new Set());

  // Live SSE stream for the active run — sub-second progress pushes.
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
          // Keep the payload whole: `kind` and the running counters are what
          // the feed groups, filters and tallies on. The old handler copied
          // four fields and dropped the rest on the floor.
          const events = [...(cur.events ?? []), { ...(msg ?? {}), at: msg?.at ?? Date.now() / 1000 }].slice(-200);
          return { ...prev, [activeRunId]: { ...cur, live: msg, events } };
        }),
      () => refresh()
    );
    return stop;
  }, [activeRunId]);

  async function stopRun(runId: string) {
    // Optimistic, and safe to be: the only outcomes are "stopped" and "already
    // finished". Both mean this row must stop offering a stop button.
    setStopping((prev) => new Set(prev).add(runId));
    try {
      await api.cancelRun(runId);
    } catch {
      // A run that finished between render and click 409s. Nothing to undo —
      // refresh() below reconciles the row to whatever the server says.
    }
    await refresh();
  }

  async function refresh() {
    try {
      const list = await api.listRuns(projectId);
      setRuns(list);
      const active = list.filter((r) => ["queued", "running"].includes(r.status));
      // "cancelled" belongs here or a stopped run is re-fetched forever:
      // nothing is driving it, so its status can never change again.
      const terminal = new Set(["completed", "completed_with_gaps", "failed",
                                "rejected", "budget_exhausted", "cancelled"]);
      const targets = list.slice(0, 6).filter((r) => !terminal.has(r.status) || !loadedStatus.current.has(r.id));
      const detailed = await Promise.all(targets.map((r) => api.runStatus(r.id).catch(() => null)));
      setStatuses((prev) => {
        const next = { ...prev };
        for (const s of detailed) {
          if (s) {
            next[s.run_id] = s;
            if (terminal.has(s.status)) loadedStatus.current.add(s.run_id);
          }
        }
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
    return () => { alive = false; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // Resume panel: latest completed report summary + open gaps.
  useEffect(() => {
    const latest = runs.find((r) => r.report_id);
    if (!latest?.report_id) { setResume(null); return; }
    if (resume?.reportId === latest.report_id) return;
    let alive = true;
    setNextQs([]);
    api.getReport(latest.report_id).then((rep) => {
      if (!alive) return;
      const gaps = rep.sections.filter((s) => s.status === "gap").map((s) => ({ q: s.sub_question, note: s.gap_note }));
      setResume({
        title: rep.title,
        verified: rep.confidence.sections_verified ?? 0,
        total: rep.confidence.sections_total ?? rep.sections.length,
        gaps, reportId: latest.report_id!,
      });
    }).catch(() => {});
    api.getNextQuestions(latest.report_id).then((r) => alive && setNextQs(r.questions ?? [])).catch(() => {});
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs]);

  async function startWith(q: string, opts = launchOpts) {
    if (!q.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      // Pass parsed constraints as STRUCTURED values (not just prose), so the
      // stated time window / citation floor are actually enforced.
      const sinceYear = Math.max(opts.sinceYear || 0, clarifyMeta?.since_year || 0);
      await api.startPipeline(projectId, q.trim(), opts.scope, sinceYear, {
        until_year: clarifyMeta?.until_year || 0,
        min_citations: clarifyMeta?.min_citations || 0,
      });
      setQuery("");
      await refresh();
    } catch (err: any) {
      setError(String(err.message ?? err));
    } finally {
      setBusy(false);
    }
  }

  function openScreening() {
    if (query.trim().length < 8) return;
    // /screen re-parses year/citation constraints from the query itself; we pass
    // the UI time-window floor. Constraints are shown + enforced in the table.
    setScreening({ query: query.trim(), sinceYear: launchOpts.sinceYear || 0, untilYear: 0, minCitations: 0 });
  }

  async function launchWithSelected(sel: Candidate[]) {
    if (!screening || busy) return;
    setBusy(true);
    setError("");
    try {
      await api.startPipeline(
        projectId, screening.query, launchOpts.scope,
        Math.max(launchOpts.sinceYear || 0, screening.sinceYear || 0),
        { until_year: screening.untilYear, min_citations: screening.minCitations, selected_papers: sel }
      );
      setScreening(null);
      setShowForm(false);
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
    const augmented = extras.length ? `${query.trim()}\n\nAdditional context:\n${extras.join("\n")}` : query.trim();
    setClarifyQs(null);
    await startWith(augmented);
  }

  // Every run first passes through clarify: rejects off-topic asks and surfaces
  // clarifying questions. Shared by form submit and the home-composer hand-off.
  async function runClarify(text: string, opts = launchOpts) {
    if (text.trim().length < 8 || clarifying || busy) return;
    setClarifying(true);
    setError(""); setRejected(""); setClarifyQs(null);
    try {
      const r = await api.clarify(projectId, text.trim());
      if (!r.allowed) { setRejected(r.reason); return; }
      setClarifyMeta({ scope_note: r.scope_note, since_year: r.since_year, until_year: r.until_year, min_citations: r.min_citations, field: r.field });
      // Pause ONLY for real ambiguity or an out-of-scope warning. A scope note
      // alone no longer blocks: most notes are informational ("a citation floor
      // was dropped"), and stopping the run to show one made clarification feel
      // mandatory even after the questions were fixed. An out-of-scope question
      // still pauses, because launching that blindly wastes 40 minutes.
      const mustAsk = r.questions.length > 0;
      const mustWarn = r.in_scope === false && !!r.scope_note;
      if (mustAsk || mustWarn) {
        setClarifyQs(r.questions);
        setClarifyAns(r.questions.map(() => ""));
        return;
      }
      await startWith(text.trim(), opts);
    } catch (err: any) {
      setError(String(err.message ?? err));
    } finally {
      setClarifying(false);
    }
  }

  async function start(e: FormEvent) {
    e.preventDefault();
    if (mode === "screen") { openScreening(); return; }
    await runClarify(query, { scope: mode, sinceYear: launchOpts.sinceYear });
  }

  useEffect(() => {
    if (!initial || consumedInitial.current) return;
    consumedInitial.current = true;
    setQuery(initial.text);
    const opts = { scope: initial.scope, sinceYear: initial.sinceYear };
    setLaunchOpts(opts);
    onInitialConsumed?.();
    runClarify(initial.text, opts);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  if (screening) {
    return (
      <div style={{ padding: 0 }}>
        <ScreeningView
          projectId={projectId} query={screening.query}
          sinceYear={screening.sinceYear} untilYear={screening.untilYear} minCitations={screening.minCitations}
          onCompile={launchWithSelected} onCancel={() => setScreening(null)}
        />
      </div>
    );
  }

  return (
    <div className="content-narrow research-page" style={{ padding: 0 }}>
      {resume && (
        <div className="resume rise-in">
          <span className="overline">Continue where you left off</span>
          <h3>{resume.title}</h3>
          <p className="resume-sub">Your most recent verified report in this project.</p>
          <div className="resume-stats">
            <div className="resume-stat"><b>{resume.verified}/{resume.total}</b><span>sections grounded</span></div>
            <div className="resume-stat"><b>{resume.gaps.length}</b><span>open gaps</span></div>
          </div>
          <button className="btn" onClick={() => onOpenReport(resume.reportId)}>
            Open report <Icon.arrowRight size={14} />
          </button>
          {resume.gaps.length > 0 && (
            <div style={{ marginTop: 18 }}>
              <div className="resume-gaps-label">Open questions — research a gap in one click</div>
              {resume.gaps.map((g, i) => (
                <button key={i} className="gap-chip" onClick={() => startWith(g.q)} disabled={busy} title={g.note || g.q}>
                  <span className="gi">◎</span> {g.q.length > 96 ? g.q.slice(0, 94) + "…" : g.q}
                </button>
              ))}
            </div>
          )}
          {nextQs.length > 0 && (
            <div style={{ marginTop: 18 }}>
              <div className="resume-gaps-label">You might also investigate</div>
              <div className="nextq-row">
                {nextQs.map((q, i) => (
                  <button key={i} className="nextq-card" onClick={() => { setQuery(q); setShowForm(true); }} disabled={busy}>
                    <span className="nextq-tag">◎ suggested</span>
                    <p>{q}</p>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {activeRunId && !showForm && (
        <button className="btn btn-ghost" style={{ marginBottom: 20 }} onClick={() => setShowForm(true)}>
          <Icon.plus size={14} /> Start another run
        </button>
      )}

      {(!activeRunId || showForm) && (
        <form onSubmit={start} className="panel card launch-card research-composer">
          <div className="research-composer-head">
            <div>
              <span className="overline">Research in this project</span>
              <p>Search for new evidence and create a verified report.</p>
            </div>
            {resume && <span className="composer-project-state">Latest report ready</span>}
          </div>
          <textarea
            className="textarea"
            placeholder="Research question — e.g. 'What are current approaches to reducing hallucination in retrieval-augmented generation, and what are their trade-offs?'"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="launch-controls">
            <div className="launch-field">
              <span className="launch-field-label">Run mode</span>
              <div className="seg" role="radiogroup" aria-label="Run mode">
                {RUN_MODES.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    role="radio"
                    aria-checked={mode === m.id}
                    className={`seg-btn ${mode === m.id ? "on" : ""}`}
                    title={m.title}
                    onClick={() => setMode(m.id)}
                    disabled={busy || clarifying}
                  >
                    <m.icon size={13} /> {m.label}
                  </button>
                ))}
              </div>
            </div>
            <label className="launch-field" title="Restrict sources to a time window">
              <span className="launch-field-label">Evidence period</span>
              <select
                value={launchOpts.sinceYear}
                onChange={(e) => setLaunchOpts((o) => ({ ...o, sinceYear: Number(e.target.value) }))}
                disabled={busy || clarifying}
              >
                {PERIODS.map((pd) => <option key={pd.year} value={pd.year}>{pd.label}</option>)}
              </select>
            </label>
          </div>
          <div className="launch-foot">
            <span className="launch-pipeline">
              {RUN_MODES.find((m) => m.id === mode)!.note}
              {launchOpts.sinceYear ? ` Sources from ${launchOpts.sinceYear} onward.` : ""}
            </span>
            <button className="btn btn-accent" disabled={busy || clarifying || query.trim().length < 8}>
              {clarifying || busy ? <Spinner /> : (
                <>{mode === "screen" ? "Screen sources" : "Launch run"} <Icon.arrowRight size={14} /></>
              )}
            </button>
          </div>
          {rejected && (
            <div className="reject-box"><strong>Not a research question.</strong> {rejected}</div>
          )}
          {clarifyQs && (
            <div className="clarify-box">
              {clarifyMeta?.scope_note && (
                <div className="scope-warn"><Icon.about size={15} /> {clarifyMeta.scope_note}</div>
              )}
              {(clarifyMeta?.since_year || clarifyMeta?.until_year || clarifyMeta?.min_citations || clarifyMeta?.field) && (
                <div className="cchip-row">
                  {clarifyMeta.field && <span className="cchip">{clarifyMeta.field}</span>}
                  {clarifyMeta.since_year && clarifyMeta.until_year
                    ? <span className="cchip">{clarifyMeta.since_year}–{clarifyMeta.until_year}</span>
                    : clarifyMeta.since_year ? <span className="cchip">after {clarifyMeta.since_year}</span>
                    : clarifyMeta.until_year ? <span className="cchip">before {clarifyMeta.until_year}</span> : null}
                  {clarifyMeta.min_citations ? <span className="cchip gold">≥ {clarifyMeta.min_citations} citations</span> : null}
                  <span className="cchip-note">parsed from your question · enforced</span>
                </div>
              )}
              <span className="overline">
                {clarifyQs.length
                  ? "A couple of questions to sharpen your research — answer what helps"
                  : "Confirm and launch"}
              </span>
              {clarifyQs.map((q, i) => (
                <div key={i} className="clarify-q">
                  <p>{q}</p>
                  <input className="input" placeholder="Your answer…" value={clarifyAns[i] ?? ""}
                         onChange={(e) => setClarifyAns((a) => a.map((x, xi) => (xi === i ? e.target.value : x)))} />
                </div>
              ))}
              <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 12 }}>
                <button type="button" className="btn btn-ghost" onClick={() => setClarifyQs(null)}>Cancel</button>
                <button type="button" className="btn btn-accent" onClick={launchRefined} disabled={busy}>
                  {busy ? <Spinner /> : <>Launch with context <Icon.arrowRight size={14} /></>}
                </button>
              </div>
            </div>
          )}
          {error && <p style={{ color: "var(--bad)", marginTop: 12 }}>{error}</p>}
        </form>
      )}

      {runs.length === 0 ? (
        <div className="research-empty">
          <span className="research-empty-mark">01</span>
          <div><b>Your research history will appear here.</b><p>Start with one focused question; you can refine the scope before it runs.</p></div>
        </div>
      ) : (
        <div className="run-history panel">
          <div className="run-history-head"><span className="overline">Research history</span><span>{runs.length} {runs.length === 1 ? "run" : "runs"}</span></div>
          {runs.map((run) => {
            const st = statuses[run.id];
            return (
              <div key={run.id} className={`run-row ${["queued", "running"].includes(run.status) ? "active" : "complete"}`}>
                <div className="run-head">
                  <p className="run-query">{run.query}</p>
                  {statusStamp(stopping.has(run.id) && run.status !== "cancelled"
                    ? "cancelling" : run.status)}
                  {["queued", "running"].includes(run.status) && (
                    <button
                      className="btn btn-ghost run-stop"
                      onClick={() => stopRun(run.id)}
                      disabled={stopping.has(run.id)}
                      title="Stop this run — keeps the papers already ingested"
                    >
                      <Icon.x size={13} />
                      {stopping.has(run.id) ? "Stopping…" : "Stop"}
                    </button>
                  )}
                </div>
                {["queued", "running"].includes(run.status) && <RunLive run={run} status={st} />}
                <div className="run-foot">
                  <span className="mono">
                    {/* Server-computed duration. budgets_spent.seconds is only
                        written at a node checkpoint, so it under-reports a
                        finished run by however long its last node took. */}
                    {formatDuration(run.elapsed_seconds ?? run.budgets_spent?.seconds ?? 0)} elapsed
                    {run.budgets_spent?.llm_calls ? ` · ${run.budgets_spent.llm_calls} llm calls` : ""}
                  </span>
                  {run.report_id && (
                    <button className="btn btn-ghost" style={{ marginLeft: "auto" }} onClick={() => onOpenReport(run.report_id!)}>
                      Open report <Icon.arrowRight size={14} />
                    </button>
                  )}
                </div>
                {st?.error && <p style={{ color: "var(--bad)", fontSize: 13, marginTop: 6 }}>{st.error}</p>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
