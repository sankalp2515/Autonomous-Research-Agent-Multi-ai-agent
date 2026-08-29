"""HTTP API. Kept surface from v1 (/api/pipeline /api/status /api/report
/api/chat /api/graph) plus workspace endpoints (projects, documents,
refind, claim evidence)."""

from datetime import datetime, timezone

from fastapi import (
    APIRouter, Depends, File, Form, Header, Response, UploadFile, WebSocket,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_email, current_name, current_user
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.exceptions import (
    ConflictError, NotFoundError, ServiceBusyError, ValidationFailed,
)
from app.db.models import (
    Chunk, Citation, Claim, ClaimEvidence, Comparison, Document, GraphEdge,
    Invitation, Membership, Memory, MonitorAlert, Note, Organization, Project,
    Report, Run, SavedClaim, ShareLink, UserProfile, Watch,
)
from app.db.session import get_session
from app.ingestion.pipeline import ingest_pdf_document
from app.services.grounded import claim_evidence_detail, grounded_chat, refind
from app.stores import redis_store

logger = get_logger("api")

router = APIRouter(prefix="/api")

# Pagination defaults. `limit` is generous so existing single-page clients are
# unaffected, but it CAPS an otherwise-unbounded full-table scan on big projects.
_PAGE_DEFAULT = 100
_PAGE_MAX = 500


def _page(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, _PAGE_MAX)), max(0, offset)


# ── Projects ─────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    org_id: str | None = None  # target org; defaults to the caller's personal org


@router.get("/projects")
async def list_projects(
    limit: int = _PAGE_DEFAULT, offset: int = 0,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user)
):
    limit, offset = _page(limit, offset)
    # Tenancy: projects across every org the user belongs to, plus any legacy
    # projects they still own directly (org_id null, pre-tenancy).
    from sqlalchemy import or_
    from app.db.models import Membership
    org_ids = list((await session.scalars(
        select(Membership.org_id).where(Membership.user_id == user))).all())
    cond = Project.owner_id == user
    if org_ids:
        cond = or_(cond, Project.org_id.in_(org_ids))
    rows = (await session.scalars(
        select(Project).where(cond)
        .order_by(Project.created_at.desc()).limit(limit).offset(offset)
    )).all()
    if not rows:
        return []
    # Two grouped aggregates instead of 2 counts per project (was 2N+1 queries).
    ids = [p.id for p in rows]
    doc_counts = dict((await session.execute(
        select(Document.project_id, func.count(Document.id))
        .where(Document.project_id.in_(ids)).group_by(Document.project_id)
    )).all())
    run_counts = dict((await session.execute(
        select(Run.project_id, func.count(Run.id))
        .where(Run.project_id.in_(ids)).group_by(Run.project_id)
    )).all())
    return [{"id": p.id, "name": p.name, "description": p.description,
             "org_id": p.org_id,
             "documents": doc_counts.get(p.id, 0), "runs": run_counts.get(p.id, 0),
             "created_at": p.created_at.isoformat()} for p in rows]


@router.post("/projects", status_code=201)
async def create_project(
    body: ProjectCreate,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    from app.services.tenancy import ensure_personal_org, role_in_org, role_ok
    # Attach to the requested org (caller must be member+ there) or the personal one.
    if body.org_id:
        if not role_ok(await role_in_org(session, user, body.org_id), "member"):
            raise NotFoundError("organization not found")
        org_id = body.org_id
    else:
        org_id = await ensure_personal_org(session, user)
    project = Project(owner_id=user, org_id=org_id,
                      name=body.name, description=body.description)
    session.add(project)
    await session.flush()
    return {"id": project.id, "name": project.name}


# ── Organizations / teams / roles ────────────────────────────────────────────

class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class MemberAdd(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)  # the member's auth subject
    role: str = Field(default="member")


class RoleUpdate(BaseModel):
    role: str


_ROLES = {"viewer", "member", "admin", "owner"}


async def _require_org_role(session: AsyncSession, org_id: str, user: str, minimum: str):
    from app.services.tenancy import role_in_org, role_ok
    if not role_ok(await role_in_org(session, user, org_id), minimum):
        raise NotFoundError("organization not found")


@router.get("/orgs")
async def list_orgs(session: AsyncSession = Depends(get_session), user: str = Depends(current_user)):
    from app.services.tenancy import ensure_personal_org, user_orgs
    await ensure_personal_org(session, user)  # every user always has one
    return await user_orgs(session, user)


@router.post("/orgs", status_code=201)
async def create_org(body: OrgCreate, session: AsyncSession = Depends(get_session),
                     user: str = Depends(current_user)):
    org = Organization(name=body.name, personal=False, created_by=user)
    session.add(org)
    await session.flush()
    session.add(Membership(org_id=org.id, user_id=user, role="owner"))
    return {"id": org.id, "name": org.name}


@router.get("/orgs/{org_id}/members")
async def list_members(org_id: str, session: AsyncSession = Depends(get_session),
                       user: str = Depends(current_user)):
    await _require_org_role(session, org_id, user, "member")
    rows = (await session.scalars(
        select(Membership).where(Membership.org_id == org_id))).all()
    profiles = {p.user_id: p for p in (await session.scalars(
        select(UserProfile).where(UserProfile.user_id.in_([m.user_id for m in rows]))
    )).all()} if rows else {}
    out = []
    for m in rows:
        p = profiles.get(m.user_id)
        out.append({"user_id": m.user_id, "role": m.role,
                    "email": p.email if p else "",
                    "name": (p.display_name if p and p.display_name else
                             (p.email.split("@")[0] if p and p.email else ""))})
    return out


@router.post("/orgs/{org_id}/members", status_code=201)
async def add_member(org_id: str, body: MemberAdd, session: AsyncSession = Depends(get_session),
                     user: str = Depends(current_user)):
    await _require_org_role(session, org_id, user, "admin")
    if body.role not in _ROLES:
        raise ValidationFailed(f"role must be one of {sorted(_ROLES)}")
    org = await session.get(Organization, org_id)
    if org and org.personal:
        raise ValidationFailed("cannot add members to a personal workspace")
    existing = await session.scalar(select(Membership).where(
        Membership.org_id == org_id, Membership.user_id == body.user_id))
    if existing:
        existing.role = body.role
    else:
        session.add(Membership(org_id=org_id, user_id=body.user_id, role=body.role))
    return {"user_id": body.user_id, "role": body.role}


@router.patch("/orgs/{org_id}/members/{member_id}")
async def update_member(org_id: str, member_id: str, body: RoleUpdate,
                        session: AsyncSession = Depends(get_session), user: str = Depends(current_user)):
    await _require_org_role(session, org_id, user, "admin")
    if body.role not in _ROLES:
        raise ValidationFailed(f"role must be one of {sorted(_ROLES)}")
    m = await session.scalar(select(Membership).where(
        Membership.org_id == org_id, Membership.user_id == member_id))
    if m is None:
        raise NotFoundError("member not found")
    m.role = body.role
    return {"user_id": member_id, "role": body.role}


@router.delete("/orgs/{org_id}/members/{member_id}")
async def remove_member(org_id: str, member_id: str,
                        session: AsyncSession = Depends(get_session), user: str = Depends(current_user)):
    await _require_org_role(session, org_id, user, "admin")
    if member_id == user:
        raise ValidationFailed("you cannot remove yourself from an org")
    m = await session.scalar(select(Membership).where(
        Membership.org_id == org_id, Membership.user_id == member_id))
    if m:
        await session.delete(m)
    return {"removed": member_id}


# ── Email invitations ────────────────────────────────────────────────────────

class InviteCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = Field(default="member")


@router.post("/orgs/{org_id}/invites", status_code=201)
async def create_invite(org_id: str, body: InviteCreate,
                        session: AsyncSession = Depends(get_session), user: str = Depends(current_user)):
    await _require_org_role(session, org_id, user, "admin")
    if body.role not in _ROLES:
        raise ValidationFailed(f"role must be one of {sorted(_ROLES)}")
    org = await session.get(Organization, org_id)
    if org and org.personal:
        raise ValidationFailed("cannot invite to a personal workspace")
    email = body.email.strip().lower()
    existing = await session.scalar(select(Invitation).where(
        Invitation.org_id == org_id, Invitation.email == email,
        Invitation.status == "pending"))
    if existing:
        existing.role = body.role
        return {"id": existing.id, "email": email, "role": body.role}
    inv = Invitation(org_id=org_id, email=email, role=body.role, invited_by=user)
    session.add(inv)
    await session.flush()
    # Queue the invite email so delivery is DURABLE (survives a restart, gets the
    # queue's retry/dead-letter) rather than a fire-and-forget task.
    inviter = await session.get(UserProfile, user)
    inviter_label = (inviter.display_name or inviter.email) if inviter else user
    await redis_store.enqueue_job("send_invite_email", {
        "email": email, "org_name": org.name if org else "workspace",
        "inviter": inviter_label, "role": body.role})
    return {"id": inv.id, "email": email, "role": body.role}


@router.get("/orgs/{org_id}/invites")
async def list_invites(org_id: str, session: AsyncSession = Depends(get_session),
                       user: str = Depends(current_user)):
    await _require_org_role(session, org_id, user, "admin")
    rows = (await session.scalars(select(Invitation).where(
        Invitation.org_id == org_id, Invitation.status == "pending"))).all()
    return [{"id": i.id, "email": i.email, "role": i.role} for i in rows]


@router.delete("/orgs/{org_id}/invites/{invite_id}")
async def revoke_invite(org_id: str, invite_id: str,
                        session: AsyncSession = Depends(get_session), user: str = Depends(current_user)):
    await _require_org_role(session, org_id, user, "admin")
    inv = await session.get(Invitation, invite_id)
    if inv and inv.org_id == org_id:
        inv.status = "revoked"
    return {"revoked": invite_id}


async def _record_profile(session: AsyncSession, user: str, email: str, name: str) -> None:
    """Upsert the caller's directory row so member lists show a real identity."""
    if not (email or name):
        return
    prof = await session.get(UserProfile, user)
    if prof is None:
        session.add(UserProfile(user_id=user, email=email or "", display_name=name or ""))
    else:
        if email:
            prof.email = email
        if name:
            prof.display_name = name


@router.post("/invites/accept")
async def accept_invites(session: AsyncSession = Depends(get_session),
                         user: str = Depends(current_user), email: str = Depends(current_email),
                         name: str = Depends(current_name)):
    """Convert every pending invitation matching the caller's email into a
    membership. Also records the user's directory profile (email/name). Idempotent
    — called on login/first org view; safe to repeat."""
    await _record_profile(session, user, email, name)
    if not email:
        return {"joined": 0, "orgs": []}
    pending = (await session.scalars(select(Invitation).where(
        Invitation.email == email, Invitation.status == "pending"))).all()
    joined: list[str] = []
    for inv in pending:
        already = await session.scalar(select(Membership).where(
            Membership.org_id == inv.org_id, Membership.user_id == user))
        if not already:
            session.add(Membership(org_id=inv.org_id, user_id=user, role=inv.role))
        inv.status = "accepted"
        joined.append(inv.org_id)
    return {"joined": len(joined), "orgs": joined}


async def _get_project(session: AsyncSession, project_id: str, user: str,
                       *, minimum: str = "viewer") -> Project:
    """Fetch a project the caller may access at >= `minimum` role. Tenancy-aware:
    authorization goes through org membership (with a legacy owner_id fallback).
    A 'not found' is returned for both missing and unauthorized, so the API never
    reveals the existence of another tenant's project."""
    from app.services.tenancy import authorize_project
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError("project not found")
    if not await authorize_project(session, project, user, minimum=minimum):
        raise NotFoundError("project not found")
    return project


# ── Documents ────────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/documents")
async def list_documents(
    project_id: str, limit: int = _PAGE_DEFAULT, offset: int = 0,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, project_id, user)
    limit, offset = _page(limit, offset)
    rows = (await session.scalars(
        select(Document).where(Document.project_id == project_id)
        .order_by(Document.created_at.desc()).limit(limit).offset(offset)
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
    # Bounded read: cap BEFORE buffering the whole file, so a multi-GB upload
    # can't exhaust memory ahead of the parser's size check. read(n) yields at
    # most n bytes; reading cap+1 lets us detect an over-limit file cheaply.
    max_bytes = get_settings().ingest_max_pdf_mb * 1024 * 1024
    pdf_bytes = await file.read(max_bytes + 1)
    if len(pdf_bytes) > max_bytes:
        raise ValidationFailed(f"PDF exceeds {get_settings().ingest_max_pdf_mb}MB limit")
    if not pdf_bytes.startswith(b"%PDF"):
        raise ValidationFailed("file is not a valid PDF")
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
    # .bib files are small; cap the read so a huge upload can't exhaust memory.
    _BIB_MAX = 5 * 1024 * 1024
    raw = await file.read(_BIB_MAX + 1)
    if len(raw) > _BIB_MAX:
        raise ValidationFailed("BibTeX file too large (5MB limit)")
    text = raw.decode("utf-8", "ignore")
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
    scope: str = Field(default="all", pattern="^(all|papers|library)$")
    since_year: int = Field(default=0, ge=0, le=2100)   # 0 = any time (recency still prioritized)
    until_year: int = Field(default=0, ge=0, le=2100)   # 0 = no upper bound (year range ceiling)
    min_citations: int = Field(default=0, ge=0, le=100000)  # 0 = no citation floor
    # Researcher-selected candidates (from the screening step) to ingest exactly.
    # When present, the run skips its own search and uses these.
    selected_papers: list[dict] = Field(default_factory=list, max_length=60)


@router.post("/pipeline", status_code=202)
async def start_pipeline(
    body: PipelineStart,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, body.project_id, user)
    settings = get_settings()

    # Idempotency: a client that retries the same submit (double-click, network
    # retry) with an `Idempotency-Key` header gets back the SAME run instead of
    # launching a second one. Scoped by user+project so keys can't collide across
    # tenants. Checked before backpressure so a retry is never spuriously shed.
    idem_scoped = None
    if idempotency_key:
        idem_scoped = f"{user}:{body.project_id}:{idempotency_key[:80]}"
        existing = await redis_store.idempotency_get(idem_scoped)
        if existing:
            return {"run_id": existing, "status": "queued", "idempotent": True}

    # Backpressure #1 — global load shed: if the queue is saturated, refuse new
    # work with a retryable 503 instead of letting it pile onto a busy worker.
    depth = await redis_store.queue_depth()
    if depth >= settings.max_queue_depth:
        raise ServiceBusyError(
            "The research queue is at capacity right now — please retry shortly.",
            detail={"queue_depth": depth},
        )

    # Backpressure #2 — per-project admission cap: bound concurrent runs so one
    # project can't monopolize the worker pool.
    active = await session.scalar(
        select(func.count(Run.id)).where(
            Run.project_id == body.project_id,
            Run.status.in_(["queued", "running"]),
        )
    )
    if (active or 0) >= settings.max_concurrent_runs_per_project:
        raise ConflictError(
            f"This project already has {active} run(s) in progress "
            f"(limit {settings.max_concurrent_runs_per_project}). "
            "Wait for one to finish before starting another."
        )

    run = Run(project_id=body.project_id, query=body.query)
    session.add(run)
    await session.flush()
    if idem_scoped:
        # Record the mapping so a later retry with the same key returns this run.
        await redis_store.idempotency_set(idem_scoped, run.id)
    await redis_store.enqueue_job(
        "run_pipeline",
        {"run_id": run.id, "scope": body.scope, "since_year": body.since_year,
         "until_year": body.until_year, "min_citations": body.min_citations,
         "selected_papers": body.selected_papers},
    )
    return {"run_id": run.id, "status": "queued"}


@router.get("/projects/{project_id}/runs")
async def list_runs(
    project_id: str, limit: int = _PAGE_DEFAULT, offset: int = 0,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, project_id, user)
    limit, offset = _page(limit, offset)
    rows = (await session.scalars(
        select(Run).where(Run.project_id == project_id)
        .order_by(Run.created_at.desc()).limit(limit).offset(offset)
    )).all()
    return [{
        "id": r.id, "query": r.query, "status": r.status,
        "current_node": r.current_node, "report_id": r.report_id,
        "budgets_spent": r.budgets_spent, "created_at": r.created_at.isoformat(),
        **_run_clock(r),
    } for r in rows]


# A cancelled run is terminal too: nothing is driving it, so the live-status
# poller must stop waiting on it and the UI must stop offering "stop".
_TERMINAL = {"completed", "completed_with_gaps", "failed", "rejected",
             "budget_exhausted", "done", "cancelled"}


def _epoch(dt: datetime | None) -> float:
    """Seconds since the epoch, treating a naive timestamp as UTC.

    SQLite drops the tzinfo that `DateTime(timezone=True)` carries on Postgres,
    so a naive value here is a UTC value that lost its label — never local time.
    Reading it as local is what made the run clock wrong by whole hours.
    """
    if dt is None:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _run_clock(run: Run) -> dict:
    """The run's wall clock, computed server-side against ONE reference now.

    `budgets_spent["seconds"]` is only rewritten at a node checkpoint, so during
    a long node (research can run for minutes) it freezes and the UI reads as a
    stalled timer. This is the authoritative value; the client ticks forward
    from it between polls instead of inventing its own start time.
    """
    started = _epoch(run.created_at)
    now = datetime.now(timezone.utc).timestamp()
    finished = run.status in _TERMINAL
    end = _epoch(run.updated_at) if finished else now
    elapsed = max(0.0, end - started)
    return {
        "started_epoch": started,
        "server_now": now,
        "running": not finished,
        "elapsed_seconds": round(elapsed),
    }


@router.get("/status/{run_id}/stream")
async def run_status_stream(
    run_id: str,
    user: str = Depends(current_user),
):
    """Server-Sent Events stream of live run progress — pushes each new
    progress update instead of the client polling. Ends on a terminal state.

    Access is verified with a short-lived session that is released immediately;
    the (up to 15-minute) stream itself touches only Redis, so it never pins a
    pooled DB connection for its lifetime — that would exhaust the pool as soon
    as a handful of viewers watch runs concurrently."""
    import json as _json

    from fastapi.responses import StreamingResponse

    from app.db.session import session_scope

    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise NotFoundError("run not found")
        await _get_project(session, run.project_id, user)

    async def gen():
        import time as _time

        def _is_terminal(p) -> bool:
            s = (p or {}).get("status") or (p or {}).get("node")
            return s in _TERMINAL

        last = None
        deadline = _time.monotonic() + 900  # hard 15-min ceiling per connection

        # Snapshot first — catch anything published before we subscribed.
        snap = await redis_store.read_progress(run_id)
        if snap:
            last = snap
            yield f"data: {_json.dumps(snap)}\n\n"
            if _is_terminal(snap):
                yield "event: done\ndata: {}\n\n"
                return

        # Then event-driven: wake on publish, not on a 1s clock. The idle ticks
        # (None) let us re-read the snapshot as a backstop for missed messages.
        async for msg in redis_store.subscribe_progress(run_id):
            if _time.monotonic() > deadline:
                break
            prog = msg
            if prog is None:  # idle tick
                prog = await redis_store.read_progress(run_id)
            if prog and prog != last:
                last = prog
                yield f"data: {_json.dumps(prog)}\n\n"
            if _is_terminal(prog):
                yield "event: done\ndata: {}\n\n"
                return
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.websocket("/status/{run_id}/ws")
async def run_status_ws(websocket: WebSocket, run_id: str):
    """WebSocket push of run progress, terminating with a `{"event":"done"}`
    frame the client turns into a completion notification — so a user who
    navigates away (or backgrounds the tab) is pulled back when the verified
    report is ready instead of babysitting a spinner.

    Auth handshake: the browser can't attach an Authorization header to a WS,
    and putting the token in the URL leaks it into logs. So the FIRST frame the
    client sends is `{"token": "<jwt>"}` (or the raw token) — verified against
    the same JWKS path as HTTP before any run data is streamed."""
    import asyncio
    import json as _json
    import time as _time

    from fastapi import WebSocketDisconnect

    from app.api.deps import user_from_token
    from app.core.exceptions import AuthError
    from app.db.session import session_scope

    await websocket.accept()
    try:
        first = await asyncio.wait_for(websocket.receive_text(), timeout=10)
    except (asyncio.TimeoutError, WebSocketDisconnect, RuntimeError):
        await _ws_close(websocket, 4401)
        return
    try:
        token = (_json.loads(first) or {}).get("token")
    except (ValueError, TypeError):
        token = first  # tolerate a raw token frame
    try:
        user = await user_from_token(token)
    except AuthError:
        await _ws_close(websocket, 4401)
        return

    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            await _ws_close(websocket, 4404)
            return
        try:
            await _get_project(session, run.project_id, user)
        except Exception:
            await _ws_close(websocket, 4403)
            return

    def _is_terminal(p) -> bool:
        s = (p or {}).get("status") or (p or {}).get("node")
        return s in _TERMINAL

    async def _send(payload: dict) -> None:
        await websocket.send_text(_json.dumps(payload))

    try:
        last = await redis_store.read_progress(run_id)
        if last:
            await _send(last)
            if _is_terminal(last):
                await _send({"event": "done", "status": last.get("status") or last.get("node")})
                await _ws_close(websocket)
                return
        deadline = _time.monotonic() + 900  # 15-min ceiling per connection
        async for msg in redis_store.subscribe_progress(run_id):
            if _time.monotonic() > deadline:
                break
            prog = msg if msg is not None else await redis_store.read_progress(run_id)
            if prog and prog != last:
                last = prog
                await _send(prog)
            if _is_terminal(prog):
                await _send({"event": "done", "status": (prog or {}).get("status") or (prog or {}).get("node")})
                break
    except WebSocketDisconnect:
        return
    finally:
        await _ws_close(websocket)


async def _ws_close(websocket, code: int = 1000) -> None:
    try:
        await websocket.close(code=code)
    except Exception:
        pass


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
        **_run_clock(run),
    }


# ── Reports ──────────────────────────────────────────────────────────────

async def _report_payload(session: AsyncSession, report: Report) -> dict:
    """Assemble a report's full render payload (sections + claims + evidence +
    references). Extracted so the authenticated GET and the public shared-link
    GET return byte-identical bodies from one code path."""
    # Batch-load every claim + evidence + chunk + document the report needs in a
    # handful of queries. The previous per-claim path was an N+1 fan-out: a
    # 6-section × 5-claim report issued ~120 sequential round trips just to
    # render. Here it is 4, regardless of report size.
    all_claim_ids = [cid for s in report.sections for cid in s.get("claim_ids", [])]
    claims_by_id: dict[str, Claim] = {}
    ev_by_claim: dict[str, list[ClaimEvidence]] = {}
    chunks_by_id: dict[str, Chunk] = {}
    docs_by_id: dict[str, Document] = {}
    if all_claim_ids:
        claims_by_id = {c.id: c for c in (await session.scalars(
            select(Claim).where(Claim.id.in_(all_claim_ids)))).all()}
        for ev in (await session.scalars(
            select(ClaimEvidence).where(ClaimEvidence.claim_id.in_(all_claim_ids)))).all():
            ev_by_claim.setdefault(ev.claim_id, []).append(ev)
        ev_chunk_ids = [ev.chunk_id for evs in ev_by_claim.values() for ev in evs]
        if ev_chunk_ids:
            chunks_by_id = {c.id: c for c in (await session.scalars(
                select(Chunk).where(Chunk.id.in_(ev_chunk_ids)))).all()}
            ev_doc_ids = {c.document_id for c in chunks_by_id.values()}
            docs_by_id = {d.id: d for d in (await session.scalars(
                select(Document).where(Document.id.in_(ev_doc_ids)))).all()}

    def _detail(claim_id: str) -> dict | None:
        claim = claims_by_id.get(claim_id)
        if claim is None:
            return None
        evidence = []
        for ev in ev_by_claim.get(claim_id, []):
            chunk = chunks_by_id.get(ev.chunk_id)
            doc = docs_by_id.get(chunk.document_id) if chunk else None
            evidence.append({
                "chunk_id": ev.chunk_id, "quote": ev.quote,
                "quote_char_start": ev.quote_char_start,
                "quote_char_end": ev.quote_char_end,
                "nli_label": ev.nli_label, "nli_score": ev.nli_score,
                "chunk_text": chunk.text if chunk else "(chunk removed)",
                "section": chunk.section if chunk else "",
                "pages": [chunk.page_start, chunk.page_end] if chunk else [],
                "document": {
                    "id": doc.id, "title": doc.title, "url": doc.url,
                    "source_type": doc.source_type, "status": doc.status,
                    "abstract_only": doc.abstract_only,
                } if doc else {"status": "tombstoned"},
            })
        return {"claim_id": claim.id, "text": claim.text,
                "status": claim.status, "evidence": evidence}

    sections = []
    for section in report.sections:
        claims = [d for cid in section.get("claim_ids", []) if (d := _detail(cid))]
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

    # The QUESTION the researcher actually asked. The report carries a
    # generated title and a derived objective, and neither is the question:
    # the objective is written as a purpose ("To understand the interplay
    # between…"), which reads badly as a headline and is not what was asked.
    # A systematic review is titled by its question, so the reader can see at a
    # glance whether it answers theirs.
    question = ""
    if report.run_id:
        question = (await session.scalar(
            select(Run.query).where(Run.id == report.run_id))) or ""

    return {"id": report.id, "title": report.title, "question": question,
            "outline": report.outline,
            "confidence": report.confidence, "sections": sections,
            "references": references,
            "created_at": report.created_at.isoformat()}


@router.get("/report/{report_id}")
async def get_report(
    report_id: str, response: Response,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    report = await session.get(Report, report_id)
    if report is None:
        raise NotFoundError("report not found")
    await _get_project(session, report.project_id, user)
    # A report's body is immutable once assembled; only its project-wide
    # reference list can grow. A short private cache avoids re-fetching the
    # (query-heavy) report on every in-session navigation without risking
    # more than ~a minute of reference staleness.
    response.headers["Cache-Control"] = "private, max-age=60"
    return await _report_payload(session, report)


# ── Sharing: stable short tokens for deep-linkable, read-only reports ────────
# A ShareLink is a new table, so init_db()'s create_all builds it with no
# migration. The slug is a short, unguessable token — the URL-shortening layer
# that turns a 32-char report id into elicit-style /s/{slug} share links.

def _share_slug() -> str:
    import secrets
    return secrets.token_urlsafe(8)  # ~11 chars, ~66 bits — unguessable


@router.post("/report/{report_id}/share", status_code=201)
async def create_share(
    report_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Create (or return the existing) public read-only share link for a report."""
    report = await session.get(Report, report_id)
    if report is None:
        raise NotFoundError("report not found")
    await _get_project(session, report.project_id, user)  # owner-only
    existing = await session.scalar(
        select(ShareLink).where(ShareLink.report_id == report_id,
                                ShareLink.revoked.is_(False)))
    if existing:
        return {"slug": existing.slug}
    link = ShareLink(slug=_share_slug(), report_id=report_id,
                     project_id=report.project_id, created_by=user)
    session.add(link)
    await session.flush()
    return {"slug": link.slug}


@router.delete("/report/{report_id}/share")
async def revoke_share(
    report_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    report = await session.get(Report, report_id)
    if report is None:
        raise NotFoundError("report not found")
    await _get_project(session, report.project_id, user)
    for link in (await session.scalars(
        select(ShareLink).where(ShareLink.report_id == report_id))).all():
        link.revoked = True
    return {"revoked": True}


@router.get("/shared/{slug}")
async def get_shared_report(
    slug: str, response: Response,
    session: AsyncSession = Depends(get_session),
):
    """PUBLIC, read-only report by share slug — NO auth. The slug is the
    capability: only someone the owner gave the link to can open it. Nothing
    here mutates, and only the report body (already gate-verified) is exposed."""
    link = await session.scalar(
        select(ShareLink).where(ShareLink.slug == slug, ShareLink.revoked.is_(False)))
    if link is None:
        raise NotFoundError("shared report not found or the link was revoked")
    report = await session.get(Report, link.report_id)
    if report is None:
        raise NotFoundError("shared report not found")
    response.headers["Cache-Control"] = "public, max-age=120"
    payload = await _report_payload(session, report)
    payload["shared"] = True
    return payload


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


@router.get("/report/{report_id}/metrics")
async def report_metrics(
    report_id: str, refresh: bool = False,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """RAG evaluation metrics for this report (citation accuracy, faithfulness,
    answer relevance, context precision/recall, latency) with a per-claim
    evidence trace. Computed once (ML sweep) then cached."""
    import json
    report = await session.get(Report, report_id)
    if report is None:
        raise NotFoundError("report not found")
    await _get_project(session, report.project_id, user)
    cache_key = f"metrics:{report_id}"
    if not refresh:
        cached = await redis_store.cache_get(cache_key)
        if cached is not None:
            return json.loads(cached)
    from app.services.evaluation import compute_report_metrics
    result = await compute_report_metrics(session, report_id)
    await redis_store.cache_set(cache_key, json.dumps(result), 86400)
    return result


@router.get("/report/{report_id}/next-questions")
async def report_next_questions(
    report_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Elicit-style 'you might also investigate…' — 2-4 follow-up research
    directions derived from what this report answered and where it had gaps.
    Computed once then cached, so the suggestions are free to re-show."""
    import json
    report = await session.get(Report, report_id)
    if report is None:
        raise NotFoundError("report not found")
    await _get_project(session, report.project_id, user)
    cached = await redis_store.cache_get(f"nextq:{report_id}")
    if cached is not None:
        return json.loads(cached)

    from app.agents.schemas import NextQuestions
    from app.llm.router import complete_json

    subqs = [s.get("sub_question", "") for s in report.sections if s.get("sub_question")]
    gaps = [s.get("gap_note", "") for s in report.sections
            if s.get("status") == "gap" and s.get("gap_note")]
    prompt = (
        "A verified research report was just produced.\n"
        f"Title: {report.title}\n"
        "Questions it answered:\n- " + "\n- ".join(subqs[:8]) + "\n"
    )
    if gaps:
        prompt += "Open gaps where evidence was missing:\n- " + "\n- ".join(gaps[:4]) + "\n"
    prompt += (
        "Propose 2-4 specific, distinct follow-up research questions a "
        "researcher would naturally pursue next — going deeper, exploring an "
        "adjacent angle, or addressing one of the gaps. Each a single, clear, "
        "self-contained question."
    )
    try:
        r = await complete_json("next_questions", prompt, NextQuestions)
        questions = [q for q in r.questions if len(q) > 12][:4]
    except Exception:
        questions = []
    result = {"questions": questions}
    # Short TTL when empty so a transient LLM hiccup can be retried soon.
    await redis_store.cache_set(f"nextq:{report_id}", json.dumps(result),
                                86400 if questions else 120)
    return result


# ── Grounded chat / refind / evidence ────────────────────────────────────

class EntityRef(BaseModel):
    kind: str = Field(max_length=32)
    id: str = Field(max_length=64)


class ChatRequest(BaseModel):
    project_id: str
    question: str = Field(min_length=3, max_length=2000)
    document_id: str | None = None  # set => "Ask this paper" (scoped RAG)
    # One-off chat context: papers / claims / answers selected anywhere in the
    # app. Resolved to a grounding scope; the chat is still fully gate-verified.
    entity_refs: list[EntityRef] | None = Field(default=None, max_length=50)


@router.post("/chat")
async def chat(
    body: ChatRequest,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, body.project_id, user)
    result = await grounded_chat(
        session, body.project_id, body.question,
        document_ids=[body.document_id] if body.document_id else None,
        entity_refs=[r.model_dump() for r in body.entity_refs] if body.entity_refs else None,
    )
    # Tag the persisted answer with its surface so only main-Ask ("corpus")
    # history is restored later (not paper-drawer or selection chats).
    from app.db.models import Answer
    kind = "paper" if body.document_id else ("selection" if body.entity_refs else "corpus")
    ans = await session.get(Answer, result.answer_id)
    if ans is not None:
        ans.kind = kind
    return result.as_dict()


@router.get("/projects/{project_id}/answers")
async def list_answers(
    project_id: str, limit: int = 20,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Recent corpus-chat history, reconstructed as ChatResult-shaped turns so the
    Ask view can restore the conversation after a refresh (answers are durable in
    Postgres; only the client view was ephemeral). Batch-loaded, oldest→newest."""
    from app.db.models import Answer
    await _get_project(session, project_id, user)
    limit = max(1, min(limit, 50))
    answers = list((await session.scalars(
        select(Answer).where(Answer.project_id == project_id, Answer.kind == "corpus")
        .order_by(Answer.created_at.desc()).limit(limit))).all())
    answers.reverse()
    if not answers:
        return []
    aids = [a.id for a in answers]
    claims = list((await session.scalars(
        select(Claim).where(Claim.answer_id.in_(aids)).order_by(Claim.ordinal))).all())
    cids = [c.id for c in claims]
    ev_by_claim: dict[str, ClaimEvidence] = {}
    for ev in (await session.scalars(
            select(ClaimEvidence).where(ClaimEvidence.claim_id.in_(cids)))).all() if cids else []:
        ev_by_claim.setdefault(ev.claim_id, ev)  # first evidence per claim
    chunk_ids = [ev.chunk_id for ev in ev_by_claim.values()]
    chunks = {c.id: c for c in (await session.scalars(
        select(Chunk).where(Chunk.id.in_(chunk_ids)))).all()} if chunk_ids else {}
    docs = {d.id: d for d in (await session.scalars(
        select(Document).where(Document.id.in_({c.document_id for c in chunks.values()}))
    )).all()} if chunks else {}

    claims_by_answer: dict[str, list[dict]] = {}
    for c in claims:
        ev = ev_by_claim.get(c.id)
        ch = chunks.get(ev.chunk_id) if ev else None
        doc = docs.get(ch.document_id) if ch else None
        claims_by_answer.setdefault(c.answer_id, []).append({
            "id": c.id, "text": c.text,
            "evidence": {
                "chunk_id": ev.chunk_id if ev else "", "document_id": ch.document_id if ch else "",
                "document_title": doc.title if doc else "(removed)",
                "section": ch.section if ch else "", "page_start": ch.page_start if ch else 0,
                "page_end": ch.page_end if ch else 0, "quote": ev.quote if ev else "",
                "quote_char_start": ev.quote_char_start if ev else 0,
                "quote_char_end": ev.quote_char_end if ev else 0,
                "nli_label": ev.nli_label if ev else "", "nli_score": ev.nli_score if ev else 0.0,
                "abstract_only": bool(doc.abstract_only) if doc else False,
                "source_type": doc.source_type if doc else "",
            },
        })
    return [{
        "answer_id": a.id, "question": a.question, "refused": a.refused,
        "refusal_reason": a.refusal_reason, "coverage_note": a.coverage_note,
        "claims": claims_by_answer.get(a.id, []), "technical_context": [],
        "created_at": a.created_at.isoformat(),
    } for a in answers]


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
    # Object-level authz: the claim must belong to a project this user owns.
    # Without this check any authenticated user could read any claim's quote +
    # source chunk by id (broken object-level authorization / IDOR).
    claim = await session.get(Claim, claim_id)
    if claim is None:
        raise NotFoundError("claim not found")
    await _get_project(session, claim.project_id, user)
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
    # Deterministic first: a request that already names its systems, its
    # measurements and its scope does not need a model's opinion on whether it
    # is clear. This is what stops clarification being a mandatory gateway.
    from app.agents.constraints import query_specificity
    specificity, signals = query_specificity(body.query)

    r = await complete_json(
        "clarify_refine",
        f"Research request: {body.query}\n"
        + (f"A deterministic check already rates this request as SPECIFIC "
           f"({', '.join(signals)}). Do not ask clarifying questions.\n"
           if specificity == "specific" else "")
        + "Return: the research domain and academic FIELD; the user's objective; "
        "any CONSTRAINTS in the text (since_year from 'after 2022', "
        "min_citations from 'at least 50 citations', else 0); in_scope = false "
        "when the question is really biomedicine, neuroscience, psychology, "
        "social science, humanities, medicine or law (this platform searches "
        "arXiv + Semantic Scholar for computer-science / engineering researchers "
        "and covers those fields poorly); and `ambiguity`. Leave `questions` "
        "EMPTY unless two materially different research projects would satisfy "
        "the same words — a request that is merely broad is not ambiguous, and "
        "asking about it wastes the researcher's time. Concise.",
        ClarifyResult,
    )
    # Hard override, not a hint. The model reliably volunteers questions even
    # when told not to; the deterministic verdict is the one that decides.
    questions = [] if specificity == "specific" else list(r.questions)
    scope_note = ""
    if not r.in_scope:
        scope_note = (
            f"Heads up — this reads like a {r.field or 'non-CS'} question. "
            "Veriscope's MVP searches arXiv + Semantic Scholar and is built for "
            "computer-science / engineering research; biomedical & social-science "
            "coverage is limited (on the roadmap). You can still run it, but expect "
            "a partial, clearly-flagged result."
        )
    # Deterministic guard: a constraint the query cannot have asked for is not a
    # constraint. Without this the UI shows an invented "≥50 citations · parsed
    # from your question · enforced" chip, and the run silently drops the recent
    # preprints that ARE the literature for most CS questions.
    from app.agents.constraints import scrub_constraints
    since_year, until_year, min_citations, dropped = scrub_constraints(
        body.query, since_year=r.since_year, until_year=r.until_year,
        min_citations=r.min_citations)
    if dropped:
        scope_note = " ".join([scope_note, *(d.capitalize() + "." for d in dropped)]).strip()
    return {"allowed": True, "reason": "", "objective": r.objective,
            "questions": questions, "field": r.field, "in_scope": r.in_scope,
            "ambiguity": specificity if specificity == "specific" else r.ambiguity,
            "scope_note": scope_note, "since_year": since_year,
            "until_year": until_year, "min_citations": min_citations}


class ScreenStart(BaseModel):
    project_id: str
    query: str = Field(min_length=8, max_length=2000)
    since_year: int = Field(default=0, ge=0, le=2100)
    until_year: int = Field(default=0, ge=0, le=2100)
    min_citations: int = Field(default=0, ge=0, le=100000)


@router.post("/screen")
async def screen_endpoint(
    body: ScreenStart,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Pre-run screening: search + rank + recommend keep/drop with reasons, WITHOUT
    ingesting. The UI shows every candidate; the researcher approves what enters
    the corpus, then launches the run with that selection."""
    await _get_project(session, body.project_id, user)
    from app.services.screening import screen_candidates
    return await screen_candidates(
        body.query, since_year=body.since_year, until_year=body.until_year,
        min_citations=body.min_citations)


@router.get("/projects/{project_id}/dashboard")
async def project_dashboard(
    project_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Per-project observability: verification health (trust), cost/tokens,
    latency, retrieval quality, corpus, provider health, and run history. Read
    from the system of record — signals that aren't measured are honest nulls."""
    await _get_project(session, project_id, user)
    from app.services.dashboard import build_dashboard
    return await build_dashboard(session, project_id)


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
    project_id: str, limit: int = _PAGE_DEFAULT, offset: int = 0,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, project_id, user)
    limit, offset = _page(limit, offset)
    rows = (await session.scalars(
        select(SavedClaim).where(SavedClaim.project_id == project_id)
        .order_by(SavedClaim.created_at.desc()).limit(limit).offset(offset)
    )).all()
    if not rows:
        return []
    # Batch-load every claim + evidence + chunk + document for the page in a
    # handful of queries. The previous path was a per-row N+1 (claim + evidence +
    # chunk + document each iteration) — the same fan-out the report payload
    # already fixed.
    claim_ids = [r.claim_id for r in rows]
    claims = {c.id: c for c in (await session.scalars(
        select(Claim).where(Claim.id.in_(claim_ids)))).all()}
    ev_by_claim: dict[str, ClaimEvidence] = {}
    for ev in (await session.scalars(
        select(ClaimEvidence).where(ClaimEvidence.claim_id.in_(claim_ids)))).all():
        ev_by_claim.setdefault(ev.claim_id, ev)  # first evidence row per claim
    chunk_ids = [ev.chunk_id for ev in ev_by_claim.values()]
    chunks = {c.id: c for c in (await session.scalars(
        select(Chunk).where(Chunk.id.in_(chunk_ids)))).all()} if chunk_ids else {}
    doc_ids = {c.document_id for c in chunks.values()}
    docs = {d.id: d for d in (await session.scalars(
        select(Document).where(Document.id.in_(doc_ids)))).all()} if doc_ids else {}

    out = []
    for r in rows:
        claim = claims.get(r.claim_id)
        ev = ev_by_claim.get(r.claim_id)
        doc_title, page, quote = "", 0, ""
        if ev:
            quote = ev.quote
            chunk = chunks.get(ev.chunk_id)
            if chunk:
                page = chunk.page_start
                doc = docs.get(chunk.document_id)
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
    project_id: str, limit: int = _PAGE_DEFAULT, offset: int = 0,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, project_id, user)
    limit, offset = _page(limit, offset)
    rows = (await session.scalars(
        select(Note).where(Note.project_id == project_id)
        .order_by(Note.updated_at.desc()).limit(limit).offset(offset)
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


# ── Cross-session memory ─────────────────────────────────────────────────

@router.get("/projects/{project_id}/memory")
async def memory_list(
    project_id: str, limit: int = _PAGE_DEFAULT, offset: int = 0,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Everything the project remembers across runs (most recent first)."""
    await _get_project(session, project_id, user)
    limit, offset = _page(limit, offset)
    rows = (await session.scalars(
        select(Memory).where(Memory.project_id == project_id)
        .order_by(Memory.created_at.desc()).limit(limit).offset(offset)
    )).all()
    return [{"id": m.id, "kind": m.kind, "text": m.text, "source_ref": m.source_ref,
             "meta": m.meta, "created_at": m.created_at.isoformat()} for m in rows]


@router.get("/projects/{project_id}/memory/recall")
async def memory_recall(
    project_id: str, q: str, k: int = 5,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Semantic recall over the project's memory (embedding when available,
    else keyword+recency). Orientation only — never answer evidence."""
    await _get_project(session, project_id, user)
    if len(q.strip()) < 2:
        raise ValidationFailed("query too short")
    from app.services.memory import recall
    return {"results": await recall(session, project_id, q.strip(), k=max(1, min(k, 20)))}


class MemoryCreate(BaseModel):
    text: str = Field(min_length=3, max_length=2000)
    kind: str = Field(default="preference", pattern="^(episodic|semantic|preference)$")


@router.post("/projects/{project_id}/memory", status_code=201)
async def memory_add(
    project_id: str, body: MemoryCreate,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Add a durable memory by hand (e.g. a research preference or a fact to keep)."""
    await _get_project(session, project_id, user)
    from app.services.memory import remember
    m = await remember(session, project_id, body.kind, body.text, source_ref="manual")
    return {"id": m.id, "kind": m.kind}


# ── Welcome-back / continuity ────────────────────────────────────────────

@router.get("/projects/{project_id}/resume")
async def project_resume(
    project_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Orientation payload shown when a project is opened: unfinished runs,
    what the project last worked on, open gaps, new alerts, next actions."""
    await _get_project(session, project_id, user)
    from app.services.resume import build_resume
    return await build_resume(session, project_id)


@router.post("/runs/{run_id}/cancel", status_code=202)
async def run_cancel(
    run_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Stop an in-flight run.

    Two paths, because a run can be stopped before OR after a worker picks it up:

      * still `queued` — no worker holds it, so it is marked terminal here and
        the flag makes the worker skip it if it claims the job before the queue
        entry drains.
      * already `running` — only the worker can unwind the pipeline safely
        (open sessions, a held inference lock, a half-written checkpoint), so
        the API just raises the flag and returns 202. The worker stops at its
        next cancellation checkpoint — between papers, not between nodes — and
        writes the terminal status itself.

    Deliberately NOT idempotent-silent on a finished run: telling a user we
    stopped something that had already completed would be a lie about what the
    system did, and the report is right there."""
    run = await session.get(Run, run_id)
    if run is None:
        raise NotFoundError("run not found")
    await _get_project(session, run.project_id, user)
    # Idempotent on an already-stopped run: pressing stop twice is not an error.
    # Checked BEFORE the terminal guard, which now includes "cancelled".
    if run.status == "cancelled":
        return {"run_id": run.id, "status": "cancelled"}
    if run.status in _TERMINAL:
        raise ConflictError("this run already finished")

    await redis_store.request_cancel(run_id)
    if run.status == "queued":
        run.status = "cancelled"
        return {"run_id": run.id, "status": "cancelled"}
    # A `running` row with no live worker lock is an ORPHAN: the worker that
    # wrote that status is gone, so nobody will ever read the flag and write the
    # terminal state. Left alone the row sits at `running` for good and the Stop
    # button reads as broken — the "sometimes it doesn't work" case. The lock is
    # heartbeat-renewed, so its absence is a real verdict, not a guess.
    from app.stores.redis_store import publish_progress
    if not await redis_store.run_lock_held(run_id):
        run.status = "cancelled"
        await publish_progress(run_id, {
            "node": run.current_node or "cancelled", "status": "cancelled",
            "kind": "refuse",
            "message": "run stopped by the user (no worker was executing it)"})
        return {"run_id": run.id, "status": "cancelled"}
    # A live worker holds it: it preempts within ~1s and writes the terminal
    # status itself. Publish the intent now so the feed reflects the press
    # immediately rather than at the next poll.
    await publish_progress(run_id, {
        "node": run.current_node or "cancelling", "status": "running",
        "kind": "refuse", "message": "Stopping this run…"})
    return {"run_id": run.id, "status": "cancelling"}


@router.post("/runs/{run_id}/resume", status_code=202)
async def run_resume(
    run_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Re-enqueue a stalled/failed run. execute_run resumes from the last
    checkpoint, so no work already verified is repeated."""
    run = await session.get(Run, run_id)
    if run is None:
        raise NotFoundError("run not found")
    await _get_project(session, run.project_id, user)
    if run.status in _TERMINAL and run.status not in ("failed", "cancelled"):
        raise ConflictError("this run already finished")
    # CLEAR THE STOP FIRST. The cancel flag outlives the run it stopped (it has
    # a TTL, not a lifetime), so resuming without consuming it would re-raise
    # RunCancelled at the very first checkpoint and look like the resume button
    # silently doing nothing.
    await redis_store.clear_cancel(run.id)
    run.status = "queued"
    await redis_store.enqueue_job("run_pipeline", {"run_id": run.id})
    return {"run_id": run.id, "status": "queued"}


# ── Cross-paper comparison ───────────────────────────────────────────────

class CompareRequest(BaseModel):
    document_ids: list[str] = Field(min_length=2, max_length=5)
    dimensions: list[str] = Field(default_factory=list, max_length=6)
    title: str = ""


async def _comparison_docs(session: AsyncSession, comp: Comparison) -> dict:
    docs = {d.id: d for d in (await session.scalars(
        select(Document).where(Document.id.in_(comp.document_ids))
    )).all()}
    return docs


@router.post("/projects/{project_id}/compare", status_code=201)
async def compare_create(
    project_id: str, body: CompareRequest,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, project_id, user)
    from app.services.compare import comparison_dict, compare_documents
    try:
        comp = await compare_documents(
            session, project_id, body.document_ids,
            dimensions=body.dimensions or None, title=body.title,
        )
    except ValueError as exc:
        raise ValidationFailed(str(exc))
    return comparison_dict(comp, await _comparison_docs(session, comp))


@router.get("/projects/{project_id}/comparisons")
async def comparisons_list(
    project_id: str, limit: int = _PAGE_DEFAULT, offset: int = 0,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    await _get_project(session, project_id, user)
    limit, offset = _page(limit, offset)
    rows = (await session.scalars(
        select(Comparison).where(Comparison.project_id == project_id)
        .order_by(Comparison.created_at.desc()).limit(limit).offset(offset)
    )).all()
    return [{
        "id": c.id, "title": c.title, "dimensions": c.dimensions,
        "document_count": len(c.document_ids),
        "include_in_report": c.include_in_report,
        "created_at": c.created_at.isoformat(),
    } for c in rows]


@router.get("/comparisons/{comparison_id}")
async def comparison_get(
    comparison_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    comp = await session.get(Comparison, comparison_id)
    if comp is None:
        raise NotFoundError("comparison not found")
    await _get_project(session, comp.project_id, user)
    from app.services.compare import comparison_dict
    return comparison_dict(comp, await _comparison_docs(session, comp))


@router.post("/comparisons/{comparison_id}/toggle-report")
async def comparison_toggle_report(
    comparison_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Mark a comparison for inclusion in the project's report view."""
    comp = await session.get(Comparison, comparison_id)
    if comp is None:
        raise NotFoundError("comparison not found")
    await _get_project(session, comp.project_id, user)
    comp.include_in_report = not comp.include_in_report
    return {"id": comp.id, "include_in_report": comp.include_in_report}


@router.delete("/comparisons/{comparison_id}")
async def comparison_delete(
    comparison_id: str,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    comp = await session.get(Comparison, comparison_id)
    if comp:
        await _get_project(session, comp.project_id, user)
        await session.delete(comp)
    return {"deleted": True}


@router.get("/projects/{project_id}/recommend")
async def recommend_sources(
    project_id: str, seed: str = "", k: int = 6,
    session: AsyncSession = Depends(get_session), user: str = Depends(current_user),
):
    """Corpus papers similar to a seed set (comma-separated document ids) — the
    researcher decides what to add to a comparison or report."""
    await _get_project(session, project_id, user)
    seed_ids = [s for s in seed.split(",") if s.strip()]
    if not seed_ids:
        return {"recommendations": []}
    from app.services.compare import recommend_related
    recs = await recommend_related(session, project_id, seed_ids, k=max(1, min(k, 12)))
    return {"recommendations": recs}


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


# ── Text-to-speech (audio briefing) ──────────────────────────────────────
# The report read aloud. The SCRIPT is built client-side from gate-verified
# claims only — this endpoint just voices it, so there is no path by which the
# audio can say something the report does not.
#
# Provider is pluggable and currently Gemini TTS. With no key configured the
# endpoint says so plainly and the client falls back to the browser's own
# speech synthesis, which needs no key and works offline. It never returns
# silence or a fake success.

class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    voice: str = Field(default="Kore", max_length=40)


@router.post("/tts")
async def synthesize_speech(
    body: TtsRequest, user: str = Depends(current_user),
):
    settings = get_settings()
    key = settings.gemini_api_key
    if not key:
        # 503, not 500: the feature is unconfigured, not broken. The client
        # reads this and degrades to browser speech rather than erroring at
        # the reader.
        raise ServiceBusyError(
            "Audio narration is not configured on this server — set GEMINI_API_KEY "
            "to enable it. The browser's built-in voice is being used instead.",
            detail={"provider": "gemini", "configured": False},
        )

    import httpx

    model = settings.gemini_tts_model
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent")
    payload = {
        "contents": [{"parts": [{"text": body.text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": body.voice}
                }
            },
        },
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload,
                                     headers={"x-goog-api-key": key})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("tts provider failed", extra={"error": str(exc)[:200]})
        raise ServiceBusyError(
            "The narration service did not respond. The browser's built-in "
            "voice is being used instead.",
            detail={"provider": "gemini"},
        ) from exc

    try:
        part = data["candidates"][0]["content"]["parts"][0]["inlineData"]
        audio_b64, mime = part["data"], part.get("mimeType", "audio/L16;rate=24000")
    except (KeyError, IndexError, TypeError) as exc:
        raise ServiceBusyError(
            "The narration service returned no audio.",
            detail={"provider": "gemini"},
        ) from exc

    return {"audio_base64": audio_b64, "mime_type": mime,
            "characters": len(body.text)}
