// In-app "About / How it works" — full transparency on what the system is,
// what it does, how the pipeline runs, the guarantees, and how every metric is
// computed. Shown as a Tools entry so a reviewer can read it inside the product.

const GUARANTEES = [
  ["Quote-match gate", "Every claim carries a verbatim quote that must exact-match its cited source chunk, character-for-character."],
  ["Entailment gate", "An NLI model checks the claim is actually entailed by the source — not just that a matching string exists."],
  ["No fabricated citations", "References render only from resolved sources in the citations table, so a made-up citation is structurally impossible."],
  ["Honest refusal", "When the corpus can't support an answer, the system refuses and says what's missing, instead of guessing."],
];

const PIPELINE = [
  ["Clarify", "An intent guard rejects non-research asks, then the question is decomposed into 2–5 answerable sub-questions."],
  ["Plan", "Source-specific search queries are generated for arXiv and Semantic Scholar — informed by what this project already researched (cross-session memory)."],
  ["Research", "A specialist agent searches and ingests papers: PDFs are downloaded, parsed, chunked and embedded. Failures become honest coverage notes, never silent gaps. (GitHub + engineering-blog agents exist in the codebase but are disabled for now — on the roadmap.)"],
  ["Outline", "A report structure is proposed where each section maps to one distinct, non-overlapping sub-question, so no finding is restated across sections."],
  ["Draft + verify", "Each section is drafted as discrete claims, then every claim runs the quote-match + NLI gate. Failures are regenerated with feedback, then trigger a bounded replan. Only survivors are persisted."],
  ["Assemble", "A deterministic step (no LLM) resolves citations and writes the report. Cross-source edges and an episodic memory of the run are recorded."],
];

const METRICS = [
  ["Citation Accuracy", "Fraction of claims whose quote exactly matches its cited span. Enforced by the gate → reads ~100%."],
  ["Answer Faithfulness", "Fraction of claims entailed by their source (NLI). Measures real support, not just a matching string."],
  ["Answer Relevance", "Cosine similarity between the question and the assembled answer (local embeddings)."],
  ["Context Precision", "Of the chunks retrieved per section, the fraction that are topically relevant — low retrieval noise."],
  ["Context Recall", "Fraction of claims for which a retrieved chunk genuinely supports them — the retriever surfaced the needed evidence."],
  ["Latency", "End-to-end run wall time with a per-node breakdown, plus LLM-call count."],
];

const STACK = [
  ["Orchestration", "LangGraph multi-agent pipeline with checkpoint/resume"],
  ["API", "FastAPI (async), Server-Sent Events for live progress"],
  ["System of record", "Postgres — durable truth; Qdrant vectors + Redis state are rebuildable from it"],
  ["Retrieval", "Hybrid dense + BM25, RRF fusion, cross-encoder rerank, query transform + HyDE"],
  ["Verification", "Deterministic quote-match + NLI entailment model"],
  ["Frontend", "React + Vite + TypeScript"],
];

export default function AboutView() {
  return (
    <div className="about-view">
      <section className="about-hero">
        <span className="about-pill">Research you can prove</span>
        <h1>What Veriscope is</h1>
        <p>
          Veriscope is a <strong>verifiable-by-construction research agent</strong>.
          Most AI research tools fabricate — plausible summaries with citations
          that are subtly wrong. Veriscope flips the default:{" "}
          <strong>nothing reaches you unless it survives a verification gate.</strong>{" "}
          A multi-agent pipeline searches real papers (arXiv, Semantic Scholar),
          drafts a report, and drops any claim that can't be quote-matched and
          entailed against a real source.
        </p>
      </section>

      <section className="about-block">
        <span className="overline">The guarantees</span>
        <h2>Four things it will not do</h2>
        <div className="about-cards">
          {GUARANTEES.map(([t, d]) => (
            <div key={t} className="about-card">
              <b>{t}</b>
              <p>{d}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="about-block">
        <span className="overline">How it works</span>
        <h2>The pipeline, step by step</h2>
        <div className="about-steps">
          {PIPELINE.map(([n, d], i) => (
            <div key={n} className="about-step">
              <span className="about-step-n mono">{i + 1}</span>
              <div>
                <b>{n}</b>
                <p>{d}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="about-block">
        <span className="overline">Features</span>
        <h2>What you can do</h2>
        <ul className="about-features">
          <li><b>Deep research runs</b> — a verified report with click-to-source evidence for every sentence.</li>
          <li><b>Grounded chat</b> — ask follow-ups over your corpus; it refuses rather than guesses.</li>
          <li><b>Cross-paper comparison</b> — compare papers side-by-side, each cell verified and click-to-source.</li>
          <li><b>Persistent library</b> — your corpus, findings and unfinished runs persist; resume exactly where you left off.</li>
          <li><b>Discovery map</b> — explore the corpus by similarity and select papers to compare.</li>
          <li><b>Standing monitor</b> — the agent keeps watching for new papers matching your open questions.</li>
          <li><b>RAG evaluation dashboard</b> — six metrics, every number traced to its evidence.</li>
        </ul>
      </section>

      <section className="about-block">
        <span className="overline">Evaluation — measured, not claimed</span>
        <h2>How we score the RAG system</h2>
        <div className="about-cards">
          {METRICS.map(([t, d]) => (
            <div key={t} className="about-card">
              <b>{t}</b>
              <p>{d}</p>
            </div>
          ))}
        </div>
        <p className="about-note">
          Every metric is computed from the same evidence the verification gate
          produces, so it is auditable. When the local ML models are disabled,
          the deterministic metrics still compute and the ML-dependent ones are
          reported as unavailable — never faked.
        </p>
      </section>

      <section className="about-block">
        <span className="overline">Under the hood</span>
        <h2>Tech stack</h2>
        <div className="about-stack">
          {STACK.map(([k, v]) => (
            <div key={k} className="about-stack-row">
              <span className="about-stack-k">{k}</span>
              <span className="about-stack-v">{v}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
