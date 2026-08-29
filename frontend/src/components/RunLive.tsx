import { useEffect, useMemo, useRef, useState } from "react";
import type { ProgressEvent, ProgressKind, Run, RunStatus } from "../types";
import { Icon } from "./icons";

/* ══════════════════════════════════════════════════════════════════════════
   The live run surface: clock, pipeline stepper, and the process feed.
   ─────────────────────────────────────────────────────────────────────────
   Two things this replaces, both of which were dishonest in their own way:

   1. The timer read `budgets_spent.seconds`, which the pipeline only rewrites
      at a NODE CHECKPOINT. Inside `research` (minutes of downloading and
      parsing) it froze, so a healthy run looked hung. The clock now anchors on
      a server-computed `elapsed_seconds` and ticks forward from a MONOTONIC
      local delta, so it neither stalls nor drifts with the wall clock.

   2. The feed showed the last six messages with no time, no category and no
      history — the run's most interesting moments (a claim refused at the
      gate, a paper with no full text) scrolled past unmarked. Events are now
      typed AT THE PUBLISH SITE (`kind`), so the feed groups and colours them
      without pattern-matching our own prose.
   ══════════════════════════════════════════════════════════════════════════ */

// The real graph topology (app/agents/graph.py). `evidence_schema` used to be
// missing here, so while that node ran, indexOf returned -1 and the stepper
// snapped back to step one mid-run.
const NODES = [
  "clarify", "plan", "evidence_schema", "research", "extract_evidence",
  "report_architect", "draft_sections", "assemble", "build_graph",
];

// Researcher-facing labels — internal node names don't mean anything to a user.
const NODE_LABELS: Record<string, string> = {
  clarify: "clarify",
  plan: "plan",
  evidence_schema: "evidence plan",
  research: "search & read",
  extract_evidence: "extract",
  report_architect: "structure",
  draft_sections: "draft + verify",
  assemble: "finalize",
  build_graph: "link sources",
};

const TERMINAL = ["completed", "completed_with_gaps", "failed", "rejected", "budget_exhausted"];

type FeedGroup = "all" | "evidence" | "sources" | "stages";

const GROUP_OF: Record<ProgressKind, FeedGroup> = {
  verify: "evidence", refuse: "evidence", extract: "evidence", recover: "evidence",
  search: "sources", ingest: "sources", corpus: "sources",
  stage: "stages", done: "stages", error: "stages",
};

const KIND_LABEL: Record<ProgressKind, string> = {
  stage: "stage", search: "search", ingest: "source", corpus: "corpus",
  extract: "extract", recover: "recover", verify: "verified", refuse: "refused",
  error: "error", done: "done",
};

/* ── Clock ──────────────────────────────────────────────────────────────── */

export function formatDuration(total: number): string {
  const s = Math.max(0, Math.round(total));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

/**
 * Seconds elapsed for a run, ticking every second while it is live.
 *
 * The server sends the authoritative `elapsed_seconds` on every poll; between
 * polls we advance it by a `performance.now()` delta (monotonic — immune to the
 * machine's clock being adjusted, and to any client/server timezone mismatch,
 * which is exactly how a naive `new Date(created_at)` gets an hour wrong).
 */
export function useRunClock(anchor: { elapsed_seconds?: number; running?: boolean } | undefined): number | null {
  const base = useRef<{ mark: number; secs: number } | null>(null);
  const [, setTick] = useState(0);
  const server = anchor?.elapsed_seconds;
  const running = anchor?.running ?? false;

  useEffect(() => {
    if (server == null) return;
    base.current = { mark: performance.now(), secs: server };
    setTick((t) => t + 1);
  }, [server]);

  useEffect(() => {
    if (!running || server == null) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [running, server]);

  if (server == null) return null;
  if (!running || !base.current) return server;
  return base.current.secs + Math.floor((performance.now() - base.current.mark) / 1000);
}

/* ── Pipeline stepper ───────────────────────────────────────────────────── */

function Stepper({ status, replans }: { status: RunStatus; replans: number }) {
  const liveNode = status.live?.node ?? status.current_node;
  const finished = TERMINAL.includes(status.status) && status.status !== "failed";
  const idx = finished ? NODES.length : Math.max(NODES.indexOf(liveNode), 0);
  const pct = (Math.min(idx, NODES.length - 1) / (NODES.length - 1)) * 100;

  return (
    <div className="rl-steps">
      <div className="rl-steps-rail">
        <div
          className={`rl-steps-fill ${status.status === "failed" ? "failed" : ""}`}
          style={{ width: `${finished ? 100 : pct}%` }}
        />
      </div>
      {NODES.map((node, i) => {
        const done = i < idx;
        const active = i === idx && !finished;
        const failed = status.status === "failed" && i === idx;
        const cls = failed ? "failed" : done ? "done" : active ? "active" : "";
        return (
          <div key={node} className={`rl-step ${cls}`}>
            <span className="rl-step-dot">{done ? "✓" : failed ? "!" : i + 1}</span>
            <span className="rl-step-label">{NODE_LABELS[node] ?? node}</span>
          </div>
        );
      })}
      {replans > 0 && (
        <span className="rl-replan" title="A sub-question found no verifiable support, so the pipeline went back to planning to search again.">
          ↺ replan ×{replans}
        </span>
      )}
    </div>
  );
}

/* ── Feed ───────────────────────────────────────────────────────────────── */

/** Consecutive duplicates are dropped: every node start republishes the same
 *  generic stage line (draft_sections does it once per section), which used to
 *  fill the feed with the identical sentence six times in a row. */
function cleanEvents(events: ProgressEvent[]): ProgressEvent[] {
  const out: ProgressEvent[] = [];
  for (const ev of events) {
    const msg = (ev.message || ev.node || "").trim();
    if (!msg) continue;
    const prev = out[out.length - 1];
    if (prev && (prev.message || prev.node || "").trim() === msg) {
      out[out.length - 1] = { ...prev, ...ev }; // keep the freshest counters
      continue;
    }
    out.push(ev);
  }
  return out;
}

function kindOf(ev: ProgressEvent): ProgressKind {
  if (ev.kind) return ev.kind;
  // Runs that were already in flight when this shipped have untyped events in
  // Redis; fall back to the node rather than inventing a category.
  if (ev.status === "failed") return "error";
  if (ev.status === "rejected") return "refuse";
  return "stage";
}

export function RunLive({ run, status }: { run: Run; status: RunStatus | undefined }) {
  const [group, setGroup] = useState<FeedGroup>("all");
  const [pinned, setPinned] = useState(true); // auto-scroll to the newest line
  const feedRef = useRef<HTMLOListElement | null>(null);

  const live = status?.live ?? null;
  const running = ["queued", "running"].includes(run.status);
  const elapsed = useRunClock({
    elapsed_seconds: status?.elapsed_seconds ?? run.elapsed_seconds,
    running,
  });

  const events = useMemo(() => cleanEvents(status?.events ?? []), [status?.events]);

  // Counters are read off the events rather than recomputed here: each is a
  // running total the pipeline already published, so a client that connects
  // late still shows the true tally instead of counting only what it saw.
  const totals = useMemo(() => {
    const max = (pick: (e: ProgressEvent) => number | undefined) =>
      events.reduce((acc, e) => Math.max(acc, pick(e) ?? 0), 0);
    return {
      papers: Math.max(max((e) => e.papers_ingested), max((e) => e.papers_done)),
      papersTotal: max((e) => e.papers_total),
      findings: max((e) => e.findings),
      verified: max((e) => e.claims_verified),
      refused: max((e) => e.claims_refused),
      sectionsDone: live?.sections_done ?? max((e) => e.sections_done),
      sectionsTotal: live?.sections_total ?? max((e) => e.sections_total),
    };
  }, [events, live]);

  const counts = useMemo(() => {
    const c: Record<FeedGroup, number> = { all: events.length, evidence: 0, sources: 0, stages: 0 };
    for (const ev of events) c[GROUP_OF[kindOf(ev)]] += 1;
    return c;
  }, [events]);

  const replans = useMemo(
    () => Math.max(0, events.filter((e) => kindOf(e) === "stage" && e.node === "plan").length - 1),
    [events],
  );

  const shown = useMemo(
    () => (group === "all" ? events : events.filter((ev) => GROUP_OF[kindOf(ev)] === group)),
    [events, group],
  );

  // Auto-scroll, but only while the reader is at the bottom. Yanking the view
  // back down while someone is reading an earlier line is the classic log-feed
  // sin; scrolling up unpins, scrolling back to the end re-pins.
  //
  // A ResizeObserver, not just an effect on the list: the feed also grows when
  // a late-loading web font reflows it, and a bare effect fires against the
  // pre-reflow scrollHeight and leaves the newest line off-screen.
  useEffect(() => {
    const el = feedRef.current;
    if (!el) return;
    const stick = () => { if (pinned) el.scrollTop = el.scrollHeight; };
    stick();
    const ro = new ResizeObserver(stick);
    ro.observe(el);
    for (const child of Array.from(el.children)) ro.observe(child);
    return () => ro.disconnect();
  }, [shown, pinned]);

  function onScroll() {
    const el = feedRef.current;
    if (!el) return;
    setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 24);
  }

  const started = status?.started_epoch ?? run.started_epoch ?? 0;
  const lastIdx = shown.length - 1;

  return (
    <section className="rl">
      <header className="rl-head">
        <span className={`rl-state ${running ? "live" : run.status}`}>
          {running && <i className="rl-beacon" />}
          {running ? (live?.node ? NODE_LABELS[live.node] ?? live.node : "starting") : run.status.replace(/_/g, " ")}
        </span>
        <span className="rl-clock mono" title="Wall-clock time since this run was submitted">
          <Icon.clock size={13} /> {elapsed == null ? "—" : formatDuration(elapsed)}
        </span>
        <div className="rl-metrics">
          {totals.papers > 0 && (
            <span className="rl-metric" title="Papers downloaded, parsed and indexed into this run's corpus">
              <b>{totals.papers}{totals.papersTotal ? `/${totals.papersTotal}` : ""}</b> papers
            </span>
          )}
          {totals.findings > 0 && (
            <span className="rl-metric" title="Quote-verified findings extracted into the evidence matrix">
              <b>{totals.findings}</b> findings
            </span>
          )}
          {totals.verified > 0 && (
            <span className="rl-metric ok" title="Claims that passed the exact-quote + NLI gate">
              <b>{totals.verified}</b> verified
            </span>
          )}
          {totals.refused > 0 && (
            <span className="rl-metric bad" title="Drafted claims refused as unsupported — these never ship">
              <b>{totals.refused}</b> refused
            </span>
          )}
          {!!totals.sectionsTotal && (
            <span className="rl-metric" title="Report sections drafted and verified">
              <b>{totals.sectionsDone ?? 0}/{totals.sectionsTotal}</b> sections
            </span>
          )}
        </div>
      </header>

      {status && <Stepper status={status} replans={replans} />}

      <div className="rl-filters">
        {([
          ["all", "All"],
          ["evidence", "Evidence & gate"],
          ["sources", "Sources"],
          ["stages", "Stages"],
        ] as [FeedGroup, string][]).map(([g, label]) => (
          <button
            key={g}
            type="button"
            className={`rl-filter ${group === g ? "on" : ""}`}
            onClick={() => setGroup(g)}
            disabled={g !== "all" && counts[g] === 0}
          >
            {label} <span className="mono">{counts[g]}</span>
          </button>
        ))}
        {!pinned && (
          <button type="button" className="rl-follow" onClick={() => setPinned(true)}>
            ↓ follow live
          </button>
        )}
      </div>

      <ol className="rl-feed" ref={feedRef} onScroll={onScroll}>
        {shown.length === 0 && <li className="rl-empty">Waiting for the first signal from the pipeline…</li>}
        {shown.map((ev, i) => {
          const kind = kindOf(ev);
          const current = running && i === lastIdx;
          const at = ev.elapsed ?? (started && ev.at ? Math.max(0, Math.round(ev.at - started)) : null);
          return (
            <li key={`${ev.at ?? i}-${i}`} className={`rl-row k-${kind} ${current ? "current" : ""}`}>
              <span className="rl-at mono">{at == null ? "" : formatDuration(at)}</span>
              <span className="rl-kind mono">{KIND_LABEL[kind]}</span>
              {/* The published message already names the refusals; adding a
                  badge here printed the same count twice. */}
              <span className="rl-msg">{ev.message || ev.node}</span>
            </li>
          );
        })}
      </ol>

      {live?.coverage_notes?.length ? (
        <p className="rl-coverage">
          <Icon.alertTriangle size={13} /> {live.coverage_notes[live.coverage_notes.length - 1]}
        </p>
      ) : null}
    </section>
  );
}

export { NODE_LABELS };
