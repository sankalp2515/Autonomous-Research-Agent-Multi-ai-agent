import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ChatTurn } from "../types";
import EvidenceDrawer from "./EvidenceDrawer";
import { Empty, Spinner, Stamp } from "./ui";
import { Icon } from "./icons";
import { useEvidence } from "../evidence";
import { useChatContext, AddToChat } from "../chatctx";

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
  // In the standalone "Ask" view, citations open the persistent app rail. Inside
  // the nested "Ask this paper" drawer, that rail would sit behind the drawer, so
  // there we fall back to a self-contained modal stacked above it.
  const paper = !!documentId;
  const rail = useEvidence();
  // Main "Ask" view honours the app-wide chat context (papers/claims/answers
  // gathered from anywhere). The scoped "Ask this paper" drawer ignores it.
  const chatCtx = useChatContext();
  const scoped = !paper && chatCtx.count > 0;
  const [localClaim, setLocalClaim] = useState<string | null>(null);
  const openCite = paper ? setLocalClaim : rail.open;

  const endRef = useRef<HTMLDivElement>(null);
  const isRepo = documentKind === "repo";
  const isBlog = documentKind === "blog";
  const docNoun = isRepo ? "repo" : isBlog ? "source" : "paper";

  // Restore durable corpus-chat history on mount (main Ask only; the paper
  // drawer stays scoped/ephemeral). A refresh no longer wipes the conversation.
  const historyLoaded = useRef(false);
  useEffect(() => {
    if (paper || historyLoaded.current) return;
    historyLoaded.current = true;
    api.listAnswers(projectId).then((rows) => {
      if (!rows.length) return;
      setTurns((cur) => (cur.length ? cur : rows.map((r) => ({ question: r.question, result: r }))));
      setTimeout(() => endRef.current?.scrollIntoView(), 60);
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, paper]);

  const PAPER_STARTERS = isRepo
    ? ["What does this project do?", "How is it implemented?", "What are the key components?", "How do I use it?"]
    : isBlog
    ? ["What is the main argument?", "What does it recommend?", "What evidence is given?", "What are the caveats?"]
    : ["What problem does this paper address?", "What method does it propose?", "What are the key results?", "What are its limitations?"];

  async function submit(q: string) {
    if (!q.trim() || busy) return;
    setQuestion("");
    setBusy(true);
    setTurns((t) => [...t, { question: q, result: null }]);
    setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    try {
      // Hard client timeout: a grounded answer that hasn't returned in ~100s is
      // stuck (provider throttle / retrieval) — surface an error instead of an
      // infinite spinner the user can't escape.
      const timeout = new Promise<never>((_, rej) =>
        setTimeout(() => rej(new Error("Still working — the model is busy. Your answer keeps generating in the background; refresh in a moment to see it.")), 100_000));
      const result = await Promise.race([
        api.chat(projectId, q, documentId,
          scoped ? chatCtx.items.map((i) => ({ kind: i.kind, id: i.id })) : undefined),
        timeout,
      ]);
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, result } : turn)));
    } catch (err: any) {
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, error: String(err.message ?? err) } : turn)));
    } finally {
      setBusy(false);
      setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 80);
    }
  }

  function ask(e: FormEvent) { e.preventDefault(); submit(question.trim()); }

  return (
    <div className={paper ? "" : "content-narrow"} style={paper ? {} : { padding: 0 }}>
      {scoped && (
        <div className="chat-ctxbar">
          <div className="chat-ctxbar-head">
            <span className="overline">Grounded in your selection</span>
            <span className="chat-ctxbar-sub">
              Answers draw only from these {chatCtx.count} item{chatCtx.count === 1 ? "" : "s"} — and still pass the verification gate.
            </span>
            <button className="btn btn-ghost" style={{ fontSize: 12, marginLeft: "auto" }} onClick={chatCtx.clear}>
              Clear context
            </button>
          </div>
          <div className="chat-ctxbar-chips">
            {chatCtx.items.map((i) => (
              <span key={i.id} className={`chatctx-chip ${i.kind}`} title={i.label}>
                <span className="chatctx-chip-k">{i.kind === "answer" ? "answer" : i.kind === "claim" ? "claim" : "paper"}</span>
                {i.label.replace(/^(paper|claim|answer) · /, "").slice(0, 46)}
                <button className="chatctx-chip-x" onClick={() => chatCtx.remove(i.id)} aria-label="Remove">×</button>
              </span>
            ))}
          </div>
        </div>
      )}
      {turns.length === 0 && !paper && !scoped && (
        <Empty glyph="❝" title="Ask your corpus">
          Every claim in an answer carries a verbatim quote from a specific document — click any
          claim to inspect its evidence trail. If your corpus can’t support an answer, Veriscope
          refuses instead of guessing.
        </Empty>
      )}
      {turns.length === 0 && paper && (
        <div>
          <Empty glyph="❝" title={`Ask this ${docNoun}`}>
            {isRepo || isBlog
              ? `Answers come only from this ${docNoun} — a practitioner source (not peer-reviewed), grounded in its exact text with clickable citations.`
              : "Answers are drawn only from this paper’s text, with page-anchored citations you can click to read the exact passage."}
          </Empty>
          <div className="starter-row">
            {PAPER_STARTERS.map((s) => (
              <button key={s} className="starter-chip" onClick={() => submit(s)}>{s}</button>
            ))}
          </div>
        </div>
      )}

      <div className="chat-thread">
        {turns.map((turn, i) => (
          <div key={i} className="chat-turn">
            <div className="chat-q">{turn.question}</div>
            <div className="chat-a">
              {!turn.result && !turn.error && (
                <p style={{ color: "var(--ink-faint)" }}><Spinner /> &nbsp;retrieving, drafting, verifying…</p>
              )}
              {turn.error && (
                <div className="refusal"><h4>Request failed</h4><p>{turn.error}</p></div>
              )}
              {turn.result?.refused && (
                <div className="refusal">
                  <h4>Refused — honestly</h4>
                  <p>{turn.result.refusal_reason}</p>
                  {turn.result.coverage_note && <div className="coverage-note" style={{ marginTop: 10 }}>{turn.result.coverage_note}</div>}
                </div>
              )}
              {turn.result && !turn.result.refused && paper && (
                <div className="paper-answer">
                  <p className="rp-prose" style={{ fontSize: 15.5 }}>
                    {turn.result.claims.map((claim) => (
                      <span key={claim.id} className="rp-claim">
                        {claim.text.trim()}{" "}
                        <sup className="rp-cite" title={`${claim.evidence.section || "passage"} — click to read it`} onClick={() => openCite(claim.id)}>
                          {claim.evidence.page_start > 0 ? `p.${claim.evidence.page_start}` : claim.evidence.section ? "§" : "·"}
                        </sup>{" "}
                      </span>
                    ))}
                  </p>
                  {turn.result.coverage_note && <div className="coverage-note" style={{ marginTop: 12 }}>{turn.result.coverage_note}</div>}
                </div>
              )}
              {turn.result && !turn.result.refused && !paper && (
                <div className="panel">
                  <div style={{ padding: "14px 16px 0", display: "flex", alignItems: "center", gap: 10 }}>
                    <Stamp kind="verified">{turn.result.claims.length} verified claim{turn.result.claims.length === 1 ? "" : "s"}</Stamp>
                    <span style={{ marginLeft: "auto" }}>
                      <AddToChat compact item={{ kind: "answer", id: turn.result.answer_id, label: `answer · ${turn.question}` }} />
                    </span>
                  </div>
                  <div className="claim-list" style={{ padding: "8px 8px 10px" }}>
                    {turn.result.claims.map((claim, n) => (
                      <div key={claim.id} className="claim" onClick={() => openCite(claim.id)} title="View evidence">
                        {claim.text}
                        <sup>[{n + 1}]</sup>
                        <span className="claim-src">
                          {claim.evidence.document_title.slice(0, 90)}
                          {claim.evidence.page_start > 0 && ` · p.${claim.evidence.page_start}`}
                          {claim.evidence.abstract_only && " · abstract only"}
                        </span>
                      </div>
                    ))}
                  </div>
                  {turn.result.coverage_note && (
                    <div className="coverage-note" style={{ margin: "0 16px 14px" }}>{turn.result.coverage_note}</div>
                  )}
                </div>
              )}
              {turn.result && turn.result.technical_context.length > 0 && (
                <div className="tech-context">
                  <h5>Practitioner signal — separate evidence class, not part of the answer</h5>
                  {turn.result.technical_context.map((hit) => (
                    <div className="tech-hit" key={hit.document_id + hit.snippet.slice(0, 16)}>
                      <Stamp kind="neutral">{hit.source_type}</Stamp>
                      <span className="t"><strong>{hit.document_title.slice(0, 70)}</strong>{" — "}{hit.snippet.slice(0, 140)}…</span>
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
          <input className="input" placeholder={paper ? "Ask this paper anything…" : "What do we know about…"}
                 value={question} onChange={(e) => setQuestion(e.target.value)} disabled={busy} />
          <button className="btn btn-accent" disabled={busy || !question.trim()}>
            {busy ? <Spinner /> : <>Ask <Icon.arrowRight size={14} /></>}
          </button>
        </div>
      </form>

      {paper && localClaim && (
        <EvidenceDrawer claimId={localClaim} projectId={projectId} onClose={() => setLocalClaim(null)} stack />
      )}
    </div>
  );
}
