"""Reference-manager import: turn BibTeX entries into corpus documents.

For each entry we fetch the full PDF when an arXiv id is known (library-first,
so nothing is downloaded twice), otherwise we ingest a clearly-labeled
abstract-only stub. This is the cold-start fix: a new project's corpus is
populated from the user's existing reading list in one step.
"""

from app.core.logging import get_logger
from app.db.session import session_scope
from app.stores import blob_store, redis_store

logger = get_logger("import")


async def _import_one(project_id: str, e: dict) -> bool:
    from app.agents import sources
    from app.ingestion.pipeline import ingest_pdf_document, ingest_text_document

    arxiv_id = e.get("arxiv_id")
    title = e.get("title") or ""
    if arxiv_id:
        key = blob_store.library_key(arxiv_id=arxiv_id)
        pdf = blob_store.load_pdf(key) if key and blob_store.has_pdf(key) else None
        if pdf is None:
            pdf = await sources.download_pdf(f"https://arxiv.org/pdf/{arxiv_id}")
            if pdf and key:
                blob_store.save_pdf(key, pdf)
        if pdf:
            async with session_scope() as session:
                await ingest_pdf_document(
                    session, project_id=project_id, pdf_bytes=pdf, source_type="paper",
                    title=title, authors=e.get("authors") or [], year=e.get("year"),
                    url=e.get("url") or f"https://arxiv.org/abs/{arxiv_id}",
                    arxiv_id=arxiv_id, doi=e.get("doi"),
                )
            return True

    # Metadata stub (abstract-only, labeled honestly).
    body = f"# {title}\n\n{e.get('abstract') or ''}".strip()
    if len(body) < 20:
        return False
    url = e.get("url") or (f"https://doi.org/{e['doi']}" if e.get("doi") else "")
    async with session_scope() as session:
        await ingest_text_document(
            session, project_id=project_id, text=body, source_type="paper",
            title=title, url=url, abstract_only=True, meta={"doi": e.get("doi")},
        )
    return True


async def import_bibtex_entries(project_id: str, entries: list[dict]) -> None:
    ok = 0
    for i, e in enumerate(entries):
        try:
            if await _import_one(project_id, e):
                ok += 1
        except Exception:
            logger.exception("import entry failed", extra={"title": (e.get("title") or "")[:60]})
        await redis_store.publish_progress(
            f"import:{project_id}",
            {"node": "import", "status": "running", "done": i + 1,
             "total": len(entries), "imported": ok},
        )
    logger.info("bibtex import complete",
                extra={"project_id": project_id, "imported": ok, "entries": len(entries)})
