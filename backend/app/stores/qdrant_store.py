"""Qdrant: vectors only, keyed by chunk id. Rebuildable from Postgres."""

import uuid

from qdrant_client import AsyncQdrantClient, models as qm

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("qdrant")

_client: AsyncQdrantClient | None = None


def get_qdrant() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=get_settings().qdrant_url, timeout=30)
    return _client


def _point_id(chunk_id: str) -> str:
    # Qdrant requires UUID/int ids; derive a stable UUID from the chunk id.
    return str(uuid.uuid5(uuid.NAMESPACE_OID, chunk_id))


async def ensure_collection() -> None:
    settings = get_settings()
    client = get_qdrant()
    existing = {c.name for c in (await client.get_collections()).collections}
    if settings.qdrant_collection not in existing:
        await client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=qm.VectorParams(
                size=settings.embedding_dim, distance=qm.Distance.COSINE
            ),
        )
        logger.info("created qdrant collection",
                    extra={"collection": settings.qdrant_collection})


async def upsert_chunks(
    items: list[tuple[str, list[float], dict]],
) -> None:
    """items: (chunk_id, vector, payload). Payload carries project_id and
    document_id for filtered search; text stays in Postgres."""
    if not items:
        return
    settings = get_settings()
    await get_qdrant().upsert(
        collection_name=settings.qdrant_collection,
        points=[
            qm.PointStruct(
                id=_point_id(cid),
                vector=vec,
                payload={**payload, "chunk_id": cid},
            )
            for cid, vec, payload in items
        ],
    )


async def search(
    vector: list[float], project_id: str, limit: int = 20,
    document_ids: list[str] | None = None,
) -> list[tuple[str, float]]:
    """Returns (chunk_id, score), restricted to one project's corpus -
    the closed-corpus guarantee is enforced here at the store level.

    `document_ids` narrows the ANN search to specific documents IN THE STORE.
    Without it, a per-document caller had to search the whole project and then
    discard everything that wasn't its document — so for a 60-chunk paper inside
    a 44k-chunk corpus, dense retrieval contributed almost nothing and per-paper
    reading silently degraded to lexical-only. Pushing the filter down to Qdrant
    means the ANN budget is spent INSIDE the document."""
    settings = get_settings()
    must = [qm.FieldCondition(key="project_id", match=qm.MatchValue(value=project_id))]
    if document_ids:
        must.append(qm.FieldCondition(
            key="document_id", match=qm.MatchAny(any=list(document_ids))))
    hits = await get_qdrant().search(
        collection_name=settings.qdrant_collection,
        query_vector=vector,
        limit=limit,
        query_filter=qm.Filter(must=must),
    )
    return [(h.payload["chunk_id"], h.score) for h in hits if h.payload]


async def delete_document(document_id: str) -> None:
    settings = get_settings()
    await get_qdrant().delete(
        collection_name=settings.qdrant_collection,
        points_selector=qm.FilterSelector(
            filter=qm.Filter(
                must=[qm.FieldCondition(key="document_id", match=qm.MatchValue(value=document_id))]
            )
        ),
    )
