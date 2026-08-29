import { useEffect, useState } from "react";
import { api } from "../api";
import type { EvidenceDetail } from "../types";
import { Spinner, Stamp } from "./ui";
import { Icon } from "./icons";

// Modal evidence panel — used only for the nested "Ask this paper" drawers,
// where the app-level persistent rail would sit behind the drawer. Everywhere
// else, evidence lives in the persistent rail (see evidence.tsx). `stack` lifts
// it above an already-open drawer.
function HighlightedChunk({ text, start, end }: { text: string; start: number; end: number }) {
  if (start < 0 || end <= start || end > text.length) return <div className="chunk-text">{text}</div>;
  return (
    <div className="chunk-text">
      {text.slice(0, start)}
      <mark>{text.slice(start, end)}</mark>
      {text.slice(end)}
    </div>
  );
}

export default function EvidenceDrawer({
  claimId,
  projectId,
  onClose,
  stack,
}: {
  claimId: string;
  projectId?: string;
  onClose: () => void;
  stack?: boolean;
}) {
  const [detail, setDetail] = useState<EvidenceDetail | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteText, setNoteText] = useState("");
  const [noteSaved, setNoteSaved] = useState(false);

  async function save() {
    if (!projectId || saved) return;
    try { await api.saveToNotebook(projectId, claimId); setSaved(true); } catch { /* non-fatal */ }
  }
  async function saveNote() {
    if (!projectId || !noteText.trim()) return;
    const ev = detail?.evidence[0];
    const seed = ev ? `"${ev.quote}" — ${ev.document.title ?? "source"}` : "";
    try {
      await api.createNote(projectId, { body: noteText.trim(), source_ref: seed, claim_id: claimId });
      setNoteSaved(true); setNoteOpen(false); setNoteText("");
    } catch { /* non-fatal */ }
  }

  useEffect(() => {
    let alive = true;
    api.claimEvidence(claimId).then((d) => alive && setDetail(d)).catch((e) => alive && setError(String(e.message ?? e)));
    return () => { alive = false; };
  }, [claimId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const z = stack ? { zIndex: 141 } : undefined;
  const zv = stack ? { zIndex: 140 } : undefined;

  return (
    <>
      <div className="drawer-veil" style={zv} onClick={onClose} />
      <aside className="drawer" style={z} role="dialog" aria-label="Claim evidence">
        <div className="drawer-head">
          <div style={{ flex: 1 }}>
            <span className="overline">Evidence trail</span>
            <h3>{detail?.text ?? "…"}</h3>
          </div>
          <button className="drawer-close" onClick={onClose} aria-label="Close"><Icon.x size={18} /></button>
        </div>
        <div className="rail-actions">
          {projectId && (
            <>
              <button className="btn btn-ghost" style={{ fontSize: 12, padding: "6px 11px" }} onClick={() => setNoteOpen((o) => !o)}>
                <Icon.notes size={14} /> {noteSaved ? "Noted" : "Note this"}
              </button>
              <button className="btn btn-ghost" style={{ fontSize: 12, padding: "6px 11px" }} onClick={save} disabled={saved}>
                <Icon.bookmark size={14} /> {saved ? "Saved" : "Save to notebook"}
              </button>
            </>
          )}
        </div>
        <div className="drawer-body">
          {noteOpen && (
            <div className="ev-note">
              <p>Your note on this finding — write your own take:</p>
              <textarea className="textarea" autoFocus placeholder="Why this matters, how it connects, what to follow up…"
                        value={noteText} onChange={(e) => setNoteText(e.target.value)} style={{ minHeight: 76 }} />
              <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
                <button className="btn btn-accent" style={{ fontSize: 12, padding: "6px 13px" }} onClick={saveNote} disabled={!noteText.trim()}>Save note</button>
              </div>
            </div>
          )}
          {error && <p style={{ color: "var(--bad)" }}>{error}</p>}
          {!detail && !error && <Spinner />}
          {detail?.evidence.map((ev, i) => (
            <div className="ev-block" key={i}>
              <div className="ev-doc-type"><Stamp kind="neutral">{ev.document.source_type ?? "source"}</Stamp></div>
              <p className="ev-doc-title">{ev.document.title || "(untitled document)"}</p>
              <p className="ev-doc-meta">
                {ev.section && <>§ {ev.section} · </>}
                {ev.pages.length === 2 && ev.pages[0] > 0 ? `pages ${ev.pages[0]}–${ev.pages[1]}` : "text source"}
                {ev.document.abstract_only && " · ABSTRACT ONLY"}
                {ev.document.status === "tombstoned" && " · SOURCE REMOVED"}
              </p>
              <div className="ev-stamps">
                <Stamp kind="verified">quote verified</Stamp>
                {ev.nli_label !== "skipped" && (
                  <Stamp kind={ev.nli_label === "entailment" ? "verified" : "gap"}>nli: {ev.nli_label} {ev.nli_score.toFixed(2)}</Stamp>
                )}
              </div>
              <span className="overline ev-passage-label">Source passage — exact quote highlighted</span>
              <HighlightedChunk text={ev.chunk_text} start={ev.quote_char_start} end={ev.quote_char_end} />
              {ev.document.url && (
                <a className="ev-source-link" href={ev.document.url} target="_blank" rel="noreferrer">Open original source <Icon.external size={13} /></a>
              )}
            </div>
          ))}
        </div>
      </aside>
    </>
  );
}
