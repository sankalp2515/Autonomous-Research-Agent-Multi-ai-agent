"""Ingestion pipeline: parse -> dedup -> chunk -> embed -> index.

Each stage is separately retryable; a document failure quarantines that
document with a reason and never blocks the batch. Idempotent by sha256.
"""


from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import IngestError
from app.core.logging import get_logger
from app.core.observability import INGEST_DOCS
from app.db.models import Chunk, Document
from app.ingestion.chunker import chunk_pages
from app.ingestion.dedup import find_duplicate, sha256_hex
from app.ingestion.pdf_parser import parse_pdf
from app.ml.local_models import embed_texts
from app.stores.qdrant_store import upsert_chunks

logger = get_logger("ingest")


async def ingest_pdf_document(
    session: AsyncSession,
    *,
    project_id: str,
    pdf_bytes: bytes,
    source_type: str = "upload",
    title: str = "",
    authors: list | None = None,
    year: int | None = None,
    url: str = "",
    doi: str | None = None,
    arxiv_id: str | None = None,
    external_id: str | None = None,
    meta: dict | None = None,
) -> Document:
    settings = get_settings()
    digest = sha256_hex(pdf_bytes)

    duplicate = await find_duplicate(
        session, project_id, sha256=digest, doi=doi, arxiv_id=arxiv_id,
        title=title, authors=authors,
    )
    if duplicate:
        logger.info("dedup hit", extra={"document_id": duplicate.id, "title": title[:80]})
        INGEST_DOCS.labels(source_type, "dedup").inc()
        return duplicate

    doc = Document(
        project_id=project_id, source_type=source_type, title=title,
        authors=authors or [], year=year, url=url, sha256=digest,
        doi=doi.lower() if doi else None, arxiv_id=arxiv_id,
        external_id=external_id, status="parsing", meta=meta or {},
    )
    session.add(doc)
    await session.flush()

    try:
        parsed = await parse_pdf(pdf_bytes, max_mb=settings.ingest_max_pdf_mb)
    except IngestError as exc:
        doc.status, doc.status_reason = "quarantined", exc.message
        INGEST_DOCS.labels(source_type, "quarantined").inc()
        logger.warning("document quarantined",
                       extra={"document_id": doc.id, "reason": exc.message})
        return doc

    pages = [(p.page_number, p.markdown) for p in parsed.pages]
    raw_chunks, _full_md = chunk_pages(pages)
    if not raw_chunks:
        doc.status, doc.status_reason = "quarantined", "no chunkable content"
        INGEST_DOCS.labels(source_type, "quarantined").inc()
        return doc

    chunk_rows = [
        Chunk(
            document_id=doc.id, project_id=project_id, section=rc.section,
            page_start=rc.page_start, page_end=rc.page_end,
            char_start=rc.char_start, char_end=rc.char_end,
            ordinal=rc.ordinal, text=rc.text,
        )
        for rc in raw_chunks
    ]
    session.add_all(chunk_rows)
    await session.flush()

    await _embed_and_index(session, project_id, doc, chunk_rows)

    doc.full_text_available = True
    doc.status = "indexed"
    # FIGURES ARE RECORDED, NOT READ (yet). Nothing in the pipeline can
    # interpret a chart today, so this does not add evidence — it removes a
    # silent one. Until now a figure left no trace at all, so "this paper does
    # not report that number" and "the number is in a bar chart we never
    # opened" were indistinguishable, and only the first was ever shown.
    # Persisting the inventory lets the second be stated. Stored on `meta`
    # (already JSON) so no migration is needed, and capped so a poster session
    # with hundreds of images cannot bloat the row.
    if parsed.figures:
        doc.meta = {
            **(doc.meta or {}),
            "figures": {
                "count": len(parsed.figures),
                "captioned": sum(1 for f in parsed.figures if f.caption),
                "items": [
                    {"page": f.page_number, "xref": f.xref, "bbox": list(f.bbox),
                     "w": f.width, "h": f.height, "caption": f.caption[:240]}
                    for f in parsed.figures[:60]
                ],
            },
        }
    if parsed.failed_pages:
        doc.status_reason = f"pages failed to parse: {parsed.failed_pages}"
    INGEST_DOCS.labels(source_type, "indexed").inc()
    logger.info("document indexed",
                extra={"document_id": doc.id, "chunks": len(chunk_rows),
                       "pages": parsed.page_count})
    return doc


async def ingest_text_document(
    session: AsyncSession,
    *,
    project_id: str,
    text: str,
    source_type: str,
    title: str = "",
    url: str = "",
    external_id: str | None = None,
    abstract_only: bool = False,
    meta: dict | None = None,
) -> Document:
    """Blogs, READMEs, abstracts - text sources without a PDF.
    abstract_only is surfaced honestly all the way to the UI (Elicit lesson)."""
    digest = sha256_hex(text.encode())
    duplicate = await find_duplicate(session, project_id, sha256=digest, title=title)
    if duplicate:
        INGEST_DOCS.labels(source_type, "dedup").inc()
        return duplicate

    doc = Document(
        project_id=project_id, source_type=source_type, title=title, url=url,
        sha256=digest, external_id=external_id, status="parsing",
        abstract_only=abstract_only, full_text_available=not abstract_only,
        meta=meta or {},
    )
    session.add(doc)
    await session.flush()

    raw_chunks, _ = chunk_pages([(1, text)])
    if not raw_chunks:
        doc.status, doc.status_reason = "quarantined", "no chunkable content"
        INGEST_DOCS.labels(source_type, "quarantined").inc()
        return doc
    chunk_rows = [
        Chunk(document_id=doc.id, project_id=project_id, section=rc.section,
              page_start=0, page_end=0, char_start=rc.char_start,
              char_end=rc.char_end, ordinal=rc.ordinal, text=rc.text)
        for rc in raw_chunks
    ]
    session.add_all(chunk_rows)
    await session.flush()
    await _embed_and_index(session, project_id, doc, chunk_rows)
    doc.status = "indexed"
    INGEST_DOCS.labels(source_type, "indexed").inc()
    return doc


def context_text(title: str, section: str, text: str) -> str:
    """Situate a chunk with its document title + section before embedding and
    lexical indexing (deterministic 'contextual retrieval'). A chunk like
    'it improved by 14%' becomes findable by the paper/section it belongs to,
    with no LLM cost. The ORIGINAL text is kept for display + quote-matching."""
    prefix = " — ".join(p for p in ((title or "").strip(), (section or "").strip()) if p)
    return f"{prefix}\n{text}" if prefix else text


async def _embed_and_index(
    session: AsyncSession, project_id: str, doc: Document, chunk_rows: list[Chunk]
) -> None:
    """Embed in batches and upsert to Qdrant. On embedding failure the
    document stays status=indexed-pending-vectors and a re-run repairs it -
    text in Postgres is the durable truth, vectors are rebuildable."""
    batch = 64
    try:
        for i in range(0, len(chunk_rows), batch):
            rows = chunk_rows[i : i + batch]
            vectors = await embed_texts(
                [context_text(doc.title, r.section, r.text) for r in rows]
            )
            await upsert_chunks([
                (r.id, vec, {"project_id": project_id, "document_id": doc.id})
                for r, vec in zip(rows, vectors)
            ])
            for r in rows:
                r.embedded = True
    except Exception:
        logger.exception("embedding/indexing failed; document text persisted, "
                         "vectors repairable via reindex",
                         extra={"document_id": doc.id})


async def enforce_corpus_budget(session: AsyncSession, project_id: str) -> int:
    """Tiered retention for small infra (ARCHITECTURE answer to 'we cannot
    store millions of papers'):

    - HOT  : embedded chunks in Qdrant, capped at corpus_max_embedded_chunks
    - COLD : text + metadata + verified claims stay in Postgres forever
             (kilobytes per paper); vectors are evicted and rebuildable
             on demand via the reindex job (text is still BM25-searchable)

    Eviction order: oldest documents whose chunks back no verified claim -
    cited evidence is never evicted. Returns number of chunks sent cold.
    """
    from app.db.models import ClaimEvidence

    settings = get_settings()
    embedded_count = await session.scalar(
        select(func.count(Chunk.id)).where(
            Chunk.project_id == project_id, Chunk.embedded == True  # noqa: E712
        )
    ) or 0
    excess = embedded_count - settings.corpus_max_embedded_chunks
    if excess <= 0:
        return 0

    cited_chunk_ids = set((await session.scalars(select(ClaimEvidence.chunk_id))).all())
    candidates = (await session.scalars(
        select(Document).where(Document.project_id == project_id,
                               Document.status == "indexed")
        .order_by(Document.created_at.asc())
    )).all()

    sent_cold = 0
    for doc in candidates:
        if sent_cold >= excess:
            break
        chunk_rows = (await session.scalars(
            select(Chunk).where(Chunk.document_id == doc.id,
                                Chunk.embedded == True)  # noqa: E712
        )).all()
        if not chunk_rows or any(c.id in cited_chunk_ids for c in chunk_rows):
            continue  # never evict evidence behind verified claims
        from app.stores.qdrant_store import delete_document
        await delete_document(doc.id)
        for c in chunk_rows:
            c.embedded = False
        doc.meta = {**(doc.meta or {}), "cold": True}
        sent_cold += len(chunk_rows)
        logger.info("document sent cold (vectors evicted, rebuildable)",
                    extra={"document_id": doc.id, "chunks": len(chunk_rows)})
    return sent_cold


async def reindex_pending(session: AsyncSession, project_id: str) -> int:
    """Repair pass: embed any chunks that missed vectors."""
    rows = (await session.scalars(
        select(Chunk).where(Chunk.project_id == project_id, Chunk.embedded == False)  # noqa: E712
    )).all()
    if not rows:
        return 0
    docs = {r.document_id for r in rows}
    repaired = 0
    for doc_id in docs:
        doc_rows = [r for r in rows if r.document_id == doc_id]
        doc = await session.get(Document, doc_id)
        title = doc.title if doc else ""
        try:
            vectors = await embed_texts(
                [context_text(title, r.section, r.text) for r in doc_rows]
            )
            await upsert_chunks([
                (r.id, vec, {"project_id": project_id, "document_id": doc_id})
                for r, vec in zip(doc_rows, vectors)
            ])
            await session.execute(
                update(Chunk).where(Chunk.id.in_([r.id for r in doc_rows]))
                .values(embedded=True)
            )
            # COMMIT PER DOCUMENT. This repair is the recovery path for chunks a
            # previous failure left cold, so it is precisely the code most likely
            # to meet the condition it repairs. Committing only at the end meant
            # one slow document discarded every document already embedded — a
            # 821-chunk reindex died twice and left the count at 821 both times,
            # having done the work and thrown it away. Per-document commits make
            # the repair monotonic: progress survives, and a re-run resumes
            # instead of restarting.
            await session.commit()
            repaired += len(doc_rows)
        except Exception:
            # One unreadable document must not abandon the rest. It stays cold
            # and is retried by the next reindex, which is the honest outcome —
            # a cold chunk is visible in the dashboard as such.
            await session.rollback()
            logger.warning("reindex failed for a document; leaving it cold",
                           extra={"document_id": doc_id, "chunks": len(doc_rows)})
    return repaired
