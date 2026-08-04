import { useState } from "react";
import type { Project } from "../types";
import { Spinner } from "./ui";

const SUGGESTIONS = [
  {
    tag: "deep research",
    text: "Current approaches to reducing hallucination in retrieval-augmented generation",
  },
  {
    tag: "deep research",
    text: "Effectiveness of unsupervised RL algorithms for zero-day attack detection",
  },
  {
    tag: "deep research",
    text: "Comparison of anomaly detection benchmarks using reinforcement learning",
  },
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
  // Practitioner sources (GitHub/blogs) are disabled for now — runs are
  // scholarly-only. TODO: restore the source selector when they return.
  const scope = "papers" as const;
  const [since, setSince] = useState(0); // 0 = any time

  async function launch(q: string) {
    const text = q.trim();
    if (text.length < 8 || busy) return;
    setBusy(true);
    setError("");
    try {
      await onLaunch(text, scope, since);
    } catch (err: any) {
      setError(String(err.message ?? err));
      setBusy(false);
    }
  }

  const CUR = new Date().getFullYear();
  const periods: { label: string; year: number }[] = [
    { label: "Any time · recency prioritized", year: 0 },
    { label: `Last 2 years (since ${CUR - 2})`, year: CUR - 2 },
    { label: `Last 5 years (since ${CUR - 5})`, year: CUR - 5 },
    { label: "Since 2020", year: 2020 },
    { label: "Since 2015", year: 2015 },
  ];

  return (
    <div className="hero">
      <h2>
        Research you can <em>prove</em>
      </h2>
      <p>
        One question in — a verified report out. Veriscope searches the
        literature, then quote-checks <em>every</em> sentence against its source.
        No grounded source, no claim.
      </p>
      <div className="hero-trust">
        <span><i>✓</i> zero fabricated citations</span>
        <span><i>✓</i> click any claim → exact quote</span>
        <span><i>✓</i> refuses when it can't prove it</span>
      </div>

      <div className="composer">
        <div className="composer-head">
          <span className="composer-mode">◎ Deep research</span>
          <span className="composer-caption">— creates a project &amp; builds its corpus</span>
        </div>
        <textarea
          placeholder="Effectiveness of unsupervised RL algorithms for zero-day attack detection…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              launch(query);
            }
          }}
          disabled={busy || apiDown}
        />
        <div className="composer-foot">
          <label className="source-select" title="Restrict sources to a time window">
            <span className="source-label">Period</span>
            <select value={since} onChange={(e) => setSince(Number(e.target.value))}
                    disabled={busy || apiDown}>
              {periods.map((p) => (
                <option key={p.year} value={p.year}>{p.label}</option>
              ))}
            </select>
          </label>
          <span className="hint">
            {since
              ? `Only sources from ${since} onward — shown per source so you can verify.`
              : "Newest evidence prioritized by default; every source shows its year."}
          </span>
          <button
            className="composer-send"
            disabled={busy || apiDown || query.trim().length < 8}
            onClick={() => launch(query)}
            aria-label="Launch research"
          >
            {busy ? <Spinner /> : "→"}
          </button>
        </div>
      </div>
      {error && <p style={{ color: "var(--bad)", textAlign: "center" }}>{error}</p>}
      {apiDown && (
        <p style={{ color: "var(--warn)", textAlign: "center", fontSize: 13 }}>
          Can’t reach the API right now — if this persists, check that the backend service is running.
        </p>
      )}

      <div className="suggest-row">
        {projects.slice(0, 1).map((p) => (
          <button key={p.id} className="suggest-card" onClick={() => onOpenProject(p)}>
            <span className="tag">↺ resume</span>
            <p>{p.name}</p>
          </button>
        ))}
        {SUGGESTIONS.slice(0, projects.length ? 2 : 3).map((s) => (
          <button key={s.text} className="suggest-card" onClick={() => launch(s.text)}>
            <span className="tag">◎ {s.tag}</span>
            <p>{s.text}</p>
          </button>
        ))}
      </div>

      <div className="how-strip">
        <div className="how-step">
          <span className="how-n">1</span>
          <h4>Search the literature</h4>
          <p>arXiv, Semantic Scholar, GitHub & engineering blogs — papers and practitioner sources kept separate.</p>
        </div>
        <div className="how-step">
          <span className="how-n">2</span>
          <h4>Verify every claim</h4>
          <p>Each sentence must quote-match its source and pass an entailment check, or it's dropped.</p>
        </div>
        <div className="how-step">
          <span className="how-n">3</span>
          <h4>Read & explore</h4>
          <p>A report you can trust, a map to discover adjacent work, and a monitor that watches for new papers.</p>
        </div>
      </div>
    </div>
  );
}
