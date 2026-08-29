// Persistent evidence rail — the product's trust moat, promoted from a modal
// drawer to a right rail so a citation NEVER interrupts reading. Clicking any
// citation anywhere (report, chat, compare, map) pins the exact quoted span,
// its NLI stamp and the source passage beside the reading column. Context
// preservation over modal interruption.
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api } from "./api";
import type { EvidenceDetail } from "./types";
import { Spinner } from "./components/ui";
import { Icon } from "./components/icons";

type Ctx = {
  claimId: string | null;
  open: (claimId: string) => void;
  close: () => void;
};
const EvidenceContext = createContext<Ctx>({ claimId: null, open: () => {}, close: () => {} });

export function useEvidence() {
  return useContext(EvidenceContext);
}

export function EvidenceProvider({
  projectId,
  children,
}: {
  projectId: string;
  children: (rail: ReactNode) => ReactNode;
}) {
  const [claimId, setClaimId] = useState<string | null>(null);
  const open = useCallback((id: string) => setClaimId(id), []);
  const close = useCallback(() => setClaimId(null), []);

  // New project → nothing pinned.
  useEffect(() => setClaimId(null), [projectId]);

  const rail = claimId ? (
    <EvidenceRail key={claimId} claimId={claimId} projectId={projectId} onClose={close} />
  ) : null;

  return (
    <EvidenceContext.Provider value={{ claimId, open, close }}>
      {children(rail)}
    </EvidenceContext.Provider>
  );
}

function HighlightedChunk({ text, start, end }: { text: string; start: number; end: number }) {
  if (start < 0 || end <= start || end > text.length) return <>{text}</>;
  return (
    <>
      {text.slice(0, start)}
      <mark>{text.slice(start, end)}</mark>
      {text.slice(end)}
    </>
  );
}

function EvidenceRail({
  claimId,
  projectId,
  onClose,
}: {
  claimId: string;
  projectId: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<EvidenceDetail | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteText, setNoteText] = useState("");
  const [noteSaved, setNoteSaved] = useState(false);
  const headRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    setDetail(null);
    setError("");
    api
      .claimEvidence(claimId)
      .then((d) => alive && setDetail(d))
      .catch((e) => alive && setError(String(e.message ?? e)));
    headRef.current?.scrollIntoView({ block: "nearest" });
    return () => {
      alive = false;
    };
  }, [claimId]);

  async function save() {
    if (saved) return;
    try {
      await api.saveToNotebook(projectId, claimId);
      setSaved(true);
    } catch {
      /* non-fatal */
    }
  }

  async function saveNote() {
    if (!noteText.trim()) return;
    const ev = detail?.evidence[0];
    const seed = ev ? `"${ev.quote}" — ${ev.document.title ?? "source"}` : "";
    try {
      await api.createNote(projectId, { body: noteText.trim(), source_ref: seed, claim_id: claimId });
      setNoteSaved(true);
      setNoteOpen(false);
      setNoteText("");
    } catch {
      /* non-fatal */
    }
  }

  const first = detail?.evidence[0];
  const isScholarly = (t?: string) => t === "paper" || t === "upload" || !t;

  return (
    <aside className="rail" role="complementary" aria-label="Evidence trail">
      <div className="rail-head" ref={headRef}>
        <div className="rail-top">
          <Icon.quote size={14} />
          <span className="k">Evidence trail</span>
          <button className="rail-x" onClick={onClose} aria-label="Close evidence rail">
            <Icon.x size={16} />
          </button>
        </div>
        <p className="rail-claim">{detail?.text ?? "…"}</p>
      </div>

      <div className="rail-body">
        {error && <p style={{ color: "var(--bad)", fontSize: 13 }}>{error}</p>}
        {!detail && !error && <Spinner />}

        {noteOpen && (
          <div className="ev-note">
            <p style={{ fontSize: 12, color: "var(--ink-2)", marginBottom: 8 }}>Your take on this finding — why it matters, how it connects:</p>
            <textarea className="textarea" autoFocus placeholder="Write your own interpretation…"
                      value={noteText} onChange={(e) => setNoteText(e.target.value)} style={{ minHeight: 76 }} />
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
              <button className="btn btn-accent" style={{ fontSize: 12, padding: "6px 13px" }} onClick={saveNote} disabled={!noteText.trim()}>Save note</button>
            </div>
          </div>
        )}

        {detail?.evidence.map((ev, i) => (
          <div key={i}>
            <div className="ev-stamps">
              <span className="ev-stamp ok"><Icon.checkCheck size={13} /> Quote verified</span>
              {ev.nli_label !== "skipped" ? (
                <span className={`ev-stamp ${ev.nli_label === "entailment" ? "nli" : "warn"}`}>
                  <Icon.gitBranch size={13} /> NLI {ev.nli_label} <span className="sc">{ev.nli_score.toFixed(2)}</span>
                </span>
              ) : (
                <span className="ev-stamp warn"><Icon.gitBranch size={13} /> quote-only</span>
              )}
            </div>

            <div className="srcdoc">
              <div className="tp">
                {ev.document.source_type ?? "source"} · {isScholarly(ev.document.source_type) ? "peer-reviewed" : "practitioner"}
              </div>
              <h4>{ev.document.title || "(untitled document)"}</h4>
              <div className="loc">
                {ev.section && <span>§ {ev.section}</span>}
                {ev.pages.length === 2 && ev.pages[0] > 0 ? <span>pp. {ev.pages[0]}–{ev.pages[1]}</span> : <span>text source</span>}
                {ev.document.abstract_only && <span>abstract only</span>}
                {ev.document.status === "tombstoned" && <span>source removed</span>}
              </div>
            </div>

            <div className="pass-h"><Icon.textQuote size={12} /> Source passage — exact quote highlighted</div>
            <div className="passage">
              <HighlightedChunk text={ev.chunk_text} start={ev.quote_char_start} end={ev.quote_char_end} />
            </div>

            {/* P3 — TRACEABILITY CHAIN.
                The stamps above say the checks passed; this says WHAT WAS
                CHECKED, as addresses a person can follow. A trust claim that
                cannot be audited step by step is just a nicer-looking assertion:
                the sentence resolves to a claim row, which resolves to a span at
                known character offsets, inside a known chunk, on a known page of
                a known document, which entered the corpus by a known route.
                Every id here is real and stable. */}
            <div className="ev-chain">
              <div className="ev-chain-h">Provenance chain</div>
              <ol>
                <li><span className="k">sentence</span><span className="v">rendered claim</span></li>
                <li><span className="k">verdict</span>
                  <span className="v">quote match + {ev.nli_label === "skipped" ? "no entailment check" : `NLI ${ev.nli_label} ${ev.nli_score.toFixed(2)}`}</span></li>
                <li><span className="k">span</span>
                  <span className="v mono">chars {ev.quote_char_start}–{ev.quote_char_end}</span></li>
                <li><span className="k">passage</span>
                  <span className="v">{ev.section ? `§ ${ev.section}` : "untitled section"}
                    {ev.pages.length === 2 && ev.pages[0] > 0 ? ` · pp. ${ev.pages[0]}–${ev.pages[1]}` : ""}</span></li>
                <li><span className="k">document</span>
                  <span className="v">{ev.document.title || "(untitled)"}
                    {ev.document.abstract_only ? " · abstract only" : " · full text"}</span></li>
              </ol>
            </div>
          </div>
        ))}

        {detail && (
          <div className="ev-acts">
            {first?.document.url && (
              <a className="ev-btn primary" href={first.document.url} target="_blank" rel="noreferrer">
                <Icon.external size={15} /> Open original source
              </a>
            )}
            <button className="ev-btn" onClick={save} disabled={saved}>
              <Icon.bookmark size={15} /> {saved ? "Saved to notebook" : "Save to notebook"}
            </button>
            <button className="ev-btn" onClick={() => setNoteOpen((o) => !o)}>
              <Icon.notes size={15} /> {noteSaved ? "Noted" : "Note this finding"}
            </button>
          </div>
        )}
      </div>

      {detail && (
        <div className="ev-foot">
          <Icon.lock size={13} />
          This claim renders only because a resolved citation, an exact quote match, and an entailment check all passed.
        </div>
      )}
    </aside>
  );
}
