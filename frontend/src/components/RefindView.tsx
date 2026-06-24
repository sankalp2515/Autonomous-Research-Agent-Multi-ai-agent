import { FormEvent, useState } from "react";
import { api } from "../api";
import type { RefindHit } from "../types";
import { Empty, Spinner, Stamp } from "./ui";

export default function RefindView({ projectId }: { projectId: string }) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<RefindHit[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function search(e: FormEvent) {
    e.preventDefault();
    if (!query.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      setHits(await api.refind(projectId, query.trim()));
    } catch (err: any) {
      setError(String(err.message ?? err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="content-narrow">
      <form onSubmit={search} className="ask-row" style={{ marginBottom: 24 }}>
        <input
          className="input"
          placeholder='"I know I read this somewhere…" — describe the passage from memory'
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button className="btn" disabled={busy || !query.trim()}>
          {busy ? <Spinner /> : "Refind"}
        </button>
      </form>
      {error && <p style={{ color: "var(--failed)" }}>{error}</p>}

      {hits === null ? (
        <Empty glyph="∿" title="Semantic recall over everything you've saved">
          Hybrid search (BM25 + dense vectors + rerank) across the full project
          corpus — built for the moment you remember a finding but not where
          you read it.
        </Empty>
      ) : hits.length === 0 ? (
        <Empty glyph="∅" title="Nothing matched">
          The corpus has no passage resembling that. Try different phrasing, or
          it may live in a document you haven't ingested yet.
        </Empty>
      ) : (
        <div className="panel">
          {hits.map((hit) => (
            <div className="refind-hit" key={hit.chunk_id}>
              <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
                <strong style={{ fontSize: 14 }}>{hit.document_title || "(untitled)"}</strong>
                <span className="mono" style={{ fontSize: 11, color: "var(--ink-faint)" }}>
                  {hit.section && `§ ${hit.section} · `}
                  {hit.page_start > 0 && `p.${hit.page_start}–${hit.page_end}`}
                </span>
                {hit.abstract_only && <Stamp kind="gap">abstract only</Stamp>}
              </div>
              <p className="refind-snippet">…{hit.snippet}…</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
