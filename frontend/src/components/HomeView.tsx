import { useState } from "react";
import type { Project } from "../types";
import { Spinner } from "./ui";
import { Icon } from "./icons";

const SUGGESTIONS = [
  "Current approaches to reducing hallucination in retrieval-augmented generation",
  "Effectiveness of unsupervised RL algorithms for zero-day attack detection",
  "Comparison of anomaly detection benchmarks using reinforcement learning",
];

export default function HomeView({
  projects,
  apiDown,
  onLaunch,
  onOpenProject,
}: {
  projects: Project[];
  apiDown: boolean;
  onLaunch: (query: string, scope: "all" | "papers", sinceYear: number) => Promise<void>;
  onOpenProject: (p: Project) => void;
}) {
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [since, setSince] = useState(0);

  async function launch(q: string) {
    const text = q.trim();
    if (text.length < 8 || busy) return;
    setBusy(true);
    setError("");
    try {
      await onLaunch(text, "papers", since);
    } catch (err: any) {
      setError(String(err.message ?? err));
      setBusy(false);
    }
  }

  const currentYear = new Date().getFullYear();
  const periods = [
    { label: "Any time · recency prioritized", year: 0 },
    { label: `Last 2 years (since ${currentYear - 2})`, year: currentYear - 2 },
    { label: `Last 5 years (since ${currentYear - 5})`, year: currentYear - 5 },
    { label: "Since 2020", year: 2020 },
  ];

  return (
    <div className="home home-desk rise-in">
      <div className="home-intro">
        <div>
          <span className="home-eyebrow"><Icon.check size={13} /> Verifiable research workspace</span>
          <h1>Start with a question.<br /><em>Leave with proof.</em></h1>
          <p className="home-sub">
            Veriscope finds the literature, builds your project corpus, and links every conclusion to the evidence behind it.
          </p>
        </div>
        <aside className="home-proof" aria-label="Evidence standard">
          <span className="overline">The evidence standard</span>
          <p><Icon.check size={14} /> Every claim is quote-checked.</p>
          <p><Icon.check size={14} /> Every source stays inspectable.</p>
          <p><Icon.check size={14} /> Gaps are reported honestly.</p>
        </aside>
      </div>

      <section className="composer home-launch" aria-label="Start a research project">
        <div className="home-launch-head">
          <span className="home-launch-number">01</span>
          <div>
            <span className="overline">Frame your research question</span>
            <p>A project, source library, and verified report will be created for you.</p>
          </div>
          <span className="home-launch-mode"><Icon.research size={14} /> Deep research</span>
        </div>
        <textarea
          placeholder="What would you like to investigate?"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); launch(query); } }}
          disabled={busy || apiDown}
        />
        <div className="composer-foot">
          <label className="source-select" title="Restrict sources to a time window">
            <span className="source-label">Evidence period</span>
            <select value={since} onChange={(e) => setSince(Number(e.target.value))} disabled={busy || apiDown}>
              {periods.map((p) => <option key={p.year} value={p.year}>{p.label}</option>)}
            </select>
          </label>
          <span className="hint">{since ? `Sources from ${since} onward.` : "Newest evidence is prioritized by default."}</span>
          <button className="composer-send" disabled={busy || apiDown || query.trim().length < 8} onClick={() => launch(query)}>
            {busy ? <Spinner /> : <>Start research <Icon.arrowRight size={16} /></>}
          </button>
        </div>
      </section>

      {error && <p className="home-message home-error">{error}</p>}
      {apiDown && <p className="home-message home-warning">Can’t reach the API right now — check that the backend service is running.</p>}

      <div className="home-prompt-row">
        <span className="overline">Or begin with a prompt</span>
        <div className="home-prompt-list">
          {SUGGESTIONS.map((suggestion) => (
            <button key={suggestion} className="home-prompt" onClick={() => setQuery(suggestion)} disabled={busy || apiDown}>
              <span>◎</span>{suggestion}
            </button>
          ))}
        </div>
      </div>
      {projects.length > 0 && (
        <button className="home-project-link" onClick={() => onOpenProject(projects[0])}>
          Continue in {projects[0].name} <Icon.arrowRight size={14} />
        </button>
      )}
    </div>
  );
}
