import { ReactNode, useEffect, useRef, useState } from "react";

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
  // A user stop is NEUTRAL, not failed. Stamping it red would tell the reader
  // Veriscope broke when in fact they pressed the button — the same category
  // error `gap_kind` exists to prevent, one surface up.
  if (["cancelled", "cancelling"].includes(status))
    return <Stamp kind="neutral">{status === "cancelling" ? "stopping…" : "stopped"}</Stamp>;
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

// Distinct from Empty: shown when a fetch actually FAILED. Never let a network
// error masquerade as "no data" — it tells the user the corpus is empty when it
// isn't. Offers a retry so recovery is one click, not a full reload.
export function ErrorState({
  title = "Couldn’t load this",
  message,
  onRetry,
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
}) {
  const offline = typeof navigator !== "undefined" && navigator.onLine === false;
  return (
    <div className="empty error-state">
      <div className="glyph">⚠</div>
      <h3>{title}</h3>
      <p>
        {offline
          ? "You appear to be offline. Check your connection and try again."
          : message || "The server didn’t respond. This is usually temporary."}
      </p>
      {onRetry && (
        <button className="btn btn-accent" style={{ marginTop: 4 }} onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

// Styled replacement for window.confirm — a native OS dialog inside a bespoke
// design system reads as broken. Esc / backdrop cancels; the primary action is
// focused. Render <ConfirmDialog ... /> conditionally from a piece of state.
export function ConfirmDialog({
  title,
  body,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  body?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    confirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="modal-veil" onClick={onCancel}>
      <div className="modal-card confirm-card" role="alertdialog" aria-label={title}
           onClick={(e) => e.stopPropagation()}>
        <h3 className="confirm-title">{title}</h3>
        {body && <p className="confirm-body">{body}</p>}
        <div className="confirm-actions">
          <button className="btn btn-ghost" onClick={onCancel}>{cancelLabel}</button>
          <button ref={confirmRef} className={`btn ${danger ? "btn-danger" : "btn-accent"}`}
                  onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

// Tiny helper: a boolean-returning imperative confirm is convenient, but keeping
// state is cleaner. This hook wires a one-shot confirm you can `await`.
export function useConfirm() {
  const [state, setState] = useState<
    | null
    | { title: string; body?: ReactNode; confirmLabel?: string; danger?: boolean; resolve: (ok: boolean) => void }
  >(null);

  const confirm = (opts: { title: string; body?: ReactNode; confirmLabel?: string; danger?: boolean }) =>
    new Promise<boolean>((resolve) => setState({ ...opts, resolve }));

  const element = state ? (
    <ConfirmDialog
      title={state.title}
      body={state.body}
      confirmLabel={state.confirmLabel}
      danger={state.danger}
      onConfirm={() => { state.resolve(true); setState(null); }}
      onCancel={() => { state.resolve(false); setState(null); }}
    />
  ) : null;

  return { confirm, element };
}
