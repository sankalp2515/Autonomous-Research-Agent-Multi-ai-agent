import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { MonitorData } from "../types";
import { Empty, Spinner } from "./ui";

export default function MonitorView({ projectId }: { projectId: string }) {
  const [data, setData] = useState<MonitorData | null>(null);
  const [checking, setChecking] = useState(false);
  const [newQuery, setNewQuery] = useState("");
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState<string>("");
  const pollRef = useRef<ReturnType<typeof setInterval>>();

  const refresh = useCallback(
    () => api.getMonitor(projectId).then(setData).catch(() => setData({ watches: [], alerts: [] })),
    [projectId]
  );
  useEffect(() => {
    refresh();
    return () => clearInterval(pollRef.current);
  }, [refresh]);

  function note(m: string) {
    setToast(m);
    setTimeout(() => setToast(""), 3000);
  }

  async function check() {
    setChecking(true);
    try {
      await api.checkMonitor(projectId);
      note("Checking arXiv & Semantic Scholar for new papers…");
      let tries = 0;
      clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        tries++;
        await refresh();
        if (tries >= 6) {
          clearInterval(pollRef.current);
          setChecking(false);
        }
      }, 5000);
    } catch {
      setChecking(false);
    }
  }

  async function addWatch(e: FormEvent) {
    e.preventDefault();
    if (newQuery.trim().length < 4) return;
    await api.addWatch(projectId, newQuery.trim());
    setNewQuery("");
    refresh();
  }
  async function toggle(id: string) {
    await api.toggleWatch(id);
    refresh();
  }
  async function addToCorpus(id: string) {
    setBusy(id);
    try {
      await api.addAlert(id);
      note("Added to corpus");
      await refresh();
    } finally {
      setBusy("");
    }
  }
  async function dismiss(id: string) {
    await api.dismissAlert(id);
    refresh();
  }

  if (!data) return <p><Spinner /> loading monitor…</p>;

  return (
    <div className="content-narrow">
      <div style={{ display: "flex", alignItems: "flex-start", marginBottom: 18 }}>
        <div>
          <span className="overline">Monitor agent</span>
          <p style={{ margin: "4px 0 0", color: "var(--text-2)", fontSize: 13.5, maxWidth: 520, lineHeight: 1.55 }}>
            Standing watches on your research questions. The agent re-checks
            arXiv & Semantic Scholar for newly-published papers you haven't seen,
            scores them for relevance, and surfaces them here.
          </p>
        </div>
        <span style={{ flex: 1 }} />
        <button className="btn btn-accent" onClick={check} disabled={checking}>
          {checking ? <Spinner /> : "↻ Check now"}
        </button>
      </div>

      <div className="panel card" style={{ marginBottom: 24 }}>
        <span className="overline">Watches</span>
        <div className="watch-row">
          {data.watches.map((w) => (
            <button key={w.id} className={`watch-chip ${w.active ? "on" : "off"}`}
                    onClick={() => toggle(w.id)} title={w.active ? "Active — click to pause" : "Paused — click to activate"}>
              <span className="watch-dot" /> {w.query.length > 70 ? w.query.slice(0, 68) + "…" : w.query}
            </button>
          ))}
          {data.watches.length === 0 && (
            <span style={{ fontSize: 13, color: "var(--text-3)" }}>
              No watches yet — they seed automatically from your research, or add one below.
            </span>
          )}
        </div>
        <form onSubmit={addWatch} className="ask-row" style={{ marginTop: 12 }}>
          <input className="input" placeholder="Add a topic to watch…" value={newQuery}
                 onChange={(e) => setNewQuery(e.target.value)} />
          <button className="btn btn-ghost" disabled={newQuery.trim().length < 4}>Add watch</button>
        </form>
      </div>

      <span className="overline">New papers{data.alerts.length ? ` · ${data.alerts.length}` : ""}</span>
      {data.alerts.length === 0 ? (
        <Empty glyph="◷" title="No new papers right now">
          When the agent finds papers matching your watches, they appear here.
          Hit "Check now" to run it immediately.
        </Empty>
      ) : (
        <div className="panel" style={{ marginTop: 10, overflow: "hidden" }}>
          {data.alerts.map((a) => (
            <div className="alert-item" key={a.id}>
              <div className="alert-main">
                <div className="alert-head">
                  <a href={a.url} target="_blank" rel="noreferrer" className="alert-title">
                    {a.title} <span style={{ opacity: 0.6 }}>↗</span>
                  </a>
                  <span className="alert-score" title="relevance to your watch">
                    {Math.round(a.score * 100)}% match
                  </span>
                </div>
                <div className="alert-meta">
                  {a.authors?.[0]}{a.authors?.length > 1 ? " et al." : ""}
                  {a.year ? ` · ${a.year}` : ""}
                  {a.has_pdf ? " · full text" : " · abstract"}
                </div>
                <p className="alert-abs">{a.abstract}…</p>
              </div>
              <div className="alert-actions">
                <button className="btn" style={{ fontSize: 12, padding: "5px 12px" }}
                        onClick={() => addToCorpus(a.id)} disabled={busy === a.id}>
                  {busy === a.id ? <Spinner /> : "+ Add to corpus"}
                </button>
                <button className="nb-remove" onClick={() => dismiss(a.id)}>dismiss</button>
              </div>
            </div>
          ))}
        </div>
      )}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
