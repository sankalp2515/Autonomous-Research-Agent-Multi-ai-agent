import { FormEvent, useRef, useState } from "react";
import { api } from "../api";
import type { ChatTurn } from "../types";
import EvidenceDrawer from "./EvidenceDrawer";
import { Empty, Spinner, Stamp } from "./ui";

export default function ChatView({
  projectId,
  documentId,
  documentKind,
}: {
  projectId: string;
  documentId?: string;
  documentKind?: string;
}) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [openClaim, setOpenClaim] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const paper = !!documentId;
  const isRepo = documentKind === "repo";
  const isBlog = documentKind === "blog";
  const docNoun = isRepo ? "repo" : isBlog ? "source" : "paper";

  const PAPER_STARTERS = isRepo
    ? ["What does this project do?", "How is it implemented?",
       "What are the key components?", "How do I use it?"]
    : isBlog
    ? ["What is the main argument?", "What does it recommend?",
       "What evidence is given?", "What are the caveats?"]
    : ["What problem does this paper address?", "What method does it propose?",
       "What are the key results?", "What are its limitations?"];

  async function submit(q: string) {
    if (!q.trim() || busy) return;
    setQuestion("");
    setBusy(true);
    setTurns((t) => [...t, { question: q, result: null }]);
    setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    try {
      const result = await api.chat(projectId, q, documentId);
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, result } : turn)));
    } catch (err: any) {
      setTurns((t) =>
        t.map((turn, i) =>
          i === t.length - 1 ? { ...turn, error: String(err.message ?? err) } : turn
        )
      );
    } finally {
      setBusy(false);
      setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 80);
    }
  }

  function ask(e: FormEvent) {
    e.preventDefault();
    submit(question.trim());
  }

  return (
    <div className="content-narrow">
      {turns.length === 0 && !paper && (
        <Empty glyph="❝" title="Ask your corpus">
          Every claim in an answer carries a verbatim quote from a specific
          document — click any claim to inspect its evidence trail. If your
          corpus can't support an answer, Veriscope refuses instead of guessing.
        </Empty>
      )}
      {turns.length === 0 && paper && (
        <div>
          <Empty glyph="❝" title={`Ask this ${docNoun}`}>
            {isRepo || isBlog
              ? `Answers come only from this ${docNoun} — a practitioner source (not peer-reviewed), grounded in its exact text with clickable citations.`
              : "Answers are drawn only from this paper's text, with page-anchored citations you can click to read the exact passage."}
          </Empty>
          <div className="starter-row">
            {PAPER_STARTERS.map((s) => (
              <button key={s} className="starter-chip" onClick={() => submit(s)}>
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="chat-thread">
        {turns.map((turn, i) => (
          <div key={i}>
            <div className="chat-q">{turn.question}</div>
            <div className="chat-a" style={{ marginTop: 14 }}>
              {!turn.result && !turn.error && (
                <p style={{ color: "var(--ink-faint)" }}>
                  <Spinner /> &nbsp;retrieving, drafting, verifying…
                </p>
              )}
              {turn.error && (
                <div className="refusal">
                  <h4>Request failed</h4>
                  <p>{turn.error}</p>
                </div>
              )}
              {turn.result?.refused && (
                <div className="refusal">
                  <h4>Refused — honestly</h4>
                  <p>{turn.result.refusal_reason}</p>
                  {turn.result.coverage_note && (
                    <div className="coverage-note">{turn.result.coverage_note}</div>
                  )}
                </div>
              )}
              {turn.result && !turn.result.refused && paper && (
                <div className="paper-answer">
                  <p className="rp-prose" style={{ paddingLeft: 0 }}>
                    {turn.result.claims.map((claim) => (
                      <span key={claim.id} className="rp-claim">
                        {claim.text.trim()}{" "}
                        <sup
                          className="rp-cite"
                          title={`${claim.evidence.section || "passage"} — click to read it`}
                          onClick={() => setOpenClaim(claim.id)}
                        >
                          {claim.evidence.page_start > 0
                            ? `p.${claim.evidence.page_start}`
                            : claim.evidence.section
                            ? "§"
                            : "·"}
                        </sup>{" "}
                      </span>
                    ))}
                  </p>
                  {turn.result.coverage_note && (
                    <div className="coverage-note">{turn.result.coverage_note}</div>
                  )}
                </div>
              )}
              {turn.result && !turn.result.refused && !paper && (
                <div className="panel">
                  <div style={{ padding: "12px 16px 0" }}>
                    <Stamp kind="verified">
                      {turn.result.claims.length} verified claim
                      {turn.result.claims.length === 1 ? "" : "s"}
                    </Stamp>
                  </div>
                  <div className="claim-list" style={{ padding: "6px 6px 8px" }}>
                    {turn.result.claims.map((claim, n) => (
                      <div
                        key={claim.id}
                        className="claim"
                        onClick={() => setOpenClaim(claim.id)}
                        title="View evidence"
                      >
                        {claim.text}
                        <sup>[{n + 1}]</sup>
                        <span className="claim-src">
                          {claim.evidence.document_title.slice(0, 90)}
                          {claim.evidence.page_start > 0 &&
                            ` · p.${claim.evidence.page_start}`}
                          {claim.evidence.abstract_only && " · abstract only"}
                        </span>
                      </div>
                    ))}
                  </div>
                  {turn.result.coverage_note && (
                    <div className="coverage-note" style={{ padding: "0 16px 14px" }}>
                      {turn.result.coverage_note}
                    </div>
                  )}
                </div>
              )}
              {turn.result && turn.result.technical_context.length > 0 && (
                <div className="tech-context">
                  <h5>Practitioner signal — separate evidence class, not part of the answer</h5>
                  {turn.result.technical_context.map((hit) => (
                    <div className="tech-hit" key={hit.document_id + hit.snippet.slice(0, 16)}>
                      <Stamp kind="neutral">{hit.source_type}</Stamp>
                      <span className="t">
                        <strong>{hit.document_title.slice(0, 70)}</strong>
                        {" — "}
                        {hit.snippet.slice(0, 140)}…
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
      <div ref={endRef} />

      <form className="ask-bar" onSubmit={ask}>
        <div className="ask-row">
          <input
            className="input"
            placeholder={paper ? "Ask this paper anything…" : "What do we know about…"}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={busy}
          />
          <button className="btn btn-accent" disabled={busy || !question.trim()}>
            {busy ? <Spinner /> : "Ask"}
          </button>
        </div>
      </form>

      {openClaim && (
        <EvidenceDrawer claimId={openClaim} projectId={projectId} onClose={() => setOpenClaim(null)} />
      )}
    </div>
  );
}
