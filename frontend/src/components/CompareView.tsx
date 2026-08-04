import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  Comparison, ComparisonSummary, Doc, Recommendation,
} from "../types";
import EvidenceDrawer from "./EvidenceDrawer";
import { Empty, Spinner } from "./ui";

// Cross-paper comparison. The researcher picks the sources; every cell is
// drafted from ONLY that paper and passed through the same verification gate
// as the pipeline, so a filled cell is click-to-source and an empty cell is an
// honest "this paper doesn't address that", never a guess.
export default function CompareView({
  projectId,
  preselect,
}: {
  projectId: string;
  preselect?: string[];
}) {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [saved, setSaved] = useState<ComparisonSummary[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set(preselect ?? []));
  const [dimText, setDimText] = useState("");
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [recBusy, setRecBusy] = useState(false);
  const [building, setBuilding] = useState(false);
  const [active, setActive] = useState<Comparison | null>(null);
  const [evidence, setEvidence] = useState<string | null>(null);
  const [error, setError] = useState("");

  const loadSaved = useCallback(async () => {
    try {
      setSaved(await api.listComparisons(projectId));
    } catch {
      /* ignore */
    }
  }, [projectId]);

  useEffect(() => {
    api
      .listDocuments(projectId)
      .then((d) => setDocs(d.filter((x) => x.status === "indexed")))
      .catch(() => setDocs([]));
    loadSaved();
  }, [projectId, loadSaved]);

  useEffect(() => {
    if (preselect?.length) setSelected(new Set(preselect));
  }, [preselect]);

  const papers = useMemo(
    () => (docs ?? []).filter((d) => ["paper", "upload"].includes(d.source_type)),
    [docs]
  );

  function toggle(id: string) {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else if (n.size < 5) n.add(id);
      return n;
    });
  }

  async function recommend() {
    if (selected.size === 0) return;
    setRecBusy(true);
    try {
      const r = await api.recommendSources(projectId, [...selected]);
      setRecs(r.recommendations);
    } catch {
      setRecs([]);
    } finally {
      setRecBusy(false);
    }
  }

  async function build() {
    if (selected.size < 2) return;
    setBuilding(true);
    setError("");
    setActive(null);
    try {
      const dims = dimText
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const comp = await api.createComparison(projectId, {
        document_ids: [...selected],
        dimensions: dims,
      });
      setActive(comp);
      loadSaved();
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setBuilding(false);
    }
  }

  async function openSaved(id: string) {
    setError("");
    try {
      setActive(await api.getComparison(id));
    } catch (e: any) {
      setError(e.message ?? String(e));
    }
  }

  async function toggleReport() {
    if (!active) return;
    const r = await api.toggleComparisonReport(active.id);
    setActive({ ...active, include_in_report: r.include_in_report });
    loadSaved();
  }

  function exportMd() {
    if (!active) return;
    const cols = active.documents.map((d) => d.title).join(" | ");
    let md = `# ${active.title}\n\n| Dimension | ${cols} |\n`;
    md += `| --- | ${active.documents.map(() => "---").join(" | ")} |\n`;
    for (const row of active.matrix) {
      const cells = active.documents.map((d) => {
        const c = row.cells[d.id];
        return c ? c.claim.replace(/\|/g, "\\|") : "—";
      });
      md += `| **${row.dimension}** | ${cells.join(" | ")} |\n`;
    }
    const blob = new Blob([md], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `comparison-${active.id}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  if (docs === null) return <p><Spinner /> loading library…</p>;

  return (
    <div className="compare-view">
      <div style={{ marginBottom: 14 }}>
        <span className="overline">Compare across papers · verified cell-by-cell</span>
        <p style={{ margin: "4px 0 0", color: "var(--text-2)", fontSize: 13.5, maxWidth: 640, lineHeight: 1.55 }}>
          Pick 2–5 papers from your library. Every cell is drafted from that
          paper alone and quote-checked against its source — click any cell to
          see the exact passage. An empty cell means that paper doesn't address
          the dimension.
        </p>
      </div>

      {papers.length < 2 ? (
        <Empty glyph="⊞" title="Add at least two papers to compare">
          Run deep research or add papers to your library, then compare them
          side-by-side here.
        </Empty>
      ) : (
        <div className="compare-picker">
          <div className="compare-sources">
            <div className="overline" style={{ marginBottom: 8 }}>
              Your library ({selected.size}/5 selected)
            </div>
            <div className="compare-doclist">
              {papers.map((d) => (
                <label key={d.id} className={`compare-doc ${selected.has(d.id) ? "on" : ""}`}>
                  <input
                    type="checkbox"
                    checked={selected.has(d.id)}
                    onChange={() => toggle(d.id)}
                    disabled={!selected.has(d.id) && selected.size >= 5}
                  />
                  <span className="compare-doc-title">
                    {d.title}
                    {d.abstract_only && <em className="mono"> · abstract only</em>}
                  </span>
                  {d.year && <span className="mono compare-doc-year">{d.year}</span>}
                </label>
              ))}
            </div>
          </div>

          <div className="compare-controls">
            <label className="overline">Comparison dimensions (optional)</label>
            <input
              className="input"
              placeholder="e.g. Method, Dataset, Result — or leave blank to auto-derive"
              value={dimText}
              onChange={(e) => setDimText(e.target.value)}
              style={{ margin: "6px 0 12px" }}
            />
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn" onClick={build} disabled={selected.size < 2 || building}>
                {building ? <><Spinner /> Building & verifying…</> : `Compare ${selected.size || ""}`}
              </button>
              <button className="btn btn-ghost" onClick={recommend}
                      disabled={selected.size === 0 || recBusy}>
                {recBusy ? <Spinner /> : "✦ Recommend related"}
              </button>
            </div>
            {error && <p style={{ color: "var(--bad)", fontSize: 12.5 }}>{error}</p>}

            {recs.length > 0 && (
              <div className="compare-recs">
                <div className="overline" style={{ margin: "14px 0 6px" }}>
                  Related papers already in your library — add to the comparison
                </div>
                {recs.map((r) => (
                  <div key={r.id} className="compare-rec">
                    <button className="compare-rec-add" onClick={() => { toggle(r.id); setRecs((x) => x.filter((y) => y.id !== r.id)); }}>
                      + Add
                    </button>
                    <span className="compare-rec-title">{r.title}</span>
                    <span className="mono compare-rec-score">{(r.score * 100).toFixed(0)}% similar</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {building && (
        <div className="compare-building">
          <Spinner /> Drafting one grounded finding per cell and running each
          through the verification gate — this makes a few LLM calls per paper.
        </div>
      )}

      {active && !building && (
        <ComparisonTable
          comp={active}
          onCell={(claimId) => setEvidence(claimId)}
          onExport={exportMd}
          onToggleReport={toggleReport}
        />
      )}

      {saved.length > 0 && (
        <div className="compare-saved">
          <div className="overline" style={{ margin: "22px 0 8px" }}>
            Saved comparisons ({saved.length})
          </div>
          {saved.map((c) => (
            <div key={c.id} className={`compare-saved-row ${active?.id === c.id ? "on" : ""}`}>
              <button className="compare-saved-open" onClick={() => openSaved(c.id)}>
                <b>{c.title}</b>
                <small className="mono">
                  {c.document_count} papers · {c.dimensions.length} dimensions
                  {c.include_in_report && " · in report"}
                </small>
              </button>
              <button className="compare-saved-del" title="Delete"
                      onClick={async () => { await api.deleteComparison(c.id); if (active?.id === c.id) setActive(null); loadSaved(); }}>
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {evidence && (
        <EvidenceDrawer claimId={evidence} projectId={projectId} onClose={() => setEvidence(null)} />
      )}
    </div>
  );
}

function ComparisonTable({
  comp,
  onCell,
  onExport,
  onToggleReport,
}: {
  comp: Comparison;
  onCell: (claimId: string) => void;
  onExport: () => void;
  onToggleReport: () => void;
}) {
  const filled = comp.matrix.reduce(
    (n, row) => n + comp.documents.filter((d) => row.cells[d.id]).length,
    0
  );
  const total = comp.matrix.length * comp.documents.length;
  return (
    <div className="compare-result">
      <div className="compare-result-head">
        <div>
          <h3 style={{ margin: 0 }}>{comp.title}</h3>
          <p className="mono" style={{ margin: "4px 0 0", color: "var(--text-3)", fontSize: 12 }}>
            {filled}/{total} cells verified · click a cell for its source
          </p>
        </div>
        <span style={{ flex: 1 }} />
        <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={onToggleReport}>
          {comp.include_in_report ? "✓ In report" : "+ Include in report"}
        </button>
        <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={onExport}>
          ↓ Export .md
        </button>
      </div>
      <div className="compare-table-wrap">
        <table className="compare-table">
          <thead>
            <tr>
              <th className="compare-dim-col">Dimension</th>
              {comp.documents.map((d) => (
                <th key={d.id}>
                  {d.url ? (
                    <a href={d.url} target="_blank" rel="noreferrer">{d.title}</a>
                  ) : (
                    d.title
                  )}
                  {d.year && <span className="mono compare-th-year"> {d.year}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {comp.matrix.map((row) => (
              <tr key={row.dimension}>
                <th className="compare-dim-col">{row.dimension}</th>
                {comp.documents.map((d) => {
                  const c = row.cells[d.id];
                  return (
                    <td key={d.id} className={c ? "compare-cell filled" : "compare-cell empty"}
                        onClick={() => c && onCell(c.claim_id)}
                        title={c ? "Click to see the exact source passage" : ""}>
                      {c ? (
                        <>
                          <span className="compare-cell-claim">{c.claim}</span>
                          <span className="compare-cell-quote">“{c.quote}”</span>
                        </>
                      ) : (
                        <span className="compare-cell-gap">— not addressed</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
