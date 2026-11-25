"""Request-edge hardening: body caps, rate-limit identity, probes, auth helpers."""

import json

import pytest
from starlette.requests import Request

from app.core.limits import BodySizeLimit
from app.core.observability import client_ip, rate_limit_subject


# ── body size ──────────────────────────────────────────────────────────────

async def _call(mw, headers, body=b""):
    sent = []
    chunks = [body]

    async def receive():
        return {"type": "http.request", "body": chunks.pop(0) if chunks else b"",
                "more_body": False}

    async def send(msg):
        sent.append(msg)

    scope = {"type": "http", "method": "POST", "path": "/x",
             "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
    await mw(scope, receive, send)
    return sent


async def _echo(scope, receive, send):
    while True:
        m = await receive()
        if not m.get("more_body"):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def test_declared_oversize_upload_is_rejected_before_parsing():
    mw = BodySizeLimit(_echo, max_bytes=1000, json_max_bytes=100)
    sent = await _call(mw, {"content-type": "multipart/form-data; boundary=x",
                            "content-length": "5000"})
    assert sent[0]["status"] == 413
    assert json.loads(sent[1]["body"])["error"] == "payload_too_large"


async def test_json_gets_the_small_cap_and_uploads_the_large_one():
    mw = BodySizeLimit(_echo, max_bytes=1000, json_max_bytes=100)
    j = await _call(mw, {"content-type": "application/json", "content-length": "500"})
    u = await _call(mw, {"content-type": "multipart/form-data; boundary=x",
                         "content-length": "500"}, b"x" * 500)
    assert j[0]["status"] == 413 and u[0]["status"] == 200


async def test_undeclared_streamed_body_is_cut_off_at_the_cap():
    mw = BodySizeLimit(_echo, max_bytes=1000, json_max_bytes=100)
    sent = await _call(mw, {"content-type": "application/json"}, b"x" * 500)
    assert sent[0]["status"] == 413


async def test_limit_is_per_request_not_shared_state():
    mw = BodySizeLimit(_echo, max_bytes=1000, json_max_bytes=100)
    await _call(mw, {"content-type": "application/json", "content-length": "10"})
    up = await _call(mw, {"content-type": "multipart/form-data; boundary=x",
                          "content-length": "900"}, b"x" * 900)
    assert up[0]["status"] == 200


# ── rate-limit identity ────────────────────────────────────────────────────

class _S:
    def __init__(self, **kw):
        self.trust_forwarded_for = kw.get("trust", False)
        self.trusted_proxy_hops = kw.get("hops", 1)
        self.auth_disabled = kw.get("auth_disabled", False)


def _req(headers: dict, client=("203.0.113.9", 1234)) -> Request:
    return Request({"type": "http", "headers": [(k.lower().encode(), v.encode())
                                                for k, v in headers.items()],
                    "client": client})


def test_spoofed_xff_cannot_choose_the_bucket():
    """Proxies APPEND. The left-most entry is whatever the client sent."""
    r = _req({"x-forwarded-for": "1.2.3.4, 198.51.100.7"})
    assert client_ip(r, _S(trust=True, hops=1)) == "198.51.100.7"


def test_two_proxy_hops_pick_the_client_before_the_load_balancer():
    r = _req({"x-forwarded-for": "1.2.3.4, 198.51.100.7, 35.191.0.1"})
    assert client_ip(r, _S(trust=True, hops=2)) == "198.51.100.7"


def test_xff_is_ignored_unless_trusted():
    r = _req({"x-forwarded-for": "1.2.3.4"})
    assert client_ip(r, _S(trust=False)) == "203.0.113.9"


def test_random_bearer_tokens_do_not_buy_fresh_budgets(monkeypatch):
    """The old subject was a hash of ANY bearer string, so a new garbage token
    per request meant no limit at all."""
    import app.api.deps as deps

    def reject(_t):
        raise deps.AuthError("bad")

    monkeypatch.setattr(deps, "_verify", reject)
    a = rate_limit_subject(_req({"authorization": "Bearer aaa"}), _S())
    b = rate_limit_subject(_req({"authorization": "Bearer bbb"}), _S())
    assert a == b == "ip:203.0.113.9"


def test_a_verified_user_gets_their_own_bucket(monkeypatch):
    import app.api.deps as deps
    monkeypatch.setattr(deps, "_verify", lambda _t: {"sub": "user-1"})
    assert rate_limit_subject(_req({"authorization": "Bearer t"}), _S()) == "u:user-1"


# ── auth helpers never trust an unverified token when auth is on ───────────

async def test_email_from_an_unverifiable_token_is_empty_when_auth_is_on(monkeypatch):
    import jwt

    import app.api.deps as deps

    class _Cfg:
        auth_disabled = False

    def reject(_t):
        raise deps.AuthError("bad signature")

    monkeypatch.setattr(deps, "_verify", reject)
    monkeypatch.setattr(deps, "get_settings", lambda: _Cfg())
    forged = jwt.encode({"sub": "x", "email": "victim@example.com"}, "k", algorithm="HS256")
    assert await deps.current_email(f"Bearer {forged}") == ""
    assert await deps.current_name(f"Bearer {forged}") == ""


# ── probes ─────────────────────────────────────────────────────────────────

def test_liveness_checks_no_dependency():
    """A liveness probe that fails on a DB blip restarts every replica at once."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    # No `with`: the lifespan (database bootstrap) is deliberately not run.
    r = TestClient(create_app()).get("/livez")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_readiness_is_503_when_a_dependency_is_down(monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as main
    from app.stores import blob_store, vector_store

    async def down():
        return "pgvector", "down: no db"

    async def ok():
        return "ok"

    monkeypatch.setattr(vector_store, "health", down)
    monkeypatch.setattr(blob_store, "health", ok)
    r = TestClient(main.create_app()).get("/readyz")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded"


@pytest.mark.parametrize("path", ["/readyz", "/health", "/api/health"])
def test_readiness_routes_exist(path):
    # Asked of the app, not of `app.routes`: newer FastAPI puts router objects
    # without a `.path` in that list. A dependency being down here (no DB in
    # unit tests) is a 503, which still proves the route exists; only a 404
    # means it does not.
    from fastapi.testclient import TestClient

    from app.main import create_app
    assert TestClient(create_app()).get(path).status_code != 404
