import { FormEvent, useEffect, useRef, useState } from "react";
import { Spinner } from "./ui";

// Reusable single-input modal — the in-app replacement for window.prompt(), so
// every "name this thing" flow is visually consistent (team workspace, rename,
// etc.) instead of a jarring browser-native dialog. Shares .modal-veil/.modal-card
// with NewProjectModal.
export default function PromptModal({
  title, label, placeholder = "", confirmLabel = "Create", initial = "",
  onSubmit, onClose,
}: {
  title: string;
  label?: string;
  placeholder?: string;
  confirmLabel?: string;
  initial?: string;
  onSubmit: (value: string) => Promise<void> | void;
  onClose: () => void;
}) {
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!value.trim() || busy) return;
    setBusy(true); setError("");
    try {
      await onSubmit(value.trim());
      onClose();
    } catch (err: any) {
      setError(err?.message ?? "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-veil" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        {label && <span className="overline">{label}</span>}
        <h3 style={{ fontFamily: "var(--serif)", fontSize: 19, fontWeight: 600, margin: "6px 0 14px" }}>
          {title}
        </h3>
        <form onSubmit={submit}>
          <input
            ref={inputRef}
            className="input"
            placeholder={placeholder}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            maxLength={200}
            style={{ marginBottom: 16 }}
          />
          {error && <p style={{ color: "var(--bad)", fontSize: 12.5, margin: "0 0 12px" }}>{error}</p>}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button className="btn" disabled={busy || !value.trim()}>
              {busy ? <Spinner /> : confirmLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
