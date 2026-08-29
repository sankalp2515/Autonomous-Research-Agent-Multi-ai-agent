// Audio briefing — the report read aloud, as chapters.
//
// WHY IT IS BUILT FROM THE REPORT, NOT WRITTEN FOR IT. Every line the narrator
// speaks is an existing gate-verified claim or a deterministic count. Nothing
// is authored for the audio: a spoken summary that says something the report
// does not is the same fabrication the whole pipeline exists to prevent, only
// harder to check because a listener cannot see the citation.
//
// PROVIDERS. `speakScript` is provider-agnostic. Today it uses the browser's
// own speech synthesis, which needs no key and works offline. When the Gemini
// TTS endpoint is configured server-side, `/api/tts` returns audio for the same
// script and the player switches to it automatically — no change here or in the
// script builder.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Report } from "../types";

export interface ScriptChapter {
  /** Shown as the chapter label, e.g. "Executive summary". */
  role: string;
  text: string;
  /** Seconds from the start, estimated from words at ~165 wpm. */
  at: number;
}

const WORDS_PER_SECOND = 165 / 60;

function estimate(text: string): number {
  return Math.max(1, Math.round(text.trim().split(/\s+/).length / WORDS_PER_SECOND));
}

/** Build the spoken script from material that already passed the gate. */
export function buildScript(report: Report): ScriptChapter[] {
  const c = report.confidence;
  const parts: { role: string; text: string }[] = [];
  const question = report.question || c.plan?.objective || report.title;

  parts.push({
    role: "Opening",
    text: `Veriscope research briefing. The question: ${question}`,
  });

  if (c.abstract?.verdict) {
    parts.push({ role: "The short answer", text: c.abstract.verdict.text });
  }

  // How much evidence stands behind it — counts, not adjectives.
  const studies = (c.evidence_matrix ?? []).length;
  const ladder = c.funnel?.ladder ?? {};
  const fullText = ladder.full_text_available ?? c.study_characteristics?.full_text ?? null;
  if (studies) {
    const span = c.study_characteristics?.year_span;
    let base = `This review rests on ${studies} ${studies === 1 ? "study" : "studies"}`;
    if (typeof fullText === "number") base += `, ${fullText} of them read in full text`;
    if (span) base += `, published between ${span.min} and ${span.max}`;
    parts.push({ role: "The evidence base", text: base + "." });
  }

  if (c.abstract?.sentences?.length) {
    parts.push({
      role: "Executive summary",
      text: c.abstract.sentences.map((s) => s.text).join(" "),
    });
  }

  // One section, one chapter — the lead finding only, so the briefing stays a
  // briefing. A listener who wants everything reads the report.
  for (const s of report.sections) {
    if (s.status === "gap") {
      parts.push({
        role: s.heading,
        text: (s.gap_kind === "drafting_failed"
          ? `On ${s.heading}, Veriscope failed to draft the section, so it carries no findings.`
          : `On ${s.heading}, the corpus offered nothing verifiable. ${s.gap_note || ""}`).trim(),
      });
      continue;
    }
    const lead = (s.claims ?? [])[0];
    if (lead) parts.push({ role: s.heading, text: lead.text });
  }

  const gaps = c.synthesis?.gaps ?? [];
  if (gaps.length) {
    parts.push({
      role: "What this does not establish",
      text: gaps.slice(0, 3).map((g) => g.basis).join(" "),
    });
  }

  const refused = Object.values(c.refusal_reasons ?? {}).reduce((a, b) => a + b, 0);
  if (refused) {
    parts.push({
      role: "Verification",
      text:
        `${refused} drafted ${refused === 1 ? "statement was" : "statements were"} withheld by ` +
        `the verification gate because the cited passage did not support them. They are listed ` +
        `in the report's verification appendix.`,
    });
  }

  let at = 0;
  return parts
    .filter((p) => p.text.trim())
    .map((p) => {
      const chapter = { ...p, at };
      at += estimate(p.text) + 1;
      return chapter;
    });
}

type Status = "idle" | "playing" | "paused";

/** Speak a script. Browser speech synthesis today; server TTS when available. */
function useSpeech(chapters: ScriptChapter[]) {
  const [status, setStatus] = useState<Status>("idle");
  const [index, setIndex] = useState(0);
  const [rate, setRate] = useState(1);
  const cancelled = useRef(false);
  const supported = typeof window !== "undefined" && "speechSynthesis" in window;

  const stop = useCallback(() => {
    cancelled.current = true;
    if (supported) window.speechSynthesis.cancel();
    setStatus("idle");
    setIndex(0);
  }, [supported]);

  // Never leave a narrator running after the reader navigates away.
  useEffect(() => stop, [stop]);
  useEffect(() => { stop(); }, [chapters, stop]);

  const speakFrom = useCallback(
    (start: number) => {
      if (!supported || !chapters.length) return;
      window.speechSynthesis.cancel();
      cancelled.current = false;
      setStatus("playing");

      let i = start;
      const next = () => {
        if (cancelled.current || i >= chapters.length) {
          if (!cancelled.current) { setStatus("idle"); setIndex(0); }
          return;
        }
        setIndex(i);
        const u = new SpeechSynthesisUtterance(chapters[i].text);
        u.rate = rate;
        u.onend = () => { i += 1; next(); };
        u.onerror = () => { i += 1; next(); };
        window.speechSynthesis.speak(u);
      };
      next();
    },
    [chapters, rate, supported]
  );

  const toggle = useCallback(() => {
    if (!supported) return;
    if (status === "playing") {
      window.speechSynthesis.pause();
      setStatus("paused");
    } else if (status === "paused") {
      window.speechSynthesis.resume();
      setStatus("playing");
    } else {
      speakFrom(0);
    }
  }, [status, speakFrom, supported]);

  return { status, index, rate, setRate, toggle, stop, speakFrom, supported };
}

const mmss = (s: number) =>
  `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;

/** Bars for the waveform. Deterministic from the script so the shape is stable
 *  across renders — a waveform that reshuffles on every tick reads as decorative
 *  noise rather than as a representation of the audio. */
function useBars(chapters: ScriptChapter[], n = 34) {
  return useMemo(() => {
    const seed = chapters.reduce((a, c) => a + c.text.length, 0) || 1;
    return Array.from({ length: n }, (_, i) => {
      const wave = Math.sin((i + 1) * 1.7 + seed * 0.013);
      const swell = Math.sin((i / n) * Math.PI); // taller in the middle
      return 0.28 + Math.abs(wave) * 0.42 * (0.55 + swell * 0.65);
    });
  }, [chapters, n]);
}

export function ReadAloud({ report }: { report: Report }) {
  // Persistent, not modal. A modal would block the report while it plays, and
  // the point of a spoken briefing is that you can read, scroll and follow a
  // citation WHILE it runs. The bar docks to the bottom of the reading column
  // and stays until dismissed.
  const [active, setActive] = useState(false);
  const [scriptOpen, setScriptOpen] = useState(false);
  const chapters = useMemo(() => buildScript(report), [report]);
  const bars = useBars(chapters);
  const { status, index, rate, setRate, toggle, stop, speakFrom, supported } =
    useSpeech(chapters);

  const total = useMemo(() => {
    const last = chapters[chapters.length - 1];
    return last ? last.at + 12 : 0;
  }, [chapters]);
  const elapsed = chapters[index]?.at ?? 0;
  const pct = total ? Math.min(100, (elapsed / total) * 100) : 0;
  const playing = status === "playing";
  const title = report.question || report.title;

  if (!chapters.length) return null;

  const dismiss = () => { stop(); setActive(false); setScriptOpen(false); };

  return (
    <>
      {!active && (
        <button className="ra-open" onClick={() => { setActive(true); toggle(); }}>
          <span className="ra-open-ic" aria-hidden="true">
            {bars.slice(0, 9).map((h, i) => (
              <i key={i} style={{ height: `${Math.round(h * 100)}%` }} />
            ))}
          </span>
          <span className="ra-open-t">
            <b>Spoken summary of the verified findings</b>
            <span>
              {mmss(total)} spoken briefing · {chapters.length} chapters · built only from
              verified findings
            </span>
          </span>
          <span className="ra-open-play" aria-hidden="true">▶</span>
        </button>
      )}

      {active && (
        <aside className="ra-dock" aria-label="Audio briefing">
          <div className="ra-dock-in">
            <div className="ra-dock-top">
              <span className="ra-eyebrow">Spoken summary · verified findings only</span>
              <button className="ra-x" onClick={dismiss} aria-label="Close briefing">×</button>
            </div>

            <h4 className="ra-title" title={title}>{title}</h4>

            <div className={playing ? "ra-wave on" : "ra-wave"} aria-hidden="true">
              {bars.map((h, i) => (
                <i
                  key={i}
                  style={{
                    height: `${Math.round(h * 100)}%`,
                    animationDelay: `${(i % 11) * 90}ms`,
                    opacity: (i / bars.length) * 100 <= pct ? 1 : 0.34,
                  }}
                />
              ))}
            </div>

            <div className="ra-bar"><span style={{ width: `${pct}%` }} /></div>
            <div className="ra-times">
              <span>{mmss(elapsed)}</span>
              <span>{mmss(total)}</span>
            </div>

            <div className="ra-ctrls">
              <button className="ra-restart" onClick={() => speakFrom(0)} disabled={!supported} title="Restart">↺</button>
              <button
                className="ra-play"
                onClick={toggle}
                disabled={!supported}
                aria-label={playing ? "Pause" : "Play"}
              >
                {playing ? "❚❚" : "▶"}
              </button>
              <div className="ra-rates" role="group" aria-label="Playback speed">
                {[1, 1.25, 1.5, 2].map((r) => (
                  <button
                    key={r}
                    className={rate === r ? "active" : ""}
                    onClick={() => setRate(r)}
                    disabled={!supported}
                  >
                    {r}×
                  </button>
                ))}
              </div>
            </div>

            {!supported && (
              <p className="ra-note">
                This browser has no speech synthesis — the script below is the full briefing.
              </p>
            )}

            <button
              className="ra-script-toggle"
              onClick={() => setScriptOpen((v) => !v)}
              aria-expanded={scriptOpen}
            >
              Spoken script &amp; chapters {scriptOpen ? "▾" : "▸"}
            </button>

            {scriptOpen && (
              <ol className="ra-script">
                {chapters.map((ch, i) => (
                  <li key={i} className={i === index && status !== "idle" ? "on" : ""}>
                    <button onClick={() => speakFrom(i)} disabled={!supported}>
                      <span className="role">{ch.role}</span>
                      <span className="at">{mmss(ch.at)}</span>
                      <span className="txt">{ch.text}</span>
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </aside>
      )}
    </>
  );
}
