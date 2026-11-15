// Demo hook — the opening 35 seconds of the product demo, and a standalone
// argument on the landing page for why Veriscope exists.
//
// It shows a DIFFERENT tool: a generic, unbranded AI assistant answering a
// research question confidently, with three real-looking citations. Clicking
// citation [1] opens the cited paper at the exact passage — which supports half
// the sentence and explicitly disowns the other half. The citation is real, the
// paper is real, the answer is not supported. That is the failure the whole
// grounding contract (CLAUDE.md, G1/G2) exists to make impossible.
//
// Two deliberate departures from the design system, both load-bearing:
//   1. It does NOT use Veriscope tokens. Cool grey + indigo + Inter-ish system
//      UI is the point — the reader must feel they are looking at somebody
//      else's product, so that closing it (beat 6) lands as a change of world.
//      Every value is local to #vhook and cannot leak; nothing here is a token
//      regression, it is a prop wearing a costume.
//   2. The papers are fictional (invented authors, invented DOI). Putting an
//      unsupported claim in a real researcher's mouth to sell our own product
//      would be the exact sin this component is about.

import { useCallback, useEffect, useRef, useState } from "react";

// Beat 6 is the handoff: the overlay dissolves and the landing page is already
// underneath — in the demo this is the 0:35 cut, with no tab change.
const BEATS = [
  "The answer",
  "Open source [1]",
  "What it actually says",
  "Back to the answer",
  "The problem",
  "Dissolve to Veriscope",
];

export default function DemoHook({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [beat, setBeat] = useState(0);
  const [hudOn, setHudOn] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const passageRef = useRef<HTMLDivElement>(null);
  const timers = useRef<number[]>([]);
  const hudTimer = useRef<number>();

  const clearTimers = () => { timers.current.forEach(clearTimeout); timers.current = []; };
  const at = (ms: number, fn: () => void) => { timers.current.push(window.setTimeout(fn, ms)); };

  // Eased scroll of the paper column down to the quoted passage. Animating
  // scrollTop directly (not scrollIntoView) so the pace is ours, not the
  // browser's — it has to sit under a spoken line.
  const scrollToPassage = useCallback((dur: number) => {
    const box = scrollRef.current, mark = passageRef.current;
    if (!box || !mark) return;
    const target = Math.max(0, mark.offsetTop - box.clientHeight * 0.34);
    const from = box.scrollTop, delta = target - from, t0 = performance.now();
    const step = (now: number) => {
      const p = Math.min(1, (now - t0) / dur);
      box.scrollTop = from + delta * (1 - Math.pow(1 - p, 3));
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }, []);

  const go = useCallback((n: number) => {
    const next = Math.max(0, Math.min(BEATS.length - 1, n));
    if (next >= BEATS.length - 1) { onClose(); return; }
    setBeat(next);
  }, [onClose]);

  // Reset to beat 0 whenever the overlay is opened, so every take starts clean.
  useEffect(() => {
    if (!open) return;
    setBeat(0);
    clearTimers();
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
    document.body.classList.add("vhook-locked");
    // Take focus off the button that opened us — otherwise Space re-triggers
    // that button instead of advancing the beat, which is the one key the
    // presenter is holding.
    const opener = document.activeElement as HTMLElement | null;
    opener?.blur();
    rootRef.current?.focus();
    return () => { clearTimers(); document.body.classList.remove("vhook-locked"); opener?.focus(); };
  }, [open]);

  // Paper choreography: land the panel, scroll to the passage, then mark it.
  const [showPaper, setShowPaper] = useState(false);
  const [marked, setMarked] = useState(false);
  useEffect(() => {
    if (!open) return;
    clearTimers();
    if (beat >= 1 && beat <= 2) {
      const opening = !showPaper;
      setShowPaper(true);
      if (opening) {
        setMarked(false);
        if (scrollRef.current) scrollRef.current.scrollTop = 0;
        at(560, () => scrollToPassage(900));
        at(1180, () => setMarked(true));
      } else { setMarked(true); }
    } else {
      setShowPaper(false);
      at(680, () => { setMarked(false); if (scrollRef.current) scrollRef.current.scrollTop = 0; });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [beat, open]);

  const bumpHud = useCallback(() => {
    setHudOn(true);
    clearTimeout(hudTimer.current);
    hudTimer.current = window.setTimeout(() => setHudOn(false), 2200);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === " " || e.key === "ArrowRight" || e.key === "PageDown" || e.key === "Enter") {
        e.preventDefault(); go(beat + 1);
      } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
        e.preventDefault(); go(beat - 1);
      } else if (e.key === "Escape") { onClose(); }
      else if (e.key === "h" || e.key === "H") { setHudOn(v => !v); }
      else if (e.key >= "1" && e.key <= "5") { go(parseInt(e.key, 10) - 1); }
    };
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("mousemove", bumpHud);
    bumpHud();
    return () => {
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("mousemove", bumpHud);
      clearTimeout(hudTimer.current);
    };
  }, [open, beat, go, onClose, bumpHud]);

  const cls = [
    "vhook",
    open ? "on" : "",
    beat === 4 ? "zoom" : "",
    showPaper ? "paper-open" : "",
    marked ? "marked" : "",
    beat === 2 ? "verdict-on" : "",
  ].filter(Boolean).join(" ");

  return (
    <>
      <div
        id="vhook"
        ref={rootRef}
        className={cls}
        role="dialog"
        aria-modal={open}
        aria-label="How AI research tools fail"
        tabIndex={-1}
        aria-hidden={!open}
        onClick={() => go(beat + 1)}
      >
        <div className="vh-app">
          <aside className="vh-side vh-dim">
            <div className="vh-brandrow"><span className="vh-glyph">A</span><span className="vh-brandname">Assistant</span></div>
            <div className="vh-newchat"><span>+</span><span>New chat</span></div>
            <div className="vh-sgroup">Today</div>
            <div className="vh-sitem on">LLMs in literature reviews</div>
            <div className="vh-sitem">Screening automation — cost model</div>
            <div className="vh-sitem">Draft: grant methods section</div>
            <div className="vh-sgroup">Previous 7 days</div>
            <div className="vh-sitem">Retrieval eval metrics explained</div>
            <div className="vh-sitem">Summarise: 4 uploaded PDFs</div>
            <div className="vh-sitem">Meta-analysis vs scoping review</div>
            <div className="vh-sfoot"><span className="vh-avatar" />Research workspace</div>
          </aside>

          <main className="vh-main">
            <div className="vh-top vh-dim">
              <span className="vh-chip"><span className="vh-dot" />Research mode</span>
              <span className="vh-chip">Web + papers</span>
              <span className="vh-spacer" />
              <span className="vh-chip">Share</span>
            </div>

            <div className="vh-scroll"><div className="vh-thread">
              <div className="vh-q vh-dim">
                <span className="vh-qav" />
                <p className="vh-qtext">Do large language models actually improve scientific literature reviews?</p>
              </div>

              <div className="vh-a">
                <span className="vh-aav">A</span>
                <div className="vh-abody">
                  <div className="vh-answer">
                    <p>
                      <span className="vh-claim">
                        Recent studies show that large language model assistants <b>significantly
                        improve</b> both the speed and the reliability of scientific literature
                        reviews.
                        <sup
                          className={`vh-cite ${beat === 0 ? "pulse" : ""} ${beat >= 1 && beat <= 2 ? "hot" : ""}`}
                          onClick={(e) => { e.stopPropagation(); go(beat === 0 ? 1 : beat + 1); }}
                        >1</sup>
                      </span>{" "}
                      In controlled evaluations, LLM-assisted screening cut reviewer workload by
                      roughly 40–60% while preserving inclusion accuracy, and automated synthesis
                      pipelines produced drafts rated comparable to those written by domain
                      experts.<sup className="vh-cite">2</sup>
                    </p>
                    <p className="vh-dim">
                      The effect appears consistent across biomedical and computer-science corpora,
                      which suggests the gains are general rather than domain-specific.
                      <sup className="vh-cite">3</sup> Reported limitations centre on prompt
                      sensitivity and on the cost of validating model output at scale, rather than
                      on whether the benefit exists.
                    </p>
                  </div>

                  <div className="vh-srcwrap vh-dim">
                    <div className="vh-srclabel">Sources</div>
                    <div className="vh-srcs">
                      <div className="vh-src">
                        <div className="vh-srcn">[1]</div>
                        <div className="vh-srct">Human–AI Screening in Systematic Reviews: A Randomised Evaluation</div>
                        <div className="vh-srcm">Aldridge et al. · 2024</div>
                      </div>
                      <div className="vh-src">
                        <div className="vh-srcn">[2]</div>
                        <div className="vh-srct">Automated Synthesis Drafting for Biomedical Evidence Reviews</div>
                        <div className="vh-srcm">Verhoeven &amp; Park · 2025</div>
                      </div>
                      <div className="vh-src">
                        <div className="vh-srcn">[3]</div>
                        <div className="vh-srct">Benchmarking Retrieval-Augmented Review Assistants Across Domains</div>
                        <div className="vh-srcm">Okafor et al. · 2025</div>
                      </div>
                    </div>
                    <div className="vh-tools"><span>↻ Regenerate</span><span>⧉ Copy</span><span>↑ Export</span></div>
                  </div>
                </div>
              </div>
            </div></div>

            <div className="vh-composer"><div className="vh-cbox">
              <span className="vh-cph">Ask a follow-up…</span><span className="vh-csend">↑</span>
            </div></div>

            <div className="vh-scrim" />
            <section className="vh-paper">
              <div className="vh-phead">
                <div className="vh-pmeta">
                  <span className="vh-pbadge">SOURCE [1]</span>
                  <span>Journal of Research Synthesis Methods · 2024</span>
                  <span>·</span><span>doi:10.4193/jrsm.2024.0117</span>
                </div>
                <div className="vh-ptitle">Human–AI Screening in Systematic Reviews: A Randomised Evaluation</div>
                <div className="vh-pauth">M. Aldridge, S. Whitlock, J. Ferreira, N. Bhatt — Centre for Evidence Methods</div>
              </div>

              <div className="vh-pscroll" ref={scrollRef}>
                <h4>Abstract</h4>
                <p>Large language models are increasingly proposed as assistants for
                title-and-abstract screening. We report a randomised evaluation in which twelve
                reviewers screened 2,400 abstracts across two clinical topics, with and without
                model assistance, measuring both time-on-task and the accuracy of inclusion
                decisions against a consensus reference set.</p>

                <h4>3. Methods</h4>
                <p>Reviewers were block-randomised to assisted and unassisted arms. The assisted arm
                received a model-generated relevance score and a two-sentence rationale for each
                abstract. Decisions were recorded with per-abstract timing. The reference standard
                was established by two senior reviewers with a third adjudicating disagreements,
                blinded to arm allocation.</p>
                <p>Because reviewers were drawn from a single review team, we treated the study as a
                within-team efficiency evaluation and pre-registered time-on-task as the primary
                endpoint. Decision quality was a secondary endpoint, and the trial was not powered
                to detect small differences in it.</p>

                <div className="vh-pg">— page 7 —</div>
                <h4>4. Results</h4>
                <p>Median screening time fell from 41.5 to 24.8 minutes per 100 abstracts in the
                assisted arm (a 40.2% reduction; 95% CI 33.1–46.8), and the effect was stable across
                both topics.</p>

                <div className="vh-hlwrap" ref={passageRef}>
                  <span className="vh-hlmark" />
                  <p><span className="vh-hl">However, the reduction in workload did not translate
                  into improved decision quality. Inclusion accuracy was 82.1% in the assisted arm
                  and 84.6% in the unassisted arm — a difference that was not statistically
                  significant (p = 0.31), and whose confidence interval is compatible with a small
                  decrease in accuracy under assistance. We therefore make no claim that model
                  assistance improves the reliability of screening; our results speak to speed
                  alone.</span></p>
                </div>

                <p>Sensitivity analyses excluding the two fastest reviewers did not change the
                direction of either result.</p>

                <h4>5. Discussion</h4>
                <p>These findings should not be generalised beyond title-and-abstract screening.
                Full-text appraisal, data extraction and synthesis were outside the scope of this
                evaluation, and the single-team design limits transportability to other review
                contexts.</p>
                <p>We note that efficiency gains in screening are frequently reported alongside
                claims of improved review quality. Our data do not support that pairing.</p>
              </div>

              <div className="vh-verdict">
                <div className="vh-vrow">
                  <span className="vh-vtag">Answer</span>
                  <p className="vh-vtxt">“…significantly improve both the speed <em>and the
                  reliability</em> of scientific literature reviews.”</p>
                </div>
                <div className="vh-vsplit" />
                <div className="vh-vrow">
                  <span className="vh-vtag">Paper p.7</span>
                  <p className="vh-vtxt">“…<em>did not translate into improved decision quality</em>
                  … not statistically significant (p = 0.31) … <em>we make no claim</em> that model
                  assistance improves the reliability of screening.”</p>
                </div>
                <div className="vh-vres">
                  <span className="vh-ok"><b>Speed</b> — supported</span>
                  <span className="vh-no"><b>Reliability</b> — contradicted by the cited source</span>
                </div>
              </div>
            </section>
          </main>
        </div>
      </div>

      {open && (
        <div className={`vhook-hud ${hudOn ? "show" : ""}`} onClick={(e) => e.stopPropagation()}>
          <span className="k">{beat + 1}/{BEATS.length}</span>
          <b>{BEATS[beat]}</b>
          <button className="hb" onClick={() => go(beat - 1)} title="Back (←)">‹</button>
          <button className="hb" onClick={() => go(beat + 1)} title="Advance (Space / →)">›</button>
          <button className="hb" onClick={onClose} title="Close (Esc)">✕</button>
        </div>
      )}
    </>
  );
}
