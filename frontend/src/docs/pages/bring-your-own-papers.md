Veriscope's automated sourcing is not the only way material enters a corpus. You can
upload PDFs directly and import an existing reference library.

## Upload PDFs

From the **Documents** view inside a project, or via the API:

```bash
curl -X POST http://localhost:8210/api/projects/<project_id>/documents \
  -F 'file=@paper.pdf'
```

Each upload is parsed with `pymupdf4llm`, chunked with section and page metadata, and
embedded into the project's Qdrant collection. There is **no page cap** — the whole
document is parsed, with a per-section fallback when the parser hits trouble on one part
rather than dropping the file.

| Setting | Default | Effect |
| --- | --- | --- |
| `INGEST_MAX_PDF_MB` | 50 | Rejected above this size. |
| `INGEST_PDF_CONCURRENCY` | 4 | Parallel parses. |
| `INGEST_DOWNLOAD_CONCURRENCY` | 10 | Parallel fetches during a run. |

## Import a BibTeX library

```bash
curl -X POST http://localhost:8210/api/projects/<project_id>/import/bibtex \
  -F 'file=@library.bib'
```

Returns `202` — the import runs in the background. Entries resolve against arXiv and
Semantic Scholar; open-access PDFs are fetched and ingested, and entries whose full text
is not retrievable are kept as **abstract-only** documents, clearly labelled as such.

:::warn Abstract-only sources cannot ground an absence
A document without full text can never produce a `not_reported` cell — only
`extraction_uncertain`. There is no way to have searched a paper properly if you never
had its body. See [Cell states](#/docs/explanation/cell-states).
:::

## How duplicates are handled

Deduplication runs on three keys, in order: `sha256` of the file, then identifier
(`doi` / `arxiv_id`), then fuzzy title-and-authors match.

Preprints and published versions are **linked as versions, not collapsed**. They are
genuinely different artefacts — the numbers frequently changed between them — and
collapsing them would silently attribute a v2 result to a v1 citation.

## Removing a source

```bash
curl -X DELETE http://localhost:8210/api/projects/<project_id>/documents/<document_id>
```

Removed sources leave an auditable **tombstone** so previously cited claims remain
traceable. A citation that resolved yesterday does not become a dangling reference because
someone tidied the corpus today.

## Corpus retention

Retention is tiered, so a large corpus does not require large infrastructure:

| Tier | What lives there | Lifetime |
| --- | --- | --- |
| Global index | External scholarly APIs | Never duplicated locally |
| Hot | Embedded vectors for the working set | Capped by `CORPUS_MAX_EMBEDDED_CHUNKS` (4000) |
| Cold | Text, verified claims and quotes in Postgres | Forever — kilobytes per paper |

Evicted vectors rebuild on demand via the reindex job. **Chunks backing verified claims
are never evicted** — otherwise a published claim could lose the ability to prove itself.

## Related

- [Data model](#/docs/reference/data-model)
- [Ask questions about your corpus](#/docs/tutorials/grounded-chat)
