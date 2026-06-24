import { useEffect, useState } from "react";
import { api } from "../api";
import type { EvidenceDetail } from "../types";
import { Spinner, Stamp } from "./ui";

function HighlightedChunk({ text, start, end }: { text: string; start: number; end: number }) {
  if (start < 0 || end <= start || end > text.length) {
    return <div className="chunk-text">{text}</div>;
  }
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
}: {
  claimId: string;
  projectId?: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<EvidenceDetail | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteText, setNoteText] = useState("");
  const [noteSaved, setNoteSaved] = useState(false);

  async function save() {
    if (!projectId || saved) return;
    try {
      await api.saveToNotebook(projectId, claimId);
      setSaved(true);
    } catch {
      /* non-fatal */
    }
  }

  async function saveNote() {
    if (!projectId || !noteText.trim()) return;
    const ev = detail?.evidence[0];
    const seed = ev ? `"${ev.quote}" — ${ev.document.title ?? "source"}` : "";
    try {
      await api.createNote(projectId, {
        body: noteText.trim(), source_ref: seed, claim_id: claimId,
      });
      setNoteSaved(true);
      setNoteOpen(false);
    } catch {
      /* non-fatal */
    }
  }

  useEffect(() => {
    let alive = true;
    api
      .claimEvidence(claimId)
      .then((d) => alive && setDetail(d))
      .catch((e) => alive && setError(String(e.message ?? e)));
    return () => {
      alive = false;
    };
  }, [claimId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div className="drawer-veil" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Claim evidence">
        <div className="drawer-head">
          <div>
            <span className="overline">Evidence trail</span>
            <h3>{detail?.text ?? "…"}</h3>
          </div>
          {projectId && (
            <>
              <button className="btn btn-ghost" style={{ padding: "5px 11px", fontSize: 12 }}
                      onClick={() => setNoteOpen((o) => !o)}>
                {noteSaved ? "✎ Noted" : "✎ Note this"}
              </button>
              <button className="btn btn-ghost" style={{ padding: "5px 11px", fontSize: 12 }}
                      onClick={save} disabled={saved}>
                {saved ? "★ Saved" : "☆ Save to notebook"}
              </button>
            </>
          )}
          <button className="drawer-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="drawer-body">
          {noteOpen && (
            <div className="note-card editing" style={{ marginBottom: 18 }}>
              <p className="note-seed">Your note on this finding — write your own take:</p>
              <textarea className="note-body-input" autoFocus
                        placeholder="Why this matters, how it connects, what to follow up…"
                        value={noteText} onChange={(e) => setNoteText(e.target.value)} />
              <div className="note-foot">
                <span style={{ flex: 1 }} />
                <button className="btn" style={{ fontSize: 12, padding: "5px 14px" }}
                        onClick={saveNote} disabled={!noteText.trim()}>
                  Save note
                </button>
              </div>
            </div>
          )}
          {error && <p style={{ color: "var(--failed)" }}>{error}</p>}
          {!detail && !error && <Spinner />}
          {detail?.evidence.map((ev, i) => (
            <div key={i} style={{ marginBottom: 30 }}>
              <div className="evidence-doc">
                <span className="overline">{ev.document.source_type ?? "source"}</span>
                <h4>{ev.document.title || "(untitled document)"}</h4>
                <div className="mono">
                  {ev.section && <>§ {ev.section} · </>}
                  {ev.pages.length === 2 && ev.pages[0] > 0
                    ? `pages ${ev.pages[0]}–${ev.pages[1]}`
                    : "text source"}
                  {ev.document.abstract_only && " · ABSTRACT ONLY"}
                  {ev.document.status === "tombstoned" && " · SOURCE REMOVED"}
                </div>
              </div>
              <div className="nli-row">
                <Stamp kind="verified">quote verified</Stamp>
                {ev.nli_label !== "skipped" && (
                  <Stamp kind={ev.nli_label === "entailment" ? "verified" : "gap"}>
                    nli: {ev.nli_label} {ev.nli_score.toFixed(2)}
                  </Stamp>
                )}
              </div>
              <span className="overline">Source passage — exact quote highlighted</span>
              <HighlightedChunk
                text={ev.chunk_text}
                start={ev.quote_char_start}
                end={ev.quote_char_end}
              />
              {ev.document.url && (
                <p style={{ marginTop: 12 }}>
                  <a href={ev.document.url} target="_blank" rel="noreferrer"
                     style={{ color: "var(--accent)", fontSize: 13 }}>
                    Open original source ↗
                  </a>
                </p>
              )}
            </div>
          ))}
        </div>
      </aside>
    </>
  );
}
