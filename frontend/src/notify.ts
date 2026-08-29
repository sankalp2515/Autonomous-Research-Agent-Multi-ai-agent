import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Run } from "./types";

// Ask once, lazily — only when a run is actually running, never on page load
// (an unprompted permission request on first paint is a dark pattern).
export function ensureNotifyPermission() {
  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission().catch(() => {});
  }
}

function fireBrowserNotification(title: string, body: string, onClick: () => void) {
  if (!("Notification" in window) || Notification.permission !== "granted") return false;
  try {
    const n = new Notification(title, { body, tag: "veriscope-run", icon: "/favicon.svg" });
    n.onclick = () => { window.focus(); onClick(); n.close(); };
    return true;
  } catch {
    return false;
  }
}

const TERMINAL = new Set(["completed", "completed_with_gaps", "failed", "rejected"]);
// How many failed socket opens per run before we stop trying and rely on the
// 15s REST tick. Any value bounds the loop; this one tolerates a genuine blip.
const WS_MAX_FAILURES = 3;
const DONE_LABEL: Record<string, string> = {
  completed: "Your verified report is ready",
  completed_with_gaps: "Report ready — with honest gaps flagged",
  failed: "Your research run failed",
  rejected: "Run rejected — not a research question",
};

export type RunToast = { runId: string; title: string; body: string; status: string } | null;

/**
 * App-wide completion notifications. Independent of whichever view is open:
 * discovers active runs for the project, watches each over a WebSocket, and on
 * a terminal frame raises a browser notification (works when the tab is
 * backgrounded) plus an in-app toast (for when it's focused, since some OSes
 * suppress notifications for the focused tab). This is the "so the user does
 * not wait" half of the latency work — they can walk away and get pulled back.
 */
export function useRunNotifications(projectId: string | null, onOpenReport?: (reportId: string) => void) {
  const [toast, setToast] = useState<RunToast>(null);
  const watching = useRef<Map<string, () => void>>(new Map());
  const notified = useRef<Set<string>>(new Set());
  const runsById = useRef<Map<string, Run>>(new Map());
  const wsFailures = useRef<Map<string, number>>(new Map());
  const giveUpWs = useRef<Set<string>>(new Set());

  const dismiss = useCallback(() => setToast(null), []);

  useEffect(() => {
    // Reset when the project changes — stop every open socket.
    for (const stop of watching.current.values()) stop();
    watching.current.clear();
    wsFailures.current.clear();
    giveUpWs.current.clear();
    notified.current.clear();
    runsById.current.clear();
    setToast(null);
    if (!projectId) return;
    const pid = projectId; // narrow for the nested closures below

    let alive = true;
    let timer: ReturnType<typeof setTimeout>;

    function announce(run: Run, status: string) {
      if (notified.current.has(run.id)) return;
      notified.current.add(run.id);
      const title = DONE_LABEL[status] ?? "Research run finished";
      const q = run.query.length > 90 ? run.query.slice(0, 88) + "…" : run.query;
      const open = () => { if (run.report_id && onOpenReport) onOpenReport(run.report_id); };
      fireBrowserNotification(title, q, open);
      setToast({ runId: run.id, title, body: q, status });
    }

    async function scan() {
      try {
        const runs = await api.listRuns(pid);
        if (!alive) return;
        for (const r of runs) runsById.current.set(r.id, r);
        const active = runs.filter((r) => ["queued", "running"].includes(r.status));
        if (active.length) ensureNotifyPermission();
        for (const r of active) {
          if (watching.current.has(r.id) || giveUpWs.current.has(r.id)) continue;
          const stop = api.watchRunWS(
            r.id,
            () => {},
            (status) => {
              watching.current.delete(r.id);
              const fresh = runsById.current.get(r.id) ?? r;
              const st = status && TERMINAL.has(status) ? status : undefined;
              if (st) {
                announce(fresh, st);
                return;
              }
              // Closed with no terminal frame. This used to call scan()
              // immediately, which re-opened the socket, which closed again —
              // an unthrottled reconnect loop that pinned the API at ~390% CPU
              // servicing rejected handshakes and made unrelated requests fail
              // with "can't reach the API". A watcher that cannot connect must
              // degrade to polling, never spin: count the failures per run and
              // stop opening sockets for it after a few.
              const n = (wsFailures.current.get(r.id) ?? 0) + 1;
              wsFailures.current.set(r.id, n);
              if (n >= WS_MAX_FAILURES) {
                // The 15s REST tick below still reports completion.
                giveUpWs.current.add(r.id);
              }
            }
          );
          watching.current.set(r.id, stop);
        }
      } catch {
        /* transient — retry on the next tick */
      }
      if (alive) timer = setTimeout(scan, 15000);
    }
    scan();

    return () => {
      alive = false;
      clearTimeout(timer);
      for (const stop of watching.current.values()) stop();
      watching.current.clear();
    };
  }, [projectId, onOpenReport]);

  return { toast, dismiss };
}
