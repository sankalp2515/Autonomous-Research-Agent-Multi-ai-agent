import { FormEvent, useEffect, useRef, useState } from "react";
import { Spinner } from "./ui";

export default function NewProjectModal({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  onCreate: (name: string, description: string) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
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
    if (!name.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      await onCreate(name.trim(), description.trim());
    } catch (err: any) {
      // Previously this failed silently — the spinner stopped and nothing
      // happened. Now the user sees why and can retry.
      setError(err?.message ?? "Couldn’t create the project. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-veil" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <span className="overline">New project</span>
        <h3 style={{ fontFamily: "var(--serif)", fontSize: 19, fontWeight: 600, margin: "6px 0 14px" }}>
          Name your research workspace
        </h3>
        <form onSubmit={submit}>
          <input
            ref={inputRef}
            className="input"
            placeholder="e.g. RAG hallucination survey"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={200}
            style={{ marginBottom: 10 }}
          />
          <textarea
            className="textarea"
            placeholder="Optional description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            style={{ minHeight: 64, marginBottom: 16 }}
          />
          {error && <p style={{ color: "var(--bad)", fontSize: 12.5, margin: "0 0 12px" }}>{error}</p>}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button className="btn" disabled={busy || !name.trim()}>
              {busy ? <Spinner /> : "Create project"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
