import { ReactNode } from "react";

export function Stamp({ kind, children }: { kind: "verified" | "gap" | "failed" | "neutral"; children: ReactNode }) {
  return (
    <span className={`stamp stamp-${kind}`}>
      <span className="stamp-dot" />
      {children}
    </span>
  );
}

export function statusStamp(status: string) {
  if (["indexed", "verified", "completed"].includes(status))
    return <Stamp kind="verified">{status}</Stamp>;
  if (["completed_with_gaps", "gap", "parsing", "pending", "queued", "running"].includes(status))
    return <Stamp kind="gap">{status.replaceAll("_", " ")}</Stamp>;
  if (["failed", "quarantined", "tombstoned", "budget_exhausted", "rejected"].includes(status))
    return <Stamp kind="failed">{status.replaceAll("_", " ")}</Stamp>;
  return <Stamp kind="neutral">{status}</Stamp>;
}

export function Spinner() {
  return <span className="spinner" aria-label="loading" />;
}

export function Empty({ glyph, title, children }: { glyph: string; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="glyph">{glyph}</div>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
    </div>
  );
}
