import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { SavedItem } from "../types";
import { Empty, Spinner } from "./ui";

function exportNotebook(items: SavedItem[]) {
  const L = ["# Findings notebook", ""];
  items.forEach((it, i) => {
    L.push(`${i + 1}. ${it.text}`);
    if (it.quote) L.push(`   > "${it.quote}"`);
    L.push(`   — ${it.source || "source"}${it.page > 0 ? `, p.${it.page}` : ""}`);
    if (it.note) L.push(`   note: ${it.note}`);
    L.push("");
  });
  const blob = new Blob([L.join("\n")], { type: "text/markdown" });
  const u = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = u;
  a.download = "findings_notebook.md";
  a.click();
  URL.revokeObjectURL(u);
}

export default function NotebookView({ projectId }: { projectId: string }) {
  const [items, setItems] = useState<SavedItem[] | null>(null);

  const refresh = useCallback(() => {
    api.listNotebook(projectId).then(setItems).catch(() => setItems([]));
  }, [projectId]);

  useEffect(refresh, [refresh]);

  async function remove(id: string) {
    await api.deleteSaved(id);
    refresh();
  }

  if (!items) return <p><Spinner /> loading notebook…</p>;

  return (
    <div className="content-narrow">
      <div style={{ display: "flex", alignItems: "flex-start", marginBottom: 16 }}>
        <div>
          <span className="overline">Findings notebook</span>
          <p style={{ margin: "4px 0 0", color: "var(--text-2)", fontSize: 13.5 }}>
            Verified claims you've saved across reports — each keeps its exact quote and source.
          </p>
        </div>
        <span style={{ flex: 1 }} />
        {items.length > 0 && (
          <button className="btn btn-ghost" style={{ fontSize: 12.5 }}
                  onClick={() => exportNotebook(items)}>
            ↓ Export
          </button>
        )}
      </div>

      {items.length === 0 ? (
        <Empty glyph="★" title="Notebook is empty">
          Open any claim's evidence (click a citation) and hit "Save to notebook"
          to collect findings here across all your reports.
        </Empty>
      ) : (
        <div className="panel" style={{ overflow: "hidden" }}>
          {items.map((it) => (
            <div className="nb-item" key={it.id}>
              <p className="nb-text">{it.text}</p>
              {it.quote && <p className="nb-quote">"{it.quote}"</p>}
              <div className="nb-foot">
                <span className="nb-src">
                  {it.source || "source"}{it.page > 0 ? ` · p.${it.page}` : ""}
                </span>
                <button className="nb-remove" onClick={() => remove(it.id)}>remove</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
