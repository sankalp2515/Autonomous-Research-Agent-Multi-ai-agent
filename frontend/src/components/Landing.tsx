// Marketing landing page — the first thing a visitor sees, before auth. Tells
// the story (fabrication problem → verification gate → what you get) and hands
// off to sign-in / the workspace.

const FEATURES: { glyph: string; title: string; body: string }[] = [
  {
    glyph: "✓",
    title: "Verified by construction",
    body: "Every sentence carries a verbatim quote that exact-matches a real source chunk and passes an entailment check. Claims that fail are dropped — not shown.",
  },
  {
    glyph: "⊞",
    title: "Compare across papers",
    body: "Pick papers from your library and compare them side-by-side. Each cell is drafted from that paper alone and quote-checked, so every claim is click-to-source.",
  },
  {
    glyph: "↩",
    title: "A library that remembers",
    body: "Your corpus, findings and unfinished runs persist. Come back and pick up exactly where you left off — the agent recalls what you already researched.",
  },
  {
    glyph: "🔔",
    title: "A standing monitor",
    body: "The agent keeps watching arXiv and Semantic Scholar for new papers matching your open questions, and surfaces them for one-click add to your corpus.",
  },
];

const PIPELINE = [
  ["Clarify", "decompose your question into answerable sub-questions"],
  ["Plan", "generate source-specific searches, informed by project memory"],
  ["Research", "a specialist agent searches & ingests papers from arXiv & Semantic Scholar"],
  ["Draft", "write claims, each cited to one source chunk"],
  ["Verify", "quote-match + NLI gate — only survivors ship"],
  ["Assemble", "citations resolve only from verified references"],
];

export default function Landing({ onEnter }: { onEnter: () => void }) {
  return (
    <div className="landing">
      <header className="landing-nav">
        <div className="landing-brand">
          <span className="logo landing-logo">V</span>
          <span>Veriscope</span>
        </div>
        <div className="landing-nav-links">
          <a href="#how">How it works</a>
          <a href="#features">Features</a>
          <button className="btn" onClick={onEnter}>Get started →</button>
        </div>
      </header>

      <section className="landing-hero">
        <span className="landing-pill">Research you can prove</span>
        <h1>
          A research agent that <em>can't</em> make things up.
        </h1>
        <p className="landing-sub">
          Most AI research tools fabricate — plausible summaries with citations
          that are subtly wrong. Veriscope flips the default:{" "}
          <strong>nothing reaches you unless it survives a verification gate.</strong>{" "}
          Every claim is quote-matched to a real source, or it isn't shown.
        </p>
        <div className="landing-cta">
          <button className="btn landing-cta-main" onClick={onEnter}>
            Start researching
          </button>
          <a className="btn btn-ghost" href="#how">See how it works</a>
        </div>
        <div className="landing-proof">
          <span>✓ Verbatim quote-check</span>
          <span>✓ NLI entailment gate</span>
          <span>✓ Honest refusal over guessing</span>
          <span>✓ No fabricated citations, structurally</span>
        </div>
      </section>

      <section id="features" className="landing-features">
        {FEATURES.map((f) => (
          <div key={f.title} className="landing-feature">
            <span className="landing-feature-glyph">{f.glyph}</span>
            <h3>{f.title}</h3>
            <p>{f.body}</p>
          </div>
        ))}
      </section>

      <section id="how" className="landing-how">
        <span className="overline">The multi-agent pipeline</span>
        <h2>Six steps, one guarantee</h2>
        <div className="landing-steps">
          {PIPELINE.map(([name, desc], i) => (
            <div key={name} className="landing-step">
              <span className="landing-step-n mono">{i + 1}</span>
              <div>
                <b>{name}</b>
                <p>{desc}</p>
              </div>
              {i < PIPELINE.length - 1 && <span className="landing-step-arrow">↓</span>}
            </div>
          ))}
        </div>
      </section>

      <section className="landing-final">
        <h2>Stop re-verifying by hand.</h2>
        <p>See the evidence trail behind every sentence.</p>
        <button className="btn landing-cta-main" onClick={onEnter}>
          Get started →
        </button>
      </section>

      <footer className="landing-foot">
        <span>Veriscope — verifiable research, by construction.</span>
        <span className="mono">arXiv · Semantic Scholar</span>
      </footer>
    </div>
  );
}
