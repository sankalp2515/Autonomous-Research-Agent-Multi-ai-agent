A report that cannot leave the app is only half useful. Veriscope exports in two ways,
and both preserve provenance rather than flattening it.

## Share a read-only link

```bash
curl -X POST http://localhost:8210/api/report/<report_id>/share
```

Returns a short slug. The recipient opens `#/s/<slug>` and reads the report without an
account — including the full evidence rail, so they can verify every claim themselves.
This is the point: a shared Veriscope report is checkable by the person receiving it, not
merely readable.

Revoke it at any time:

```bash
curl -X DELETE http://localhost:8210/api/report/<report_id>/share
```

:::warn A share link is public to anyone holding it
There is no per-recipient access control on shared reports. Treat the slug as the
credential and revoke it when the audience changes.
:::

## Export Markdown

The Markdown export mirrors the on-screen structure rather than reducing it:

- `#` title, `##` numbered sections, `###` sub-themes;
- comparison tables preserved as Markdown tables;
- inline footnote markers preserved;
- a `## Works Cited` appendix numbered in citation order, each entry carrying authors,
  year, resolver badge and the **verbatim grounding span** with its page range and NLI
  score.

The numbering matches the inline footnotes, so a claim in the exported text is still
traceable to a source span in a plain text file with no app around it.

## Fetch a report over the API

```bash
curl http://localhost:8210/api/report/<report_id>
```

Useful companions:

| Endpoint | Returns |
| --- | --- |
| `GET /api/report/{id}/metrics` | Grounding metrics for the report. |
| `GET /api/report/{id}/contradictions` | NLI-detected conflicts between claim pairs. |
| `GET /api/report/{id}/next-questions` | Follow-up questions derived from the gaps. |
| `GET /api/claims/{claim_id}/evidence` | The full evidence chain for one claim. |

## What is deliberately *not* exported

Nothing that failed the gate. Refused claims are counted in the methods funnel — you can
see *how many* were dropped — but their text does not travel, because an ungrounded
sentence outside the app has no way to announce that it was ungrounded.

## Related

- [API reference](#/docs/reference/api)
- [Compare papers](#/docs/features/compare)
