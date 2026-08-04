import { useEffect, useState } from "react";
import { api } from "../api";
import type { ResumeData } from "../types";

// Welcome-back surface. Shown when a project is opened so a researcher who left
// mid-flight sees exactly where they were — unfinished runs (resumable from
// checkpoint), what they last worked on, open gaps, and new watch alerts.
export default function ResumeBanner({
  projectId,
  onResumeRun,
  onGo,
}: {
  projectId: string;
  onResumeRun: (runId: string) => void;
  onGo: (view: "runs" | "report" | "monitor" | "compare") => void;
}) {
  const [data, setData] = useState<ResumeData | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [resuming, setResuming] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setDismissed(false);
    api.getResume(projectId).then(setData).catch(() => setData(null));
  }, [projectId]);

  if (!data || dismissed) return null;

  const nothing =
    data.unfinished_runs.length === 0 &&
    !data.last_activity &&
    data.new_alerts === 0 &&
    data.open_gaps.length === 0;
  if (nothing) return null;

  async function resume(runId: string) {
    setResuming(runId);
    try {
      await api.resumeRun(runId);
      onResumeRun(runId);
    } catch {
      /* ignore */
    } finally {
      setResuming(null);
    }
  }

  const when = data.last_activity_at
    ? new Date(data.last_activity_at).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      })
    : "";

  return (
    <div className="resume-banner">
      <button className="resume-x" onClick={() => setDismissed(true)} aria-label="Dismiss">
        ×
      </button>
      <div className="resume-head">
        <span className="resume-glyph">↩</span>
        <div>
          <b>Welcome back</b>
          {data.last_activity && (
            <p className="resume-last">
              {data.last_activity}
              {when && <span className="mono"> · {when}</span>}
            </p>
          )}
        </div>
      </div>

      {data.unfinished_runs.length > 0 && (
        <div className="resume-runs">
          {data.unfinished_runs.map((r) => (
            <div key={r.run_id} className="resume-run">
              <div className="resume-run-info">
                <span className={`resume-dot ${r.status}`} />
                <span className="resume-run-q">{r.query}</span>
                <span className="mono resume-run-node">
                  {r.status === "failed" ? "stopped at" : "at"} {r.current_node}
                </span>
              </div>
              {r.resumable && (
                <button className="btn" style={{ fontSize: 12, padding: "5px 13px" }}
                        onClick={() => resume(r.run_id)} disabled={resuming === r.run_id}>
                  {resuming === r.run_id ? "Resuming…" : "▸ Resume"}
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="resume-chips">
        {data.new_alerts > 0 && (
          <button className="resume-chip alert" onClick={() => onGo("monitor")}>
            🔔 {data.new_alerts} new paper{data.new_alerts !== 1 ? "s" : ""} matched your watches
          </button>
        )}
        {data.open_gaps.length > 0 && (
          <button className="resume-chip" onClick={() => onGo("report")}>
            ◐ {data.open_gaps.length} open gap{data.open_gaps.length !== 1 ? "s" : ""} in your last report
          </button>
        )}
        {data.doc_count >= 2 && (
          <button className="resume-chip" onClick={() => onGo("compare")}>
            ⊞ Compare {data.doc_count} papers in your library
          </button>
        )}
      </div>
    </div>
  );
}
