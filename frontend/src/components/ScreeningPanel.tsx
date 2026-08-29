import { useEffect, useState } from "react";
import { api } from "../api";
import type { Candidate } from "../types";
import ScreeningView from "./ScreeningView";
import { Empty, Spinner } from "./ui";
import { Icon } from "./icons";

// Persistent Screening as a first-class nav destination — so the human-in-the-
// loop "decide what enters the corpus" step is always discoverable and its
// history is tracked, not buried behind a one-off button inside Research.
type Screening = { query: string; sinceYear: number; minCitations: number };
type Past = Screening & { at: number };

const histKey = (pid: string) => `vs_screenings_${pid}`;
function loadHist(pid: string): Past[] {
  try { return JSON.parse(localStorage.getItem(histKey(pid)) || "[]"); } catch { return []; }
}
function saveHist(pid: string, list: Past[]) {
  localStorage.setItem(histKey(pid), JSON.stringify(list.slice(0, 12)));
}

export default function ScreeningPanel({
  projectId, onLaunched,
}: {
  projectId: string;
  onLaunched: () => void;
}) {
  const [query, setQuery] = useState("");
  const [sinceYear, setSinceYear] = useState(0);
  const [minCitations, setMinCitations] = useState(0);
  const [active, setActive] = useState<Screening | null>(null);
  const [hist, setHist] = useState<Past[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { setHist(loadHist(projectId)); setActive(null); }, [projectId]);

  function startScreening(s: Screening) {
    if (s.query.trim().length < 8) return;
    setActive(s);
    const next = [{ ...s, at: Date.now() }, ...loadHist(projectId).filter((h) => h.query !== s.query)];
    saveHist(projectId, next);
    setHist(next);
  }

  async function launchWithSelected(selected: Candidate[]) {
    if (!active || busy) return;
    setBusy(true); setError("");
    try {
      await api.startPipeline(projectId, active.query, "all", active.sinceYear, {
        min_citations: active.minCitations, selected_papers: selected,
      });
      setActive(null);
      onLaunched(); // hand off to Research to watch the run
    } catch (err: any) {
      setError(String(err.message ?? err));
    } finally {
      setBusy(false);
    }
  }

  if (active) {
    return (
      <div className="content-narrow" style={{ padding: 0 }}>
        {error && <p style={{ color: "var(--bad)", marginBottom: 10 }}>{error}</p>}
        <ScreeningView
          projectId={projectId} query={active.query}
          sinceYear={active.sinceYear} untilYear={0} minCitations={active.minCitations}
          onCompile={launchWithSelected} onCancel={() => setActive(null)}
        />
      </div>
    );
  }

  return (
    <div className="content-narrow" style={{ padding: 0 }}>
      <div className="view-head" style={{ marginBottom: 18 }}>
        <div className="view-head-text">
          <span className="overline">Screening · human-in-the-loop</span>
          <h2>Screen sources before you commit the corpus</h2>
          <p>
            Search arXiv &amp; Semantic Scholar, see every candidate with a keep/drop
            recommendation and a plain reason, and decide what enters this project’s
            corpus <strong>before a single PDF is downloaded</strong>. Nothing here spends
            the run budget until you compile.
          </p>
        </div>
      </div>

      <form className="panel card launch-card" onSubmit={(e) => { e.preventDefault(); startScreening({ query, sinceYear, minCitations }); }}>
        <span className="overline">New screening</span>
        <textarea
          className="textarea"
          placeholder="Research question to screen for — e.g. 'effect of spatial-hearing training in cochlear-implant users'"
          value={query} onChange={(e) => setQuery(e.target.value)}
        />
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", marginTop: 6 }}>
          <label className="sc-inp">Published after
            <input className="input" type="number" min={0} placeholder="any"
              value={sinceYear || ""} onChange={(e) => setSinceYear(Number(e.target.value) || 0)} style={{ width: 90 }} />
          </label>
          <label className="sc-inp">Min citations
            <input className="input" type="number" min={0} placeholder="0"
              value={minCitations || ""} onChange={(e) => setMinCitations(Number(e.target.value) || 0)} style={{ width: 90 }} />
          </label>
          <span style={{ flex: 1 }} />
          <button className="btn btn-accent" disabled={query.trim().length < 8}>
            <Icon.sources size={14} /> Screen sources
          </button>
        </div>
      </form>

      {hist.length > 0 ? (
        <div className="panel" style={{ padding: "6px 8px", marginTop: 18 }}>
          <div className="side-group-label" style={{ padding: "8px 12px 4px" }}>Recent screenings</div>
          {hist.map((h, i) => (
            <button key={i} className="screen-hist" onClick={() => startScreening(h)}>
              <span className="sh-q">{h.query}</span>
              <span className="sh-meta mono">
                {h.sinceYear ? `after ${h.sinceYear}` : "any year"}
                {h.minCitations ? ` · ≥${h.minCitations} cites` : ""}
              </span>
              <Icon.arrowRight size={14} />
            </button>
          ))}
        </div>
      ) : (
        <Empty glyph="▽" title="No screenings yet">
          Start one above. Every screening you run is remembered here so you can
          re-open or re-run it.
        </Empty>
      )}
      {busy && <p style={{ marginTop: 12 }}><Spinner /> launching run…</p>}
    </div>
  );
}
