import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Doc } from "../types";
import { Empty, ErrorState, Spinner, statusStamp, Stamp, useConfirm } from "./ui";
import { Icon } from "./icons";
import ChatView from "./ChatView";
import { AddToChat } from "../chatctx";

export default function DocumentsView({ projectId }: { projectId: string }) {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [drag, setDrag] = useState(false);
  const [uploading, setUploading] = useState(0);
  const [toast, setToast] = useState("");
  const [asking, setAsking] = useState<Doc | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const bibInput = useRef<HTMLInputElement>(null);
  const { confirm, element: confirmEl } = useConfirm();

  const refresh = useCallback(() => {
    setLoadError(false);
    api.listDocuments(projectId)
      .then((d) => { setDocs(d); })
      .catch(() => { setDocs(null); setLoadError(true); });
  }, [projectId]);
  useEffect(refresh, [refresh]);

  function note(msg: string) { setToast(msg); setTimeout(() => setToast(""), 3500); }

  async function upload(files: FileList | File[]) {
    const pdfs = Array.from(files).filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    if (!pdfs.length) { note("Only PDF files are supported for upload."); return; }
    setUploading(pdfs.length);
    for (const file of pdfs) {
      try {
        const result = await api.uploadDocument(projectId, file);
        note(result.status === "quarantined" ? `Quarantined: ${result.status_reason}` : `Indexed: ${file.name}`);
      } catch (err: any) {
        note(`Failed: ${file.name} — ${err.message ?? err}`);
      }
      setUploading((u) => u - 1);
    }
    refresh();
  }

  async function tombstone(doc: Doc) {
    const ok = await confirm({
      title: `Remove “${doc.title || "this source"}”?`,
      body: "It leaves the corpus, but existing answers keep an auditable tombstone so nothing already cited breaks.",
      confirmLabel: "Remove source",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.tombstoneDocument(projectId, doc.id);
    } catch (err: any) {
      note(`Couldn’t remove: ${err?.message ?? err}`);
      return;
    }
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
      <div className="view-head">
        <div className="view-head-text">
          <span className="overline">Corpus</span>
          <h2>Sources</h2>
          <p>Every source in this project — uploaded PDFs and papers ingested by research runs. Parsed with page provenance, deduplicated, and queryable.</p>
        </div>
        <button className="btn btn-ghost" onClick={() => bibInput.current?.click()}>
          <Icon.upload size={15} /> Import .bib
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
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.current?.click(); }
        }}
        role="button" tabIndex={0} aria-label="Upload PDFs — drop files here or activate to browse"
      >
        {uploading > 0 ? (
          <span><Spinner /> &nbsp;ingesting {uploading} file{uploading > 1 ? "s" : ""}… parse → dedup → chunk → embed → index</span>
        ) : (
          <span><strong>Drop PDFs here</strong> or click to browse — parsed with PyMuPDF4LLM, deduplicated, chunked with page provenance</span>
        )}
        <input ref={fileInput} type="file" accept=".pdf" multiple hidden onChange={(e) => e.target.files && upload(e.target.files)} />
      </div>

      {loadError ? (
        <ErrorState title="Couldn’t load your corpus" onRetry={refresh} />
      ) : !docs ? (
        <p><Spinner /> loading corpus…</p>
      ) : docs.length === 0 ? (
        <Empty glyph="⌘" title="Your corpus is empty">
          Upload PDFs or launch a deep research run — the papers it finds are ingested here
          permanently and become queryable.
        </Empty>
      ) : (
        <div className="panel" style={{ overflow: "hidden" }}>
          <table className="doc-table">
            <thead>
              <tr><th>Document</th><th>Type</th><th>Status</th><th>Text</th><th></th></tr>
            </thead>
            <tbody>
              {docs.map((doc) => (
                <tr key={doc.id}>
                  <td className="doc-title">
                    {doc.url ? (
                      <a href={doc.url} target="_blank" rel="noreferrer" style={{ color: "var(--ink)" }}>
                        {doc.title || "(untitled)"} <Icon.external size={12} style={{ display: "inline", verticalAlign: -1, color: "var(--ink-3)" }} />
                      </a>
                    ) : (doc.title || "(untitled)")}
                    <div className="doc-sub">
                      {doc.authors?.slice(0, 3).join(", ")}
                      {doc.year ? ` · ${doc.year}` : ""}
                      {doc.status_reason ? ` · ${doc.status_reason}` : ""}
                    </div>
                  </td>
                  <td><Stamp kind="neutral">{doc.source_type}</Stamp></td>
                  <td>{statusStamp(doc.status)}</td>
                  <td>
                    {doc.abstract_only ? <Stamp kind="gap">abstract only</Stamp>
                      : doc.full_text_available ? <Stamp kind="verified">full text</Stamp>
                      : <Stamp kind="neutral">—</Stamp>}
                  </td>
                  <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                    {doc.status === "indexed" && (
                      <span style={{ marginRight: 6, display: "inline-block", verticalAlign: "middle" }}>
                        <AddToChat compact item={{ kind: "document", id: doc.id, label: `paper · ${doc.title || "untitled"}` }} />
                      </span>
                    )}
                    {doc.status === "indexed" && !doc.abstract_only && (
                      <button className="btn" style={{ padding: "5px 11px", fontSize: 12, marginRight: 6 }} onClick={() => setAsking(doc)}>
                        {doc.source_type === "repo" ? "Ask this repo" : doc.source_type === "blog" ? "Ask this source" : "Ask this paper"}
                      </button>
                    )}
                    {doc.status !== "tombstoned" && (
                      <button className="btn btn-ghost" style={{ padding: "5px 10px", fontSize: 12 }} onClick={() => tombstone(doc)}>remove</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {toast && <div className="toast">{toast}</div>}
      {confirmEl}

      {asking && (
        <>
          <div className="drawer-veil" onClick={() => setAsking(null)} />
          <aside className="drawer" role="dialog" aria-label="Ask this paper">
            <div className="drawer-head">
              <div style={{ flex: 1 }}>
                <span className="overline">
                  {asking.source_type === "repo" ? "Ask this repo" : asking.source_type === "blog" ? "Ask this source" : "Ask this paper"}
                  {" "}· {asking.source_type === "paper" || asking.source_type === "upload" ? "peer-reviewed source" : "practitioner source"}
                </span>
                <h3>{asking.title || "(untitled)"}</h3>
              </div>
              <button className="drawer-close" onClick={() => setAsking(null)} aria-label="Close"><Icon.x size={18} /></button>
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
