import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Doc } from "../types";
import { Empty, Spinner, statusStamp, Stamp } from "./ui";
import ChatView from "./ChatView";

export default function DocumentsView({ projectId }: { projectId: string }) {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [drag, setDrag] = useState(false);
  const [uploading, setUploading] = useState(0);
  const [toast, setToast] = useState("");
  const [asking, setAsking] = useState<Doc | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const bibInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(() => {
    api.listDocuments(projectId).then(setDocs).catch(() => setDocs([]));
  }, [projectId]);

  useEffect(refresh, [refresh]);

  function note(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(""), 3500);
  }

  async function upload(files: FileList | File[]) {
    const pdfs = Array.from(files).filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    if (!pdfs.length) {
      note("Only PDF files are supported for upload.");
      return;
    }
    setUploading(pdfs.length);
    for (const file of pdfs) {
      try {
        const result = await api.uploadDocument(projectId, file);
        note(
          result.status === "quarantined"
            ? `Quarantined: ${result.status_reason}`
            : `Indexed: ${file.name}`
        );
      } catch (err: any) {
        note(`Failed: ${file.name} — ${err.message ?? err}`);
      }
      setUploading((u) => u - 1);
    }
    refresh();
  }

  async function tombstone(doc: Doc) {
    if (!window.confirm(`Remove "${doc.title}" from the corpus? Existing answers keep an auditable tombstone.`)) return;
    await api.tombstoneDocument(projectId, doc.id);
    refresh();
  }

  async function importBib(files: FileList | null) {
    const f = files?.[0];
    if (!f) return;
    try {
      const { queued } = await api.importBibtex(projectId, f);
      note(`Importing ${queued} reference${queued === 1 ? "" : "s"} — arXiv entries fetch full text, others are abstract stubs. Refresh shortly.`);
      setTimeout(refresh, 6000);
    } catch (err: any) {
      note(`Import failed: ${err.message ?? err}`);
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 10 }}>
        <button className="btn btn-ghost" style={{ fontSize: 12.5 }}
                onClick={() => bibInput.current?.click()}>
          ↥ Import .bib
        </button>
        <input ref={bibInput} type="file" accept=".bib,.bibtex,text/plain" hidden
               onChange={(e) => { importBib(e.target.files); e.target.value = ""; }} />
      </div>
      <div
        className={`dropzone ${drag ? "drag" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files); }}
        onClick={() => fileInput.current?.click()}
        role="button"
        tabIndex={0}
      >
        {uploading > 0 ? (
          <span><Spinner /> &nbsp;ingesting {uploading} file{uploading > 1 ? "s" : ""}… parse → dedup → chunk → embed → index</span>
        ) : (
          <span>
            <strong style={{ color: "var(--ink-soft)" }}>Drop PDFs here</strong> or click to browse —
            parsed with PyMuPDF4LLM, deduplicated, chunked with page provenance
          </span>
        )}
        <input
          ref={fileInput} type="file" accept=".pdf" multiple hidden
          onChange={(e) => e.target.files && upload(e.target.files)}
        />
      </div>

      {!docs ? (
        <p><Spinner /> loading corpus…</p>
      ) : docs.length === 0 ? (
        <Empty glyph="⌘" title="Corpus is empty">
          Upload PDFs or launch a deep research run — the papers it finds are
          ingested here permanently and become queryable.
        </Empty>
      ) : (
        <div className="panel" style={{ overflow: "hidden" }}>
          <table className="doc-table">
            <thead>
              <tr>
                <th>Document</th>
                <th>Type</th>
                <th>Status</th>
                <th>Text</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {docs.map((doc) => (
                <tr key={doc.id}>
                  <td className="doc-title">
                    {doc.url ? (
                      <a href={doc.url} target="_blank" rel="noreferrer"
                         style={{ color: "var(--primary-deep)", textDecoration: "none" }}>
                        {doc.title || "(untitled)"} <span style={{ opacity: 0.6 }}>↗</span>
                      </a>
                    ) : (
                      doc.title || "(untitled)"
                    )}
                    <div className="doc-sub">
                      {doc.authors?.slice(0, 3).join(", ")}
                      {doc.year ? ` · ${doc.year}` : ""}
                      {doc.status_reason ? ` · ${doc.status_reason}` : ""}
                    </div>
                  </td>
                  <td><Stamp kind="neutral">{doc.source_type}</Stamp></td>
                  <td>{statusStamp(doc.status)}</td>
                  <td>
                    {doc.abstract_only ? (
                      <Stamp kind="gap">abstract only</Stamp>
                    ) : doc.full_text_available ? (
                      <Stamp kind="verified">full text</Stamp>
                    ) : (
                      <Stamp kind="neutral">—</Stamp>
                    )}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {doc.status === "indexed" && !doc.abstract_only && (
                      <button className="btn" style={{ padding: "4px 10px", fontSize: 12, marginRight: 6 }}
                              onClick={() => setAsking(doc)}>
                        {doc.source_type === "repo" ? "Ask this repo"
                          : doc.source_type === "blog" ? "Ask this source"
                          : "Ask this paper"}
                      </button>
                    )}
                    {doc.status !== "tombstoned" && (
                      <button className="btn btn-ghost" style={{ padding: "4px 10px", fontSize: 12 }}
                              onClick={() => tombstone(doc)}>
                        remove
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {toast && <div className="toast">{toast}</div>}

      {asking && (
        <>
          <div className="drawer-veil" onClick={() => setAsking(null)} />
          <aside className="drawer" role="dialog" aria-label="Ask this paper">
            <div className="drawer-head">
              <div>
                <span className="overline">
                  {asking.source_type === "repo" ? "Ask this repo"
                    : asking.source_type === "blog" ? "Ask this source"
                    : "Ask this paper"}{" "}· {asking.source_type === "paper" || asking.source_type === "upload"
                    ? "peer-reviewed source" : "practitioner source"}
                </span>
                <h3>{asking.title || "(untitled)"}</h3>
              </div>
              <button className="drawer-close" onClick={() => setAsking(null)} aria-label="Close">
                ×
              </button>
            </div>
            <div className="drawer-body">
              <ChatView projectId={projectId} documentId={asking.id} documentKind={asking.source_type} />
            </div>
          </aside>
        </>
      )}
    </div>
  );
}
