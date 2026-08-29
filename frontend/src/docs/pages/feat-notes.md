Notes are your own writing, kept inside the project alongside the corpus. They are
the one surface in Veriscope that is deliberately **not** verified — because it is
you writing, and the system should not pretend otherwise.

## What it does

A note has a title, a free-text body, optional tags, and optionally a
`source_ref` — a line recording what it was seeded from. Notes autosave on blur;
there is no save button.

## How to use it

**Create one.** From the Notes view, or seeded from something you were reading, so
the note remembers its origin:

```bash
curl -X POST http://localhost:8210/api/projects/<project_id>/notes \
  -H 'Content-Type: application/json' \
  -d '{"title": "Why the HotpotQA numbers disagree",
       "body": "Both report 89.2 but the metrics differ — check the task column.",
       "source_ref": "claim · dense retrieval improves multi-hop recall",
       "claim_id": "<claim-id>"}'
```

When a note carries a `source_ref`, it renders above the body as a quiet seed
line — so months later you know what prompted the thought.

**Edit.** Type. Title and body save when the field loses focus
(`PATCH /api/notes/{note_id}`).

**Export.** One click produces `research_notes.md`, one `##` section per note with
its seed line as a blockquote and the body beneath.

**Delete.** `DELETE /api/notes/{note_id}`.

## What it gives you

- **Thinking stays next to evidence.** The interpretation, the doubt and the
  "check this later" live in the same project as the papers that provoked them,
  rather than in a separate app you forget to open.
- **Provenance for your own ideas.** `source_ref` records what a thought came
  from — the closest thing to a citation for something you reasoned yourself.
- **A place for the things the system must not say.** Speculation, hypotheses,
  arguments with the literature. These are valuable and they are not verifiable.
  Giving them their own surface is what keeps them out of the report.

## Notes, Notebook, Memory — which one?

This trips people up, so plainly:

| Surface | Contents | Written by | Verified? | Affects future runs? |
| --- | --- | --- | --- | --- |
| **[Notebook](#/docs/features/notebook)** | Gate-verified claims | The system | Yes | No |
| **Notes** | Prose | You | No | No |
| **[Memory](#/docs/features/memory)** | Orientation facts | Both | No | **Yes** — informs planning |

The rule of thumb: *the machine said it* → Notebook. *I said it* → Notes.
*The agent should know it next time* → Memory.

## Limits worth knowing

- **Notes are never used as evidence.** No claim can cite a note. They are outside
  the grounding path entirely, and that is the point.
- **Notes are not searched by Ask.** Asking the corpus retrieves document chunks,
  not your notes.
- **Plain text, not Markdown-rendered** in the editor. The export writes Markdown;
  the editing surface keeps it simple.
- **No revision history.** Autosave on blur overwrites.

## Related

- [Notebook](#/docs/features/notebook)
- [Memory](#/docs/features/memory)
