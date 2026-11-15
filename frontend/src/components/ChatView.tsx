import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type {
  AnswerSegment, ChatProgress, ChatResult, ChatTurn, RefusalKind,
} from "../types";
import EvidenceDrawer from "./EvidenceDrawer";
import { Empty, Spinner } from "./ui";
import { Icon } from "./icons";
import { useEvidence } from "../evidence";
import { useChatContext, AddToChat } from "../chatctx";

/**
 * Ask — the grounded follow-up conversation.
 *
 * THREE THINGS THIS FILE IS DELIBERATELY NOT.
 *
 * 1. It is not a claim list. An answer renders as FLOWING PROSE with mono
 *    superscript footnotes — the treatment the report and the paper drawer
 *    already use. The old corpus view stacked each verified claim as its own
 *    card, which read as search results rather than an answer, and buried the
 *    fact that the claims were written to be read in sequence.
 *
 * 2. It does not stream tokens. It cannot: the verification gate runs after
 *    generation, so streaming raw text would put ungated sentences in front of
 *    the reader and break G1/G2. What streams is the PIPELINE — searching, N
 *    passages from M documents, drafting, verifying — which is honest and is
 *    the part worth watching. Progress events are typed at the publish site and
 *    grouped on `kind` alone; nothing here pattern-matches server prose.
 *
 * 3. It does not treat every refusal alike. Exactly one refusal kind
 *    (`empty_corpus`) is a statement about the corpus. The rest are statements
 *    about Veriscope, and a refusal that says "your corpus lacks this" when it
 *    means "we could not establish this" is the same error the cell-state table
 *    forbids in the matrix. So a refusal shows what it read, what this corpus
 *    covers, and what it CAN answer.
 */

// Every sentence declares its type — E evidential, D derived, S structural.
// G6: the reader can always tell which one they are reading.
function Sentence({ seg, onCite }: { seg: AnswerSegment; onCite: (id: string) => void }) {
  if (seg.type === "E") {
    return (
      <span className="ans-s ans-e">
        {seg.text.trim()}{" "}
        {seg.claim_id && (
          <sup className="rp-cite" title="Click to read the verbatim source span"
               onClick={() => onCite(seg.claim_id)}>&#8226;</sup>
        )}{" "}
      </span>
    );
  }
  if (seg.type === "D") {
    // A derived sentence is NEVER given a footnote: a citation to one paper
    // would misrepresent a sentence computed from many. Its provenance
    // affordance is the row-set and the basis it was computed from.
    return (
      <span className="ans-s ans-d" title={seg.basis || undefined}>
        {seg.text.trim()}
        {seg.doc_ids?.length ? (
          <span className="ans-rowset">{seg.doc_ids.length} rows</span>
        ) : null}{" "}
      </span>
    );
  }
  return <span className="ans-s ans-struct">{seg.text.trim()} </span>;
}

const REFUSAL_TITLE: Record<string, string> = {
  empty_corpus: "Nothing in this corpus matched",
  no_support: "Could not establish this",
  gate_rejected: "Drafted, then refused by the gate",
  guardrail: "Outside what Ask will answer",
  unresolved_selection: "That selection resolved to nothing",
  no_records: "No run records yet",
};

// Only `empty_corpus` is a fact about the corpus. Everything else is a fact
// about us, and reads as the softer amber caveat rather than a verdict.
const ABOUT_CORPUS = new Set<RefusalKind>(["empty_corpus", "guardrail"]);

function Refusal({
  result, onAsk,
}: { result: ChatResult; onAsk: (q: string) => void }) {
  const kind = (result.refusal_kind || "no_support") as RefusalKind;
  const [open, setOpen] = useState(false);
  const looked = result.looked_at ?? [];
  return (
    <div className={`refusal ${ABOUT_CORPUS.has(kind) ? "is-corpus" : "is-ours"}`}>
      <h4>{REFUSAL_TITLE[kind] || "Refused — honestly"}</h4>
      <p>{result.refusal_reason}</p>
      {result.coverage_note && <p className="refusal-note">{result.coverage_note}</p>}

      {looked.length > 0 && (
        <div className="refusal-read">
          <button className="refusal-toggle" onClick={() => setOpen((v) => !v)}>
            <Icon.chevronRight size={12}
              style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform .15s" }} />
            {open ? "Hide" : "Show"} the {looked.length} passage{looked.length === 1 ? "" : "s"} we read
          </button>
          {open && (
            <ul className="refusal-passages">
              {looked.map((h, i) => (
                <li key={h.document_id + i}>
                  <span className="rp-src">
                    {h.document_title.slice(0, 80)}
                    {h.section ? ` · ${h.section.slice(0, 40)}` : ""}
                    {h.page_start > 0 ? ` · p.${h.page_start}` : ""}
                  </span>
                  <span className="rp-snip">{h.snippet}…</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {(result.suggestions?.length ?? 0) > 0 && (
        <div className="refusal-next">
          <span className="overline">Questions this workspace can answer</span>
          <div className="starter-row">
            {result.suggestions!.map((q) => (
              <button key={q} className="starter-chip" onClick={() => onAsk(q)}>{q}</button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// The live pipeline. One line per stage, the newest one active — so a slow turn
// says what it is doing instead of spinning.
function ProgressTrail({ events }: { events: ChatProgress[] }) {
  if (!events.length) {
    return <p className="ans-progress"><Spinner /> &nbsp;working…</p>;
  }
  return (
    <ul className="ans-progress-trail">
      {events.map((e, i) => (
        <li key={i} className={`prog prog-${e.kind} ${i === events.length - 1 ? "is-live" : ""}`}>
          <span className="prog-k">{e.kind}</span>
          <span className="prog-m">{e.message}</span>
        </li>
      ))}
    </ul>
  );
}

function Answer({
  result, question, onCite, onAsk, paper,
}: {
  result: ChatResult;
  question: string;
  onCite: (id: string) => void;
  onAsk: (q: string) => void;
  paper: boolean;
}) {
  const segments = useMemo<AnswerSegment[]>(() => {
    if (result.segments?.length) return result.segments;
    // A pre-envelope answer (restored history): its claims are all E.
    return result.claims.map((c) => ({
      type: "E" as const, text: c.text, claim_id: c.id, basis: "", doc_ids: [],
    }));
  }, [result]);

  const counts = useMemo(() => {
    const e = segments.filter((s) => s.type === "E").length;
    const d = segments.filter((s) => s.type === "D").length;
    return { e, d };
  }, [segments]);

  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(segments.map((s) => s.text).join(" "));
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch { /* clipboard unavailable */ }
  }

  return (
    <div className="ans">
      {result.resolved_question && (
        <div className="ans-resolved" title="How your follow-up was read for retrieval">
          <Icon.search size={11} /> read as: {result.resolved_question}
        </div>
      )}

      <p className="ans-prose">
        {segments.map((s, i) => <Sentence key={i} seg={s} onCite={onCite} />)}
      </p>

      {/* The composition, not a "verified" badge. That badge stops being true
          the moment a sentence ships that is not quote-verified. */}
      <div className="ans-foot">
        <span className="ans-comp">
          {counts.e} verified{counts.d ? ` · ${counts.d} derived` : ""}
        </span>
        {(result.sources?.length ?? 0) > 0 && (
          <span className="ans-srcs">
            {result.sources!.map((s) => (
              <span key={s.document_id} className="ans-src" title={s.document_title}>
                {s.document_title.slice(0, 44)}
                {s.abstract_only && <em> abstract only</em>}
                <b>{s.claims}</b>
              </span>
            ))}
          </span>
        )}
        <span className="ans-acts">
          <button className="ans-act" onClick={copy}>{copied ? "copied" : "copy"}</button>
          {!paper && (
            <AddToChat compact item={{ kind: "answer", id: result.answer_id,
                                       label: `answer · ${question}` }} />
          )}
        </span>
      </div>

      {result.coverage_note && <div className="coverage-note">{result.coverage_note}</div>}

      {(result.suggestions?.length ?? 0) > 0 && (
        <div className="ans-followups">
          <span className="overline">Ask next</span>
          <div className="starter-row">
            {result.suggestions!.slice(0, 3).map((q) => (
              <button key={q} className="starter-chip" onClick={() => onAsk(q)}>{q}</button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

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
  const stopRef = useRef<(() => void) | null>(null);
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

  useEffect(() => () => stopRef.current?.(), []);

  const PAPER_STARTERS = isRepo
    ? ["What does this project do?", "How is it implemented?", "What are the key components?", "How do I use it?"]
    : isBlog
    ? ["What is the main argument?", "What does it recommend?", "What evidence is given?", "What are the caveats?"]
    : ["What problem does this paper address?", "What method does it propose?", "What are the key results?", "What are its limitations?"];

  // A follow-up carries its subject in the conversation. The last few turns go
  // back with the question so "why?" can be resolved into something a retriever
  // can search for — the answer text sent is what the user actually read.
  function historyPayload(): { question: string; answer: string }[] {
    return turns
      .filter((t) => t.result)
      .slice(-4)
      .map((t) => ({
        question: t.question,
        answer: t.result!.refused
          ? t.result!.refusal_reason
          : (t.result!.segments?.map((s) => s.text).join(" ")
             || t.result!.claims.map((c) => c.text).join(" ")).slice(0, 4000),
      }));
  }

  function patchLast(patch: Partial<ChatTurn>) {
    setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, ...patch } : turn)));
  }

  function submit(q: string) {
    if (!q.trim() || busy) return;
    const history = historyPayload();
    setQuestion("");
    setBusy(true);
    setTurns((t) => [...t, { question: q, result: null, progress: [] }]);
    setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 50);

    const finish = () => {
      setBusy(false);
      stopRef.current = null;
      setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 80);
    };

    stopRef.current = api.chatStream(
      {
        projectId, question: q, documentId,
        entityRefs: scoped ? chatCtx.items.map((i) => ({ kind: i.kind, id: i.id })) : undefined,
        history: paper ? undefined : history,
      },
      (p) => setTurns((t) => t.map((turn, i) =>
        i === t.length - 1 ? { ...turn, progress: [...(turn.progress ?? []), p] } : turn)),
      (result) => { patchLast({ result }); finish(); },
      (message) => { patchLast({ error: message }); finish(); },
    );
  }

  function stop() {
    stopRef.current?.();
    stopRef.current = null;
    patchLast({ error: "Stopped before the answer finished verifying, so nothing was returned. Ask again to retry." });
    setBusy(false);
  }

  function ask(e: FormEvent) { e.preventDefault(); submit(question.trim()); }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(question.trim()); }
  }

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
        <div>
          <Empty glyph="❝" title="Ask your corpus">
            Follow-ups are answered from what this project has read. Every factual
            sentence carries a verbatim quote you can click; sentences derived from
            study counts are labelled as derived. When the corpus cannot support an
            answer, Veriscope says so — and shows you what it read.
          </Empty>
          <div className="starter-row">
            {["What is this report about?", "What did you find?",
              "What are the open gaps?", "Which papers are in this corpus?"].map((s) => (
              <button key={s} className="starter-chip" onClick={() => submit(s)}>{s}</button>
            ))}
          </div>
        </div>
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
              {!turn.result && !turn.error && <ProgressTrail events={turn.progress ?? []} />}
              {turn.error && (
                <div className="refusal is-ours"><h4>Request failed</h4><p>{turn.error}</p></div>
              )}
              {turn.result?.refused && <Refusal result={turn.result} onAsk={submit} />}
              {turn.result && !turn.result.refused && (
                <Answer result={turn.result} question={turn.question}
                        onCite={openCite} onAsk={submit} paper={paper} />
              )}
              {turn.result && turn.result.technical_context.length > 0 && (
                <div className="tech-context">
                  <h5>Practitioner signal — separate evidence class, not part of the answer</h5>
                  {turn.result.technical_context.map((hit) => (
                    <div className="tech-hit" key={hit.document_id + hit.snippet.slice(0, 16)}>
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
          <textarea
            className="input ask-input" rows={1}
            placeholder={paper ? "Ask this paper anything…" : "Ask a follow-up…"}
            value={question} onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={onKey} disabled={busy}
          />
          {busy ? (
            <button type="button" className="btn" onClick={stop}>Stop</button>
          ) : (
            <button className="btn btn-accent" disabled={!question.trim()}>
              Ask <Icon.arrowRight size={14} />
            </button>
          )}
        </div>
        <div className="ask-hint">Enter to send · Shift+Enter for a new line</div>
      </form>

      {paper && localClaim && (
        <EvidenceDrawer claimId={localClaim} projectId={projectId} onClose={() => setLocalClaim(null)} stack />
      )}
    </div>
  );
}
