"""HTTP API. Kept surface from v1 (/api/pipeline /api/status /api/report
/api/chat /api/graph) plus workspace endpoints (projects, documents,
refind, claim evidence)."""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.exceptions import NotFoundError, ValidationFailed
from app.db.models import (
    Chunk, Citation, Claim, ClaimEvidence, Document, GraphEdge, MonitorAlert,
    Note, Project, Report, Run, SavedClaim, Watch,
)
from app.db.session import get_session
from app.ingestion.pipeline import ingest_pdf_document
from app.services.grounded import claim_evidence_detail, grounded_chat, refind
from app.stores import redis_store

router = APIRouter(prefix="/api")


# ── Projects ─────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


@router.get("/projects")
async def list_projects(
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user)
):
    rows = (await session.scalars(
        select(Project).where(Project.owner_id == user).order_by(Project.created_at.desc())
    )).all()
    out = []
    for p in rows:
        doc_count = await session.scalar(
            select(func.count(Document.id)).where(Document.project_id == p.id)
        )
        run_count = await session.scalar(
            select(func.count(Run.id)).where(Run.project_id == p.id)
        )
        out.append({"id": p.id, "name": p.name, "description": p.description,
                    "documents": doc_count, "runs": run_count,
                    "created_at": p.created_at.isoformat()})
    return out


@router.post("/projects", status_code=201)
async def create_project(
    body: ProjectCreate,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    project = Project(owner_id=user, name=body.name, description=body.description)
    session.add(project)
    await session.flush()
    return {"id": project.id, "name": project.name}


async def _get_project(session: AsyncSession, project_id: str, user: str) -> Project:
    project = await session.get(Project, project_id)
    if project is None or project.owner_id != user:
        raise NotFoundError("project not found")
    return project


# ── Documents ────────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/documents")
async def list_documents(
    project_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, project_id, user)
    rows = (await session.scalars(
        select(Document).where(Document.project_id == project_id)
        .order_by(Document.created_at.desc())
    )).all()
    return [{
        "id": d.id, "title": d.title, "source_type": d.source_type,
        "status": d.status, "status_reason": d.status_reason, "url": d.url,
        "year": d.year, "authors": d.authors, "abstract_only": d.abstract_only,
        "full_text_available": d.full_text_available,
        "created_at": d.created_at.isoformat(),
    } for d in rows]


@router.post("/projects/{project_id}/documents", status_code=201)
async def upload_document(
    project_id: str,
    file: UploadFile = File(...),
    title: str = Form(default=""),
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, project_id, user)
    if not (file.filename or "").lower().endswith(".pdf"):
        raise ValidationFailed("only PDF uploads are supported here")
    pdf_bytes = await file.read()
    doc = await ingest_pdf_document(
        session, project_id=project_id, pdf_bytes=pdf_bytes,
        source_type="upload", title=title or (file.filename or "untitled"),
    )
    return {"id": doc.id, "status": doc.status, "status_reason": doc.status_reason}


@router.delete("/projects/{project_id}/documents/{document_id}")
async def tombstone_document(
    project_id: str, document_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, project_id, user)
    doc = await session.get(Document, document_id)
    if doc is None or doc.project_id != project_id:
        raise NotFoundError("document not found")
    # Tombstone, never hard-delete: existing answers keep auditable history.
    doc.status = "tombstoned"
    from app.stores.qdrant_store import delete_document
    await delete_document(document_id)
    return {"id": doc.id, "status": doc.status}


@router.post("/projects/{project_id}/import/bibtex", status_code=202)
async def import_bibtex(
    project_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Import a .bib reference list. arXiv entries fetch full text (library-
    first); others become labeled abstract-only stubs. Runs as a job."""
    await _get_project(session, project_id, user)
    from app.ingestion.bibtex import parse_bibtex
    text = (await file.read()).decode("utf-8", "ignore")
    entries = parse_bibtex(text)[:50]
    if not entries:
        raise ValidationFailed("no BibTeX entries found in file")
    await redis_store.enqueue_job(
        "import_bibtex",
        {"project_id": project_id, "entries": [e.__dict__ for e in entries]},
    )
    return {"queued": len(entries)}


# ── Pipeline runs ────────────────────────────────────────────────────────

class PipelineStart(BaseModel):
    project_id: str
    query: str = Field(min_length=8, max_length=2000)


@router.post("/pipeline", status_code=202)
async def start_pipeline(
    body: PipelineStart,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, body.project_id, user)
    run = Run(project_id=body.project_id, query=body.query)
    session.add(run)
    await session.flush()
    await redis_store.enqueue_job("run_pipeline", {"run_id": run.id})
    return {"run_id": run.id, "status": "queued"}


@router.get("/projects/{project_id}/runs")
async def list_runs(
    project_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, project_id, user)
    rows = (await session.scalars(
        select(Run).where(Run.project_id == project_id).order_by(Run.created_at.desc())
    )).all()
    return [{
        "id": r.id, "query": r.query, "status": r.status,
        "current_node": r.current_node, "report_id": r.report_id,
        "budgets_spent": r.budgets_spent, "created_at": r.created_at.isoformat(),
    } for r in rows]


_TERMINAL = {"completed", "completed_with_gaps", "failed", "rejected", "budget_exhausted", "done"}


@router.get("/status/{run_id}/stream")
async def run_status_stream(
    run_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Server-Sent Events stream of live run progress — pushes each new
    progress update instead of the client polling. Ends on a terminal state."""
    import asyncio
    import json as _json

    from fastapi.responses import StreamingResponse

    run = await session.get(Run, run_id)
    if run is None:
        raise NotFoundError("run not found")
    await _get_project(session, run.project_id, user)

    async def gen():
        last = None
        for _ in range(900):  # safety cap ~15 min
            prog = await redis_store.read_progress(run_id)
            if prog and prog != last:
                last = prog
                yield f"data: {_json.dumps(prog)}\n\n"
            status = (prog or {}).get("status") or (prog or {}).get("node")
            if status in _TERMINAL:
                yield "event: done\ndata: {}\n\n"
                return
            await asyncio.sleep(1.0)
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/status/{run_id}")
async def run_status(
    run_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    run = await session.get(Run, run_id)
    if run is None:
        raise NotFoundError("run not found")
    await _get_project(session, run.project_id, user)
    progress = await redis_store.read_progress(run_id)
    events = await redis_store.read_events(run_id)
    return {
        "run_id": run.id, "status": run.status, "current_node": run.current_node,
        "error": run.error, "report_id": run.report_id,
        "budgets_spent": run.budgets_spent, "live": progress, "events": events,
    }


# ── Reports ──────────────────────────────────────────────────────────────

@router.get("/report/{report_id}")
async def get_report(
    report_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    report = await session.get(Report, report_id)
    if report is None:
        raise NotFoundError("report not found")
    await _get_project(session, report.project_id, user)

    sections = []
    for section in report.sections:
        claims = []
        for claim_id in section.get("claim_ids", []):
            detail = await claim_evidence_detail(session, claim_id)
            if detail:
                claims.append(detail)
        sections.append({**section, "claims": claims})

    citations = (await session.scalars(
        select(Citation).where(Citation.project_id == report.project_id)
    )).all()
    doc_ids = {c.document_id for c in citations if c.document_id}
    references = []
    if doc_ids:
        docs = (await session.scalars(
            select(Document).where(Document.id.in_(doc_ids))
        )).all()
        references = [{
            "document_id": d.id, "title": d.title, "url": d.url,
            "source_type": d.source_type, "year": d.year, "authors": d.authors,
            "abstract_only": d.abstract_only,
            "citations": int((d.meta or {}).get("citation_count") or 0),
        } for d in docs]

    return {"id": report.id, "title": report.title, "outline": report.outline,
            "confidence": report.confidence, "sections": sections,
            "references": references,
            "created_at": report.created_at.isoformat()}


@router.get("/report/{report_id}/contradictions")
async def report_contradictions(
    report_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Cross-source disagreements among the report's verified claims. Computed
    once (NLI sweep) then cached, so the first view pays, later views are free."""
    import json
    report = await session.get(Report, report_id)
    if report is None:
        raise NotFoundError("report not found")
    await _get_project(session, report.project_id, user)
    cached = await redis_store.cache_get(f"contra:{report_id}")
    if cached is not None:
        return json.loads(cached)
    from app.services.analysis import find_contradictions
    result = {"contradictions": await find_contradictions(session, report_id)}
    await redis_store.cache_set(f"contra:{report_id}", json.dumps(result), 86400)
    return result


# ── Grounded chat / refind / evidence ────────────────────────────────────

class ChatRequest(BaseModel):
    project_id: str
    question: str = Field(min_length=3, max_length=2000)
    document_id: str | None = None  # set => "Ask this paper" (scoped RAG)


@router.post("/chat")
async def chat(
    body: ChatRequest,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, body.project_id, user)
    result = await grounded_chat(
        session, body.project_id, body.question,
        document_ids=[body.document_id] if body.document_id else None,
    )
    return result.as_dict()


class RefindRequest(BaseModel):
    project_id: str
    query: str = Field(min_length=3, max_length=500)


@router.post("/refind")
async def refind_endpoint(
    body: RefindRequest,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, body.project_id, user)
    return await refind(session, body.project_id, body.query)


@router.get("/claims/{claim_id}/evidence")
async def claim_evidence(
    claim_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    detail = await claim_evidence_detail(session, claim_id)
    if detail is None:
        raise NotFoundError("claim not found")
    return detail


@router.post("/clarify")
async def clarify_endpoint(
    body: PipelineStart,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Pre-run refinement: returns 1-3 clarifying questions for a query. The UI
    collects answers and folds them into the launched run's question."""
    await _get_project(session, body.project_id, user)
    from app.agents.schemas import ClarifyResult
    from app.llm.router import complete_json
    from app.services.grounded import _intent_ok

    # Guardrail: reject off-topic / non-research asks before anything else.
    ok, why = await _intent_ok(body.query)
    if not ok:
        return {"allowed": False,
                "reason": why or "This looks like a task request, not a research "
                "question. Try asking what you want to investigate or compare.",
                "objective": "", "questions": []}
    r = await complete_json(
        "clarify_refine",
        f"Research request: {body.query}\n"
        "Return the research domain, the user's objective, and 1-3 SHORT "
        "clarifying questions whose answers would most sharpen the research "
        "(scope, time range, specific application, comparison axis). Concise.",
        ClarifyResult,
    )
    return {"allowed": True, "reason": "", "objective": r.objective,
            "questions": r.questions}


@router.get("/projects/{project_id}/map")
async def project_map(
    project_id: str, refresh: bool = False,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, project_id, user)
    import json
    key = f"map:{project_id}"
    if not refresh:
        cached = await redis_store.cache_get(key)
        if cached is not None:
            return json.loads(cached)
    from app.services.mapping import build_map
    result = await build_map(session, project_id)
    await redis_store.cache_set(key, json.dumps(result), 1800)
    return result


# ── Monitor agent ────────────────────────────────────────────────────────

class WatchCreate(BaseModel):
    query: str = Field(min_length=4, max_length=500)


@router.get("/projects/{project_id}/monitor")
async def monitor_get(
    project_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Watches + new-paper alerts. Seeds watches from the project's research on
    first view so the monitor is useful immediately."""
    await _get_project(session, project_id, user)
    from app.services.monitor import seed_watches
    await seed_watches(session, project_id)
    watches = (await session.scalars(
        select(Watch).where(Watch.project_id == project_id).order_by(Watch.created_at)
    )).all()
    alerts = (await session.scalars(
        select(MonitorAlert).where(MonitorAlert.project_id == project_id,
                                   MonitorAlert.status == "new")
        .order_by(MonitorAlert.score.desc())
    )).all()
    return {
        "watches": [{"id": w.id, "query": w.query, "active": w.active,
                     "last_checked": w.last_checked.isoformat() if w.last_checked else None}
                    for w in watches],
        "alerts": [{"id": a.id, "title": a.title, "url": a.url, "abstract": a.abstract[:400],
                    "authors": a.authors, "year": a.year, "score": a.score,
                    "arxiv_id": a.arxiv_id, "has_pdf": bool(a.pdf_url)}
                   for a in alerts],
    }


@router.post("/projects/{project_id}/watches", status_code=201)
async def watch_add(
    project_id: str, body: WatchCreate,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, project_id, user)
    w = Watch(project_id=project_id, query=body.query)
    session.add(w)
    await session.flush()
    return {"id": w.id}


@router.post("/watches/{watch_id}/toggle")
async def watch_toggle(
    watch_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    w = await session.get(Watch, watch_id)
    if w is None:
        raise NotFoundError("watch not found")
    await _get_project(session, w.project_id, user)
    w.active = not w.active
    return {"id": w.id, "active": w.active}


@router.post("/projects/{project_id}/monitor/check", status_code=202)
async def monitor_check(
    project_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, project_id, user)
    await redis_store.enqueue_job("run_monitor", {"project_id": project_id})
    return {"queued": True}


@router.post("/alerts/{alert_id}/dismiss")
async def alert_dismiss(
    alert_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    a = await session.get(MonitorAlert, alert_id)
    if a is None:
        raise NotFoundError("alert not found")
    await _get_project(session, a.project_id, user)
    a.status = "dismissed"
    return {"id": a.id, "status": a.status}


@router.post("/alerts/{alert_id}/add")
async def alert_add_to_corpus(
    alert_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Ingest the discovered paper into the project corpus (library-first PDF
    fetch, else an abstract stub), and mark the alert handled."""
    a = await session.get(MonitorAlert, alert_id)
    if a is None:
        raise NotFoundError("alert not found")
    await _get_project(session, a.project_id, user)
    from app.ingestion.pipeline import ingest_pdf_document, ingest_text_document
    from app.stores import blob_store

    pdf = None
    if a.arxiv_id:
        key = blob_store.library_key(arxiv_id=a.arxiv_id)
        if key and blob_store.has_pdf(key):
            pdf = blob_store.load_pdf(key)
        elif a.pdf_url:
            from app.agents import sources
            pdf = await sources.download_pdf(a.pdf_url)
            if pdf and key:
                blob_store.save_pdf(key, pdf)
    if pdf:
        doc = await ingest_pdf_document(
            session, project_id=a.project_id, pdf_bytes=pdf, source_type="paper",
            title=a.title, authors=a.authors, year=a.year, url=a.url,
            doi=a.doi, arxiv_id=a.arxiv_id, external_id=a.external_id,
        )
    else:
        doc = await ingest_text_document(
            session, project_id=a.project_id, text=f"# {a.title}\n\n{a.abstract}",
            source_type="paper", title=a.title, url=a.url, external_id=a.external_id,
            abstract_only=True,
        )
    a.status = "added"
    return {"id": a.id, "document_id": doc.id, "status": doc.status}


# ── Findings notebook ────────────────────────────────────────────────────

class NotebookSave(BaseModel):
    claim_id: str
    note: str = ""


@router.post("/projects/{project_id}/notebook", status_code=201)
async def notebook_save(
    project_id: str, body: NotebookSave,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, project_id, user)
    existing = await session.scalar(
        select(SavedClaim).where(SavedClaim.project_id == project_id,
                                 SavedClaim.claim_id == body.claim_id)
    )
    if existing:
        if body.note:
            existing.note = body.note
        return {"id": existing.id, "saved": True}
    row = SavedClaim(project_id=project_id, claim_id=body.claim_id, note=body.note)
    session.add(row)
    await session.flush()
    return {"id": row.id, "saved": True}


@router.get("/projects/{project_id}/notebook")
async def notebook_list(
    project_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, project_id, user)
    rows = (await session.scalars(
        select(SavedClaim).where(SavedClaim.project_id == project_id)
        .order_by(SavedClaim.created_at.desc())
    )).all()
    out = []
    for r in rows:
        claim = await session.get(Claim, r.claim_id)
        ev = (await session.scalars(
            select(ClaimEvidence).where(ClaimEvidence.claim_id == r.claim_id)
        )).first()
        doc_title, page, quote = "", 0, ""
        if ev:
            quote = ev.quote
            chunk = await session.get(Chunk, ev.chunk_id)
            if chunk:
                page = chunk.page_start
                doc = await session.get(Document, chunk.document_id)
                if doc:
                    doc_title = doc.title
        out.append({
            "id": r.id, "claim_id": r.claim_id,
            "text": claim.text if claim else "(claim removed)", "note": r.note,
            "source": doc_title, "page": page, "quote": quote,
            "created_at": r.created_at.isoformat(),
        })
    return out


@router.delete("/notebook/{saved_id}")
async def notebook_delete(
    saved_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    row = await session.get(SavedClaim, saved_id)
    if row:
        await _get_project(session, row.project_id, user)
        await session.delete(row)
    return {"deleted": True}


# ── Research notes ───────────────────────────────────────────────────────

class NoteCreate(BaseModel):
    title: str = ""
    body: str = ""
    tags: list[str] = Field(default_factory=list)
    source_ref: str = ""
    claim_id: str | None = None


class NoteUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    tags: list[str] | None = None


def _note_dict(n: Note) -> dict:
    return {"id": n.id, "title": n.title, "body": n.body, "tags": n.tags,
            "source_ref": n.source_ref, "claim_id": n.claim_id,
            "updated_at": n.updated_at.isoformat()}


@router.get("/projects/{project_id}/notes")
async def notes_list(
    project_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, project_id, user)
    rows = (await session.scalars(
        select(Note).where(Note.project_id == project_id).order_by(Note.updated_at.desc())
    )).all()
    return [_note_dict(n) for n in rows]


@router.post("/projects/{project_id}/notes", status_code=201)
async def note_create(
    project_id: str, body: NoteCreate,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, project_id, user)
    n = Note(project_id=project_id, title=body.title, body=body.body, tags=body.tags,
             source_ref=body.source_ref, claim_id=body.claim_id)
    session.add(n)
    await session.flush()
    return _note_dict(n)


@router.patch("/notes/{note_id}")
async def note_update(
    note_id: str, body: NoteUpdate,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    n = await session.get(Note, note_id)
    if n is None:
        raise NotFoundError("note not found")
    await _get_project(session, n.project_id, user)
    if body.title is not None:
        n.title = body.title
    if body.body is not None:
        n.body = body.body
    if body.tags is not None:
        n.tags = body.tags
    return _note_dict(n)


@router.delete("/notes/{note_id}")
async def note_delete(
    note_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    n = await session.get(Note, note_id)
    if n:
        await _get_project(session, n.project_id, user)
        await session.delete(n)
    return {"deleted": True}


# ── Graph ────────────────────────────────────────────────────────────────

@router.get("/graph/{project_id}")
async def get_graph(
    project_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, project_id, user)
    edges = (await session.scalars(
        select(GraphEdge).where(GraphEdge.project_id == project_id)
    )).all()
    node_ids = {(e.src_type, e.src_id) for e in edges} | {(e.dst_type, e.dst_id) for e in edges}
    docs = {d.id: d for d in (await session.scalars(
        select(Document).where(Document.id.in_([nid for _, nid in node_ids]))
    )).all()}
    return {
        "nodes": [{
            "id": nid, "type": ntype,
            "label": docs[nid].title[:80] if nid in docs else nid,
        } for ntype, nid in node_ids],
        "edges": [{"src": e.src_id, "dst": e.dst_id, "relation": e.relation,
                   "weight": e.weight} for e in edges],
    }
