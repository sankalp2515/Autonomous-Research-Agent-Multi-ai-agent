import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { Candidate, ScreenResult } from "../types";
import { Spinner } from "./ui";
import { Icon } from "./icons";

const keyOf = (c: Candidate) => c.arxiv_id || c.doi || c.external_id || c.title;

// Human-in-the-loop screening: the researcher sees EVERY candidate the search
// found, with a keep/drop recommendation and a plain reason, and decides what
// enters the corpus BEFORE anything is downloaded. Transparent (no hidden cap)
// and simple ("accept recommendations" is one click).
export default function ScreeningView({
  projectId, query, sinceYear, untilYear, minCitations, onCompile, onCancel,
}: {
  projectId: string;
  query: string;
  sinceYear: number;
  untilYear: number;
  minCitations: number;
  onCompile: (selected: Candidate[]) => void;
  onCancel: () => void;
}) {
  const [data, setData] = useState<ScreenResult | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  useEffect(() => {
    let alive = true;
    api.screen(projectId, query, { since_year: sinceYear, until_year: untilYear, min_citations: minCitations })
      .then((d) => {
        if (!alive) return;
        setData(d);
        setSelected(new Set(d.candidates.filter((c) => c.recommend === "keep").map(keyOf)));
      })
      .catch((e) => alive && setError(String(e.message ?? e)));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const candidates = data?.candidates ?? [];
  const chosen = useMemo(() => candidates.filter((c) => selected.has(keyOf(c))), [candidates, selected]);

  function toggle(c: Candidate) {
    setSelected((s) => { const n = new Set(s); const k = keyOf(c); n.has(k) ? n.delete(k) : n.add(k); return n; });
  }
  function acceptRecommendations() {
    setSelected(new Set(candidates.filter((c) => c.recommend === "keep").map(keyOf)));
  }

  if (error) return <p style={{ color: "var(--bad)" }}>{error}</p>;
  if (!data) return <p><Spinner /> searching arXiv &amp; Semantic Scholar, ranking &amp; screening candidates…</p>;

  const keeps = candidates.filter((c) => c.recommend === "keep").length;

  return (
    <div className="screen-view rise-in">
      <div className="view-head">
        <div className="view-head-text">
          <span className="overline">Screen sources · nothing downloaded yet</span>
          <h2>Screen {candidates.length} candidates{data.found > candidates.length ? ` (of ${data.found} found)` : ""}</h2>
          <p>
            Ranked by relevance to your objective × authority (citations) × recency. Every
            candidate shows a recommendation and why — <strong>you</strong> decide what enters the
            corpus before a single PDF is downloaded. Chat becomes available once a paper is
            ingested (it isn’t downloaded yet here).
          </p>
        </div>
        <button className="btn btn-ghost" onClick={onCancel}><Icon.x size={15} /> Cancel</button>
      </div>

      {(data.since_year || data.until_year || data.min_citations || data.field) && (
        <div className="cchip-row" style={{ marginBottom: 14 }}>
          {data.field && <span className="cchip">{data.field}</span>}
          {data.since_year && data.until_year ? <span className="cchip">{data.since_year}–{data.until_year}</span>
            : data.since_year ? <span className="cchip">after {data.since_year}</span>
            : data.until_year ? <span className="cchip">before {data.until_year}</span> : null}
          {data.min_citations ? <span className="cchip gold">≥ {data.min_citations} citations</span> : null}
          <span className="cchip-note">enforced on the corpus</span>
        </div>
      )}

      {/* What this candidate pool can and cannot answer — shown BEFORE the
          researcher commits to a 40-minute run. An axis nothing mentions will
          not fill itself once the PDFs are downloaded, and finding that out at
          the end is how a review ends up reporting "no evidence" on the
          question it was asked. */}
      {data.axis_coverage?.length ? (
        <div className="axcov">
          <div className="axcov-h">
            What this set can answer
            <span>
              a mention is not a measurement — this is an upper bound, counted
              from titles and abstracts
            </span>
          </div>
          {data.axis_coverage.map((a) => (
            <div className="axcov-row" key={a.axis}>
              <span className="ax">{a.axis}</span>
              <span className="bar" aria-hidden="true">
                <i
                  className={a.verdict === "barely present" ? "low"
                    : a.verdict === "thin" ? "mid" : "ok"}
                  style={{ width: `${Math.round(a.share * 100)}%` }}
                />
              </span>
              <span className="n">
                {a.candidates_mentioning}/{a.candidates_kept}
              </span>
              <span className={`v ${a.verdict === "barely present" ? "low"
                : a.verdict === "thin" ? "mid" : "ok"}`}>
                {a.verdict}
              </span>
            </div>
          ))}
        </div>
      ) : null}

      <div className="panel" style={{ overflow: "hidden" }}>
        <table className="screen-table">
          <thead>
            <tr>
              <th style={{ width: 34 }}></th>
              <th>Paper</th>
              <th>Domain</th>
              <th>Relevance</th>
              <th>Cited</th>
              <th>Year</th>
              <th>Recommendation</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((c) => {
              const on = selected.has(keyOf(c));
              const drop = c.recommend === "drop";
              return (
                <tr key={keyOf(c)} className={drop && !on ? "sc-dim" : ""}>
                  <td><button className={`sc-tgl ${on ? "on" : ""}`} onClick={() => toggle(c)} aria-label={on ? "Exclude" : "Include"} /></td>
                  <td className="sc-paper">
                    {c.url ? <a href={c.url} target="_blank" rel="noreferrer">{c.title}</a> : c.title}
                    <span className="sc-meta">
                      {(c.authors ?? []).slice(0, 1).join("")}{(c.authors?.length ?? 0) > 1 ? " et al." : ""}
                      {c.venue ? ` · ${c.venue}` : ""} · {c.source === "arxiv" ? "arXiv" : "Semantic Scholar"}
                    </span>
                  </td>
                  <td><span className="sc-dom">{c.domain_fit || "—"}</span></td>
                  <td>
                    <span className="sc-bar"><i style={{ width: `${Math.round(c.score * 100)}%`, background: c.score >= 0.5 ? "var(--accent)" : "var(--bad)" }} /></span>
                    <span className="sc-barn mono">{c.score.toFixed(2)}</span>
                  </td>
                  <td className="mono" style={{ color: c.citation_count ? "var(--warn)" : "var(--ink-faint)" }}>{c.citation_count || "—"}</td>
                  <td className="mono">{c.year ?? "n.d."}</td>
                  <td>
                    <span className={`sc-rec ${drop ? "drop" : "keep"}`}>{drop ? "drop" : "keep"}</span>
                    <span className="sc-reason">{c.reason}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="screen-foot">
        <span className="sum"><b>{chosen.length} selected</b> · {keeps} recommended to keep · {candidates.length - keeps} to drop</span>
        <span className="spacer" />
        <button className="btn btn-ghost" onClick={acceptRecommendations}><Icon.sparkle size={14} /> Accept recommendations</button>
        <button className="btn btn-accent" disabled={chosen.length === 0} onClick={() => onCompile(chosen)}>
          Compile verified review from {chosen.length} <Icon.arrowRight size={14} />
        </button>
      </div>
    </div>
  );
}
