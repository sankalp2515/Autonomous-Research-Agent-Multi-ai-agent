"""Citation resolver: a reference may be shown to the user only after it
resolves against the corpus or a real-world registry (CrossRef, OpenAlex,
arXiv). Unresolvable references never become Citation rows, and the UI
renders references exclusively from Citation rows."""

import re

import httpx

from app.core.logging import get_logger
from app.core.retry import retry_external

logger = get_logger("citations")

_TIMEOUT = httpx.Timeout(connect=5, read=20, write=10, pool=5)
_ARXIV_ID = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")


@retry_external
async def _get(url: str, **kwargs) -> httpx.Response:
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url, **kwargs)
    resp.raise_for_status()
    return resp


async def resolve_doi(doi: str) -> dict | None:
    doi = doi.strip().removeprefix("https://doi.org/").removeprefix("doi:")
    try:
        resp = await _get(
            f"https://api.crossref.org/works/{doi}",
            headers={"User-Agent": "research-agent/0.1 (mailto:ops@example.com)"},
        )
        msg = resp.json().get("message", {})
        return {
            "identifier": doi,
            "resolver": "crossref",
            "title": (msg.get("title") or [""])[0],
        }
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            # Fall through to OpenAlex - CrossRef doesn't cover everything.
            pass
        else:
            raise
    except httpx.HTTPError:
        logger.warning("crossref unreachable, trying openalex", extra={"doi": doi})
    try:
        resp = await _get(f"https://api.openalex.org/works/doi:{doi}")
        work = resp.json()
        return {"identifier": doi, "resolver": "openalex", "title": work.get("title", "")}
    except httpx.HTTPError:
        return None


async def resolve_arxiv(arxiv_id: str) -> dict | None:
    arxiv_id = arxiv_id.strip().removeprefix("arXiv:")
    if not _ARXIV_ID.match(arxiv_id):
        return None
    try:
        resp = await _get(
            "https://export.arxiv.org/api/query", params={"id_list": arxiv_id, "max_results": 1}
        )
    except httpx.HTTPError:
        return None
    body = resp.text
    if "<entry>" not in body:
        return None
    title_match = re.search(r"<title>(.*?)</title>", body, re.DOTALL)
    # First <title> is the feed title; the entry title follows.
    titles = re.findall(r"<title>(.*?)</title>", body, re.DOTALL)
    title = titles[1].strip() if len(titles) > 1 else (title_match.group(1) if title_match else "")
    return {"identifier": arxiv_id, "resolver": "arxiv", "title": re.sub(r"\s+", " ", title)}


async def resolve(identifier: str, kind: str) -> dict | None:
    """kind: doi | arxiv | url. Returns citation payload or None (= reject)."""
    if kind == "doi":
        return await resolve_doi(identifier)
    if kind == "arxiv":
        return await resolve_arxiv(identifier)
    if kind == "url":
        # URLs from whitelisted fetchers were already fetched successfully;
        # resolution = the fetch itself. Recorded with its source resolver.
        return {"identifier": identifier, "resolver": "tavily", "title": ""}
    return None
