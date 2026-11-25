"""API keys never reach the log stream.

Found by the screening benchmark: Gemini's key was sent as `?key=` in the
request URL; httpx puts the URL into every HTTPStatusError message, and both
tenacity's retry logger and the router's failover warning print that message.
Every 503 from Gemini logged a live key. Two fixes, two tests:
  * the key travels in a header, so the URL never carries it;
  * both formatters redact credential shapes on the final line (backstop).
"""

import io
import json
import logging

import httpx
import pytest

from app.core import logging as applog
from app.llm import clients

FAKE_KEY = "AIza" + "x" * 35


async def test_gemini_key_is_sent_as_a_header_not_in_the_url(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["header"] = request.headers.get("x-goog-api-key")
        return httpx.Response(503, text="overloaded")

    real = httpx.AsyncClient
    monkeypatch.setattr(clients.httpx, "AsyncClient",
                        lambda *a, **k: real(*a, **{**k, "transport": httpx.MockTransport(handler)}))
    with pytest.raises(httpx.HTTPStatusError) as err:
        await clients._call_gemini.__wrapped__(FAKE_KEY, "hi", system="", temperature=0,
                                               max_tokens=8)
    assert seen["header"] == FAKE_KEY
    assert FAKE_KEY not in seen["url"]
    assert FAKE_KEY not in str(err.value), "the error message a retry logger prints"


@pytest.mark.parametrize("fmt", ["json", "console"])
@pytest.mark.parametrize("secret_line", [
    f"Server error '503' for url 'https://x.googleapis.com/v1/m:gen?key={FAKE_KEY}'",
    "GET https://api.example.com/v1?api_key=abcd1234efgh5678&x=1",
    "headers={'Authorization': 'Bearer abcdefghijklmnop.qrs'}",
    "x-goog-api-key: abcdefgh12345678",
    "invalid key gsk-" + "a" * 20,
    "key AQ.FAKEfakeFAKEfakeFAKEfakeFAKEfake0123456789",
])
def test_formatters_redact_credentials_everywhere_on_the_line(fmt, secret_line):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(applog.JsonFormatter() if fmt == "json" else applog.ConsoleFormatter())
    log = logging.getLogger(f"redaction-test-{fmt}")
    log.handlers[:] = [handler]
    log.propagate = False
    log.warning("provider failed: %s", secret_line, extra={"error": secret_line})
    try:
        raise RuntimeError(secret_line)
    except RuntimeError:
        log.exception("with traceback")
    out = stream.getvalue()
    assert "[REDACTED]" in out
    for token in ("x" * 35, "abcd1234efgh5678", "abcdefghijklmnop", "abcdefgh12345678",
                  "a" * 20, "FAKEfakeFAKEfakeFAKEfakeFAKEfake0123456789"):
        if token in secret_line:
            assert token not in out
    if fmt == "json":
        for line in out.strip().splitlines():
            if line.startswith("{"):
                json.loads(line)          # redaction must not break the JSON


def test_redaction_leaves_ordinary_text_alone():
    text = "screened 304 records; key finding: recall 48.1% (keyboard=1)"
    assert applog.redact(text) == text


# ── Multi-part answers (found by the same benchmark) ──────────────────────
# Gemini returned one answer split across parts ([4946, 37] chars) with
# finishReason=STOP; the client read parts[0] only, so the JSON was cut off and
# the repair rebuilt a partial list. Vertex shares the parser and the bug.

def _mock(monkeypatch, body: dict):
    real = httpx.AsyncClient
    monkeypatch.setattr(clients.httpx, "AsyncClient", lambda *a, **k: real(
        *a, **{**k, "transport": httpx.MockTransport(lambda r: httpx.Response(200, json=body))}))


async def test_a_split_gemini_answer_is_joined(monkeypatch):
    _mock(monkeypatch, {"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"text": '{"papers": [{"index": 0, "re'}, {"text": 'levant": true}]}'}]}}]})
    r = await clients._call_gemini.__wrapped__(FAKE_KEY, "p", system="", temperature=0,
                                               max_tokens=8)
    assert json.loads(r.text) == {"papers": [{"index": 0, "relevant": True}]}


async def test_thought_parts_are_not_part_of_the_answer(monkeypatch):
    _mock(monkeypatch, {"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"text": "let me think about this", "thought": True}, {"text": '{"ok": 1}'}]}}]})
    r = await clients._call_gemini.__wrapped__(FAKE_KEY, "p", system="", temperature=0,
                                               max_tokens=8)
    assert r.text == '{"ok": 1}'


def test_vertex_uses_the_same_parser():
    body = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"text": "a"}, {"text": "b"}]}}]}
    assert clients._gemini_answer_text(body, "vertex", 8) == "ab"


def test_an_empty_answer_is_an_error_not_an_empty_string():
    from app.core.exceptions import ExternalServiceError
    with pytest.raises(ExternalServiceError):
        clients._gemini_answer_text(
            {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}, "gemini", 8)
