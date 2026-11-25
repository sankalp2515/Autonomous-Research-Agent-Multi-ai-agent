"""Untrusted PDF fetches: every redirect hop is SSRF-checked; bodies are capped.

PDF URLs come from external records (open-access links, client-selected
papers). The guard used to check only the FIRST hop and httpx followed
redirects by itself, so public -> 302 -> private reached into the VPC; and the
body was fully buffered before its size was checked.
"""

import httpx
import pytest

from app.agents import sources

PDF = b"%PDF-1.7\n" + b"x" * 100


@pytest.fixture
def transport(monkeypatch):
    routes = {}

    def handler(request: httpx.Request) -> httpx.Response:
        return routes[str(request.url)](request)

    real = httpx.AsyncClient

    def client(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return real(*a, **k)

    monkeypatch.setattr(sources.httpx, "AsyncClient", client)
    monkeypatch.setattr(sources, "_is_safe_public_url",
                        lambda url: "internal" not in httpx.URL(url).host)
    return routes


async def test_a_redirect_into_the_private_network_is_refused(transport):
    seen = []
    transport["https://public.example/paper.pdf"] = lambda r: httpx.Response(
        302, headers={"location": "http://internal.local/secret"})

    def internal(r):
        seen.append(r.url)
        return httpx.Response(200, content=PDF)

    transport["http://internal.local/secret"] = internal
    assert await sources.download_pdf("https://public.example/paper.pdf") is None
    assert seen == [], "the private host was contacted"


async def test_a_public_redirect_chain_is_followed(transport):
    transport["https://a.example/p"] = lambda r: httpx.Response(
        301, headers={"location": "https://b.example/p.pdf"})
    transport["https://b.example/p.pdf"] = lambda r: httpx.Response(200, content=PDF)
    assert await sources.download_pdf("https://a.example/p") == PDF


async def test_redirect_loops_stop(transport):
    transport["https://loop.example/a"] = lambda r: httpx.Response(
        302, headers={"location": "https://loop.example/a"})
    assert await sources.download_pdf("https://loop.example/a") is None


async def test_declared_oversize_is_refused_without_reading(transport):
    transport["https://big.example/p.pdf"] = lambda r: httpx.Response(
        200, headers={"content-length": str(10 * 1024 * 1024)}, content=PDF)
    assert await sources.download_pdf("https://big.example/p.pdf", max_mb=1) is None


async def test_undeclared_oversize_is_cut_off_while_streaming(transport):
    big = b"%PDF" + b"x" * (2 * 1024 * 1024)

    def stream(r):
        return httpx.Response(200, stream=httpx.ByteStream(big))

    transport["https://big.example/stream.pdf"] = stream
    assert await sources.download_pdf("https://big.example/stream.pdf", max_mb=1) is None


async def test_non_pdf_content_is_rejected(transport):
    transport["https://x.example/p"] = lambda r: httpx.Response(200, content=b"<html>")
    assert await sources.download_pdf("https://x.example/p") is None
