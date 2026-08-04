import { useEffect, useState } from "react";
import { api } from "../api";
import { Empty, Spinner } from "./ui";

type Mem = { id: string; kind: string; text: string; source_ref: string; created_at: string };

export default function MemoryView({ projectId }: { projectId: string }) {
  const [mems, setMems] = useState<Mem[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [recall, setRecall] = useState<{ text: string; kind: string; score: number }[] | null>(null);
  const [adding, setAdding] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    setLoading(true);
    try {
      setMems(await api.listMemory(projectId));
    } catch {
      /* offline */
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function doRecall() {
    if (q.trim().length < 2) return;
    try {
      const r = await api.recallMemory(projectId, q.trim());
      setRecall(r.results);
    } catch {
      setRecall([]);
    }
  }

  async function add() {
    if (adding.trim().length < 3 || busy) return;
    setBusy(true);
    setError("");
    try {
      await api.addMemory(projectId, adding.trim(), "preference");
      setAdding("");
      await refresh();
    } catch (err: any) {
      // Never fail silently: a broken write used to look like "nothing happened".
      setError(String(err?.message ?? err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="content-narrow">
      <div className="panel card" style={{ marginBottom: 20 }}>
        <span className="overline">What this project remembers</span>
        <p style={{ fontSize: 13, color: "var(--text-3)", margin: "6px 0 12px" }}>
          Cross-session memory — a summary of every completed run plus anything you pin.
          Used to steer new research (recalled at planning time), never as answer evidence.
        </p>
        <div style={{ display: "flex", gap: 8 }}>
          <input className="input" placeholder="Recall — e.g. 'what did we find on hallucination?'"
                 value={q} onChange={(e) => setQ(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && doRecall()} />
          <button className="btn btn-accent" onClick={doRecall}>Recall</button>
        </div>
        {recall && (
          <div style={{ marginTop: 12 }}>
            {recall.length === 0 ? (
              <p style={{ fontSize: 13, color: "var(--text-3)" }}>No relevant memory yet.</p>
            ) : recall.map((r, i) => (
              <div key={i} className="nb-item" style={{ padding: "10px 0" }}>
                <p className="nb-text" style={{ margin: 0 }}>{r.text}</p>
                <span className="mono" style={{ fontSize: 11, color: "var(--text-3)" }}>
                  {r.kind}{r.score ? ` · ${r.score.toFixed(2)}` : ""}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="panel card" style={{ marginBottom: 20 }}>
        <span className="overline">Pin a fact or preference</span>
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <input className="input" placeholder="e.g. 'Prefer sources from 2023 onward for this project'"
                 value={adding} onChange={(e) => setAdding(e.target.value)}
                 disabled={busy}
                 onKeyDown={(e) => e.key === "Enter" && add()} />
          <button className="btn btn-ghost" onClick={add} disabled={busy || adding.trim().length < 3}>
            {busy ? <Spinner /> : "Add"}
          </button>
        </div>
        {error && (
          <p style={{ color: "var(--bad)", fontSize: 13, margin: "10px 0 0" }}>
            Couldn’t save: {error}
          </p>
        )}
      </div>

      {loading ? (
        <p><Spinner /> loading memory…</p>
      ) : mems.length === 0 ? (
        <Empty glyph="◈" title="No memory yet">
          Run some research — each completed run leaves an episodic summary here that
          future runs recall.
        </Empty>
      ) : (
        <div className="panel">
          {mems.map((m) => (
            <div key={m.id} className="nb-item">
              <p className="nb-text">{m.text}</p>
              <div className="nb-foot">
                <span className="nb-src">
                  <span className="mono" style={{ fontSize: 10.5 }}>{m.kind}</span>
                  {m.source_ref ? ` · ${m.source_ref}` : ""} · {new Date(m.created_at).toLocaleDateString()}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
