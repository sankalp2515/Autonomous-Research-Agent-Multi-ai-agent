// Marketing landing — the first thing a visitor sees, before auth. It SHOWS the
// product's signature moment (a verified claim + its evidence trail) rather than
// only describing it, contrasts fabrication vs. verification, walks the real
// pipeline, and hands off to the workspace. Every claim here is true to the
// shipped product: sources are arXiv + Semantic Scholar (+ uploads), export is
// Markdown/BibTeX/RIS/Print, and the differentiators (NLI score, honest gaps,
// tensions, closed corpus) are real. Scoped under #vlp so its styles never leak.

import { useEffect, useState } from "react";

const scrollTo = (id: string) =>
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });

// ── Data ──────────────────────────────────────────────────────────────────
const SCENARIOS: Record<string, { bad: string; note: string; claim: JSX.Element; quote: string }> = {
  ml: {
    bad: "“Studies show a ~15% improvement across most benchmarks.”",
    note: "Plausible. Unsourced. Possibly invented. You re-check it by hand.",
    claim: (<>“Improved zero-shot accuracy by 12.3 points<sup>1</sup>.” <em>— or an honest gap.</em></>),
    quote: "“…a 12.3-point absolute gain in zero-shot top-1 accuracy relative to the supervised baseline.”",
  },
  sys: {
    bad: "“This method is state-of-the-art and widely adopted in production.”",
    note: "A vibe, not a number. No source, no benchmark, no conditions.",
    claim: (<>“Cut p99 latency by 43% on the YCSB-A workload<sup>2</sup>.” <em>— or an honest gap.</em></>),
    quote: "“…observed a 43% reduction in p99 tail latency under the YCSB-A read-heavy workload.”",
  },
};

const FEAT_CITE: Record<number, { h: string; nli: string; q: string }> = {
  1: { h: "GROUNDING SPAN · [1]", nli: "NLI 1.00", q: "“The CNN-LSTM hybrid model achieved significantly higher accuracy, meaning it reached 96.3%.”" },
  2: { h: "GROUNDING SPAN · [2]", nli: "NLI 1.00", q: "“A compact architecture with 76,651 trainable parameters provided lower computational overhead and faster inference.”" },
};

const PIPELINE = [
  { n: "Clarify", lab: "Query scoping", desc: "Decompose your question into answerable sub-questions and parse any constraints (year, citation floor).", gate: "Query validated as researchable", in: "'Approaches to reducing hallucination in RAG, with trade-offs?'", out: "3 sub-questions: retrieval, grounding, evaluation", detail: "Off-topic or non-research prompts are rejected here — a run never launches blindly." },
  { n: "Plan", lab: "Evidence mapping", desc: "Generate source-specific searches across arXiv & Semantic Scholar, informed by project memory.", gate: "Searches cover each sub-question", in: "Sub-questions + project memory", out: "Parallel arXiv / Semantic Scholar queries + HyDE vectors", detail: "Retrieval is hybrid dense-sparse; earlier findings in the project steer new searches." },
  { n: "Research", lab: "Search & ingest", desc: "A specialist agent searches, fetches, and ingests papers into this project’s corpus.", gate: "Sources parsed & chunked with page offsets", in: "Ranked candidate papers", out: "Ingested corpus of quotable chunks (per-page)", detail: "Every chunk keeps its document, section, and page range so a quote can be traced back exactly." },
  { n: "Draft", lab: "Candidate claims", desc: "Write claims, each attached to exactly one source chunk and a verbatim candidate quote.", gate: "Each claim cites one chunk + a ≥12-char quote", in: "Retrieved SOURCE chunks", out: "Draft claim + candidate grounding quote", detail: "No flowing prose is authored — the report’s density comes only from grounded findings." },
  { n: "Verify", lab: "Quote-match + NLI gate", desc: "Each claim must exact-match its quote AND be entailed by the source. Failures are refused.", gate: "Verbatim match ✓ AND NLI entailment passes", in: "Premise: source chunk / Hypothesis: claim", out: "PASS → ships · FAIL → dropped or honest gap", detail: "This is the heart of Veriscope: a claim that isn’t entailed by its source never reaches you." },
  { n: "Assemble", lab: "Audit-ready report", desc: "Render only verified claims; citations resolve solely from verified references; gaps are stated honestly.", gate: "Zero ungrounded claims in the output", in: "Verified claims + evidence", out: "Interactive report — click any citation for its span", detail: "Export to Markdown, BibTeX, RIS, or Print/PDF — every entry carries its grounding quote." },
];

const FAQ = [
  { q: "How does Veriscope avoid fabricating citations?", a: "Every generated claim must pass two checks before it renders: a verbatim substring match against a real source chunk, and a Natural Language Inference (NLI) entailment check confirming the source text actually supports the claim. If either fails, the claim is dropped and Veriscope shows an honest gap instead of guessing." },
  { q: "What sources does Veriscope search?", a: "Veriscope searches arXiv and Semantic Scholar, and ingests the full text it can retrieve into a per-project corpus. You can also upload your own PDFs so synthesis is grounded in your private library. Answers are grounded only in that closed corpus — never the open web." },
  { q: "Which research fields does it work best for?", a: "The current MVP is built for computer-science and engineering research (its sources are arXiv + Semantic Scholar). Biomedical and social-science coverage is limited today and is flagged honestly in-product when a question falls outside scope — broader coverage is on the roadmap." },
  { q: "How does it handle conflicting studies?", a: "Where two individually-verified claims disagree, Veriscope surfaces the pair as a “tension” with both sources and their quotes, so you can weigh the difference in method or dataset yourself rather than getting one averaged-away answer." },
  { q: "Can I export reports?", a: "Yes — one-click export to Markdown, BibTeX, RIS, and Print/PDF. Every reference carries its verbatim grounding span, page range, and NLI score, so the export is audit-ready." },
];

// Minimal inline icons (stroke, currentColor)
const I = {
  check: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>,
  shield: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path d="M9 12l2 2 4-4m5.6-1A11.9 11.9 0 0112 2.9 11.9 11.9 0 013.4 6 12 12 0 003 9c0 5.6 3.8 10.3 9 11.6 5.2-1.3 9-6 9-11.6 0-1-.1-2-.4-3z" /></svg>,
  tick: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path d="M5 13l4 4L19 7" /></svg>,
  arrow: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path d="M14 5l7 7-7 7M21 12H3" /></svg>,
  copy: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>,
  table: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path d="M3 3v18h18" /><path d="M7 14l4-4 3 3 5-6" /></svg>,
  chat: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path d="M8 12h8M8 8h8M8 16h5M4 4h16v12H8l-4 4z" /></svg>,
  bell: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path d="M15 17h5l-1.4-1.4A2 2 0 0118 14.2V11a6 6 0 00-4-5.7V5a2 2 0 10-4 0v.3A6 6 0 006 11v3.2a2 2 0 01-.6 1.4L4 17h5m6 0v1a3 3 0 11-6 0v-1" /></svg>,
  gap: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path d="M12 9v4m0 4h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" /></svg>,
  tension: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path d="M8 7l-5 5 5 5M16 7l5 5-5 5" /></svg>,
  corpus: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path d="M12 2l8 4v6c0 5-3.4 9.4-8 10-4.6-.6-8-5-8-10V6z" /></svg>,
};

export default function Landing({ onEnter }: { onEnter: () => void }) {
  const [scenario, setScenario] = useState<keyof typeof SCENARIOS>("ml");
  const [featCite, setFeatCite] = useState(1);
  const [plStep, setPlStep] = useState(4);
  const [faqOpen, setFaqOpen] = useState(0);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const io = new IntersectionObserver(
      (es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }),
      { rootMargin: "0px 0px -8% 0px" }
    );
    document.querySelectorAll("#vlp .vlp-reveal").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);

  const sc = SCENARIOS[scenario];
  const fc = FEAT_CITE[featCite];
  const step = PIPELINE[plStep];

  return (
    <div id="vlp">
      {/* NAV */}
      <header className="vlp-nav"><div className="vlp-wrap vlp-nav-in">
        <div className="vlp-brand"><span className="vlp-logo">V</span><div><b>Veriscope</b><span className="sub">Verifiable research</span></div></div>
        <nav className="vlp-nav-links">
          <a onClick={() => scrollTo("vlp-contrast")}>The contrast</a>
          <a onClick={() => scrollTo("vlp-features")}>Features</a>
          <a onClick={() => scrollTo("vlp-pipeline")}>Pipeline</a>
          <a onClick={() => scrollTo("vlp-difference")}>Why us</a>
          <a onClick={() => scrollTo("vlp-faq")}>FAQ</a>
          <a href="#/docs">Docs</a>
        </nav>
        <div className="vlp-nav-right">
          <span className="vlp-nav-pill">{I.shield}NLI entailment gate</span>
          <button className="vlp-btn vlp-btn-accent" onClick={onEnter}>Get started {I.arrow}</button>
        </div>
      </div></header>

      {/* HERO */}
      <section className="vlp-hero"><div className="vlp-wrap vlp-hero-grid">
        <div className="vlp-reveal">
          <span className="vlp-eyebrow"><span className="vlp-eyedot" />Research you can prove</span>
          <h1>A research agent that <em>can’t</em> make things up.</h1>
          <p className="vlp-lead">Most AI research tools fabricate — plausible summaries with citations that are subtly wrong. Veriscope flips the default: <b>nothing reaches you unless it survives a verification gate.</b> Every claim is quote-matched to a real source, or it isn’t shown.</p>
          <div className="vlp-hero-cta">
            <button className="vlp-btn vlp-btn-accent" onClick={onEnter}>Start researching {I.arrow}</button>
            <button className="vlp-btn vlp-btn-ghost" onClick={() => scrollTo("vlp-pipeline")}>See how it works</button>
          </div>
          <div className="vlp-chips">
            <span className="vlp-chip">{I.check}Verbatim quote-check</span>
            <span className="vlp-chip">{I.shield}NLI entailment gate</span>
            <span className="vlp-chip">{I.tick}Honest refusal over guessing</span>
          </div>
        </div>
        <div className="vlp-reveal">
          <div className="vlp-proof">
            <div className="vlp-proof-head"><span className="vlp-proof-dot" /><span className="vlp-proof-title">Verified claim</span><span className="vlp-proof-badge">gate passed</span></div>
            <p className="vlp-proof-claim">Contrastive pre-training improved zero-shot accuracy by <mark>12.3 points</mark> over the supervised baseline<sup>1</sup></p>
            <div className="vlp-proof-span">
              <div className="vlp-proof-sh"><span>Grounding span · p.7</span>
                <button onClick={() => { navigator.clipboard?.writeText("…yields a 12.3-point absolute gain in zero-shot top-1 accuracy relative to the supervised baseline."); setCopied(true); setTimeout(() => setCopied(false), 1600); }}>{I.copy}{copied ? "Copied" : "Copy span"}</button>
              </div>
              <p className="vlp-proof-quote">“…yields a <mark>12.3-point</mark> absolute gain in zero-shot top-1 accuracy relative to the supervised baseline.”</p>
              <div className="vlp-proof-meta"><span className="vlp-mono">Radford et al. · 2021 · arXiv</span>
                <span className="vlp-proof-nli">NLI entailment <b>0.94</b><span className="vlp-proof-bar"><i style={{ width: "94%" }} /></span></span></div>
            </div>
          </div>
        </div>
      </div></section>

      {/* TRUST */}
      <div className="vlp-trust"><div className="vlp-trust-in">
        <span>Grounded only in peer-reviewed &amp; preprint literature</span><span className="vlp-tdot">·</span>
        <span className="vlp-src">arXiv · Semantic Scholar</span><span className="vlp-tdot">·</span>
        <span>plus your own uploaded papers</span>
      </div></div>

      {/* CONTRAST */}
      <section className="vlp-section" id="vlp-contrast"><div className="vlp-wrap">
        <div className="vlp-sec-head vlp-reveal">
          <span className="vlp-overline">The contrast</span>
          <h2>Plausible prose vs. verifiable evidence</h2>
          <p>The same finding, two ways. One you re-check by hand. One that traces to a verbatim quote and an entailment score — or is honestly refused.</p>
          <div className="vlp-sc-tabs">
            <button className={scenario === "ml" ? "active" : ""} onClick={() => setScenario("ml")}>LLM evaluation</button>
            <button className={scenario === "sys" ? "active" : ""} onClick={() => setScenario("sys")}>Systems &amp; RL</button>
          </div>
        </div>
        <div className="vlp-contrast vlp-reveal">
          <div className="vlp-ct vlp-ct-bad">
            <div className="vlp-ct-h"><b>Typical AI research tool</b><span className="vlp-ct-tag">UNVERIFIED</span></div>
            <p className="vlp-ct-claim">{sc.bad}</p>
            <p className="vlp-ct-note">{sc.note}</p>
          </div>
          <div className="vlp-ct-arrow">→</div>
          <div className="vlp-ct vlp-ct-ok">
            <div className="vlp-ct-h"><b>Veriscope</b><span className="vlp-ct-tag">NLI ENTAILED</span></div>
            <p className="vlp-ct-claim">{sc.claim}</p>
            <p className="vlp-ct-quote">{sc.quote}</p>
          </div>
        </div>
      </div></section>

      {/* FEATURES */}
      <section className="vlp-section" id="vlp-features"><div className="vlp-wrap">
        <div className="vlp-sec-head vlp-reveal"><span className="vlp-overline">What you get</span><h2>Four ways to research with proof</h2>
          <p>Every surface below is built on the same guarantee: click any citation and see the exact source span behind it.</p></div>

        {/* 01 */}
        <div className="vlp-feat vlp-reveal">
          <div className="vlp-feat-copy">
            <div className="vlp-fh"><span className="vlp-fn">01</span><span className="vlp-ft">Sentence-level auditability</span></div>
            <h3>Verified by construction</h3><div className="vlp-rule" />
            <p>Generate a report where every sentence carries a verbatim quote that exact-matches a real source chunk and passes an entailment check. Claims that fail are dropped — not shown. Click a citation and the exact grounding span pins beside it.</p>
            <span className="vlp-stat">{I.check}Only gate-verified claims ship</span>
          </div>
          <div className="vlp-feat-visual sage">
            <div className="vlp-card">
              <div className="vlp-card-h"><b>Verified report · §2 Results</b><span className="vlp-tag">100% quote-entailed</span></div>
              <p className="vlp-mini-claim">A CNN-LSTM hybrid reached 96.3% fault-classification accuracy<button className={`vlp-mini-cite ${featCite === 1 ? "on" : "off"}`} onClick={() => setFeatCite(1)}>1</button> while a compact 76,651-parameter model cut inference cost<button className={`vlp-mini-cite ${featCite === 2 ? "on" : "off"}`} onClick={() => setFeatCite(2)}>2</button>.</p>
              <div className="vlp-inspector">
                <div className="vlp-ih"><span>{fc.h}</span><span className="ok">{fc.nli}</span></div>
                <p className="vlp-iq">{fc.q}</p>
              </div>
            </div>
          </div>
        </div>

        {/* 02 */}
        <div className="vlp-feat vlp-reveal">
          <div className="vlp-feat-copy">
            <div className="vlp-fh"><span className="vlp-fn">02</span><span className="vlp-ft">Automated extraction</span></div>
            <h3>Compare across papers</h3><div className="vlp-rule" />
            <p>Pick papers from your library and compare them side by side. Each cell is drafted from that paper alone and quote-checked, so every value is click-to-source — spot consensus and contradiction at a glance.</p>
            <span className="vlp-stat">{I.table}Every cell is a verified claim</span>
          </div>
          <div className="vlp-feat-visual claret">
            <div className="vlp-card">
              <div className="vlp-card-h"><b>Cross-paper matrix</b><span className="vlp-tag">click-to-source</span></div>
              <table className="vlp-mini-tbl"><thead><tr><th>Study</th><th>Result</th><th>NLI</th></tr></thead><tbody>
                <tr><td>Ürgen 2026 <sup>↗</sup></td><td>R²=0.8901 · RMSE 13.28</td><td><span className="vlp-nli">1.00</span></td></tr>
                <tr><td>Lin 2026 <sup>↗</sup></td><td>Smaller param space, faster</td><td><span className="vlp-nli">0.93</span></td></tr>
                <tr><td>IoT Review <sup>↗</sup></td><td>CNN-LSTM 96.3% accuracy</td><td><span className="vlp-nli">1.00</span></td></tr>
              </tbody></table>
            </div>
          </div>
        </div>

        {/* 03 */}
        <div className="vlp-feat vlp-reveal">
          <div className="vlp-feat-copy">
            <div className="vlp-fh"><span className="vlp-fn">03</span><span className="vlp-ft">Grounded conversation</span></div>
            <h3>Chat any selection</h3><div className="vlp-rule" />
            <p>Select papers, claims or answers from anywhere and build a one-off chat context — grounded in exactly those sources, and still gate-verified. No open-web guessing; the answer cites the selection or refuses.</p>
            <span className="vlp-stat">{I.chat}Answers cite your selection — or refuse</span>
          </div>
          <div className="vlp-feat-visual sage">
            <div className="vlp-card">
              <div className="vlp-card-h"><b>Grounded chat</b><span className="vlp-tag">2 sources in context</span></div>
              <div className="vlp-sel-row"><span className="vlp-sel-chip">◆ claim · SHAP consistency</span><span className="vlp-sel-chip">◆ paper · Lin 2026</span></div>
              <p className="vlp-chat-a">SHAP is favored for its game-theoretic consistency; both selected sources pair it with Bayesian uncertainty for real-time streams.<sup>5</sup></p>
            </div>
          </div>
        </div>

        {/* 04 */}
        <div className="vlp-feat vlp-reveal">
          <div className="vlp-feat-copy">
            <div className="vlp-fh"><span className="vlp-fn">04</span><span className="vlp-ft">Continuous pipeline</span></div>
            <h3>A standing monitor</h3><div className="vlp-rule" />
            <p>The agent keeps watching arXiv and Semantic Scholar for new papers matching your open questions, and surfaces them for one-click add to your corpus — already quote-checked against what you’re tracking.</p>
            <span className="vlp-stat">{I.bell}Notifies you only on verifiable matches</span>
          </div>
          <div className="vlp-feat-visual claret">
            <div className="vlp-card">
              <div className="vlp-card-h"><b>Standing monitor</b><span className="vlp-tag" style={{ color: "var(--ok)" }}>● watching</span></div>
              <div className="vlp-mon">
                <span className="vlp-mon-m">NEW MATCH · arXiv 2609.04412</span>
                <span className="vlp-mon-t">Uncertainty-calibrated transformers for remaining-useful-life prediction</span>
                <button className="vlp-mon-add" onClick={onEnter}>＋ Add to corpus</button>
              </div>
            </div>
          </div>
        </div>
      </div></section>

      {/* PIPELINE */}
      <section className="vlp-section vlp-pipeline" id="vlp-pipeline"><div className="vlp-wrap">
        <div className="vlp-sec-head vlp-reveal"><span className="vlp-overline">The multi-agent pipeline</span>
          <h2>Stop re-verifying by hand.</h2>
          <p>Six steps, one guarantee — every sentence is quote-matched and entailment-checked before it reaches your report.</p></div>
        <div className="vlp-pl-steps vlp-reveal">
          {PIPELINE.map((s, i) => (
            <button key={s.n} className={`vlp-pl-step ${i === plStep ? "active" : ""}`} onClick={() => setPlStep(i)}>
              <span className="vlp-pn">0{i + 1}</span><h4>{s.n}</h4><span className="vlp-pl-lab">{s.lab}</span>
            </button>
          ))}
        </div>
        <div className="vlp-pl-detail vlp-reveal">
          <div className="vlp-pl-detail-h">
            <div><span className="vlp-pstep">Step 0{plStep + 1} of 06</span><h3>{step.n}: {step.lab}</h3><p>{step.desc}</p></div>
            <span className="vlp-pl-gate">Gate: {step.gate}</span>
          </div>
          <div className="vlp-pl-io">
            <div className="vlp-box vlp-in"><span className="k">STAGE INPUT</span><p>{step.in}</p></div>
            <div className="vlp-box vlp-out"><span className="k">VERIFIED OUTPUT</span><p>{step.out}</p></div>
          </div>
          <p className="vlp-pl-note">{step.detail}</p>
        </div>
      </div></section>

      {/* DIFFERENCE */}
      <section className="vlp-section" id="vlp-difference"><div className="vlp-wrap">
        <div className="vlp-sec-head vlp-reveal"><span className="vlp-overline">Why Veriscope</span><h2>What makes us different</h2>
          <p>Most AI research tools synthesize plausible text and link a paper. Veriscope is verifiable by construction — and honest when the evidence isn’t there.</p></div>
        <div className="vlp-diff-grid">
          <div className="vlp-diff vlp-reveal"><div className="vlp-di">{I.shield}</div>
            <h3>An entailment score, not just a link</h3>
            <p>Every claim carries a Natural Language Inference score proving the source text actually entails it — not merely that a paper was cited nearby.</p>
            <span className="vlp-vs">Typical tools: a linked paper. <b>Veriscope: a verified score per sentence.</b></span></div>
          <div className="vlp-diff vlp-reveal"><div className="vlp-di">{I.gap}</div>
            <h3>Honest refusal &amp; labeled gaps</h3>
            <p>When the corpus can’t support a claim, Veriscope says so — a designed “evidence gap”, never a confident guess dressed up as fact.</p>
            <span className="vlp-vs">Typical tools: best-effort synthesis. <b>Veriscope: refuses over fabricating.</b></span></div>
          <div className="vlp-diff vlp-reveal"><div className="vlp-di">{I.tension}</div>
            <h3>Tensions, surfaced</h3>
            <p>Where two verified sources disagree, Veriscope shows both sides with their quotes — real disagreements to weigh, not averaged away.</p>
            <span className="vlp-vs">Typical tools: one smoothed answer. <b>Veriscope: shows the conflict.</b></span></div>
          <div className="vlp-diff vlp-reveal"><div className="vlp-di">{I.corpus}</div>
            <h3>Closed corpus by default</h3>
            <p>Answers are grounded only in peer-reviewed literature and your own library — no open-web drift. You always know exactly what it read.</p>
            <span className="vlp-vs">Typical tools: the whole web. <b>Veriscope: a corpus you control.</b></span></div>
        </div>
      </div></section>

      {/* FAQ */}
      <section className="vlp-section" id="vlp-faq"><div className="vlp-wrap">
        <div className="vlp-sec-head vlp-reveal"><span className="vlp-overline">FAQ</span><h2>Straight answers</h2></div>
        <div className="vlp-faq">
          {FAQ.map((f, i) => (
            <div key={i} className={`vlp-qa ${faqOpen === i ? "open" : ""}`} onClick={() => setFaqOpen(faqOpen === i ? -1 : i)}>
              <div className="vlp-qa-q"><h4>{f.q}</h4><span className="vlp-pm">{faqOpen === i ? "−" : "+"}</span></div>
              <div className="vlp-qa-a">{f.a}</div>
            </div>
          ))}
        </div>
      </div></section>

      {/* FINAL CTA */}
      <section className="vlp-section" style={{ paddingTop: 0 }}><div className="vlp-wrap">
        <div className="vlp-final vlp-reveal">
          <span className="vlp-overline">Stop re-verifying by hand</span>
          <h2>See the evidence trail behind every sentence.</h2>
          <p>Grounded research where every claim traces to a verbatim quote and an entailment score — or an honest gap.</p>
          <button className="vlp-btn vlp-final-btn" onClick={onEnter}>Get started {I.arrow}</button>
        </div>
      </div></section>

      {/* FOOTER */}
      <footer className="vlp-footer"><div className="vlp-footer-in">
        <span className="vlp-fb"><span className="vlp-logo sm">V</span>Veriscope — verifiable research, by construction.</span>
        <span className="vlp-src">arXiv · Semantic Scholar</span>
        <nav className="vlp-foot-links"><a href="#/docs">Documentation</a><a href="#/legal/privacy">Privacy</a><a href="#/legal/terms">Terms</a><a href="mailto:support@veriscope.app">Contact</a></nav>
      </div></footer>
    </div>
  );
}
