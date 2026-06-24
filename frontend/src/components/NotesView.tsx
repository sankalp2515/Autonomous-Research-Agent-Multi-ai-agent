import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { Note } from "../types";
import { Empty, Spinner } from "./ui";

function exportNotes(notes: Note[]) {
  const L = ["# Research notes", ""];
  notes.forEach((n) => {
    L.push(`## ${n.title || "Untitled"}`);
    if (n.source_ref) L.push(`> ${n.source_ref}`);
    L.push("", n.body || "", "");
  });
  const blob = new Blob([L.join("\n")], { type: "text/markdown" });
  const u = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = u;
  a.download = "research_notes.md";
  a.click();
  URL.revokeObjectURL(u);
}

function NoteCard({
  note,
  onSave,
  onDelete,
}: {
  note: Note;
  onSave: (n: Note, t: string, b: string) => void;
  onDelete: (id: string) => void;
}) {
  const [title, setTitle] = useState(note.title);
  const [body, setBody] = useState(note.body);
  return (
    <div className="note-card">
      <input className="note-title-input" value={title} placeholder="Untitled"
             onChange={(e) => setTitle(e.target.value)}
             onBlur={() => onSave(note, title, body)} />
      {note.source_ref && <p className="note-seed">{note.source_ref}</p>}
      <textarea className="note-body-input" value={body}
                placeholder="Write your thoughts…"
                onChange={(e) => setBody(e.target.value)}
                onBlur={() => onSave(note, title, body)} />
      <div className="note-foot">
        <span className="note-time">{new Date(note.updated_at).toLocaleString()}</span>
        <button className="note-del" onClick={() => onDelete(note.id)}>delete</button>
      </div>
    </div>
  );
}

export default function NotesView({ projectId }: { projectId: string }) {
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [draft, setDraft] = useState({ title: "", body: "" });

  const refresh = useCallback(
    () => api.listNotes(projectId).then(setNotes).catch(() => setNotes([])),
    [projectId]
  );
  useEffect(() => {
    refresh();
  }, [refresh]);

  async function create() {
    if (!draft.title.trim() && !draft.body.trim()) return;
    await api.createNote(projectId, { title: draft.title.trim(), body: draft.body.trim() });
    setDraft({ title: "", body: "" });
    refresh();
  }
  async function save(n: Note, title: string, body: string) {
    if (title === n.title && body === n.body) return;
    await api.updateNote(n.id, { title, body });
    refresh();
  }
  async function del(id: string) {
    await api.deleteNote(id);
    refresh();
  }

  if (!notes) return <p><Spinner /> loading notes…</p>;

  return (
    <div className="content-narrow">
      <div style={{ display: "flex", alignItems: "flex-start", marginBottom: 16 }}>
        <div>
          <span className="overline">Research notes</span>
          <p style={{ margin: "4px 0 0", color: "var(--text-2)", fontSize: 13.5, maxWidth: 560, lineHeight: 1.55 }}>
            Your own observations and synthesis — write freely. Seed a note from
            any finding with "✎ Note this" in the evidence panel, then add your take.
          </p>
        </div>
        <span style={{ flex: 1 }} />
        {notes.length > 0 && (
          <button className="btn btn-ghost" style={{ fontSize: 12.5 }} onClick={() => exportNotes(notes)}>
            ↓ Export
          </button>
        )}
      </div>

      <div className="note-card editing" style={{ marginBottom: 22 }}>
        <input className="note-title-input" placeholder="New note title…" value={draft.title}
               onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
        <textarea className="note-body-input"
                  placeholder="Write your thoughts — what's interesting, why it matters, what to follow up…"
                  value={draft.body}
                  onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
        <div className="note-foot">
          <span style={{ flex: 1 }} />
          <button className="btn" style={{ fontSize: 12, padding: "5px 14px" }}
                  onClick={create} disabled={!draft.title.trim() && !draft.body.trim()}>
            Add note
          </button>
        </div>
      </div>

      {notes.length === 0 ? (
        <Empty glyph="✎" title="No notes yet">
          Capture an idea above, or hit "✎ Note this" on any finding to start one
          from a quote and write your own interpretation.
        </Empty>
      ) : (
        notes.map((n) => <NoteCard key={n.id} note={n} onSave={save} onDelete={del} />)
      )}
    </div>
  );
}
