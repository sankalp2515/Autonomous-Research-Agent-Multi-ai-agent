"""External research sources: arXiv, Semantic Scholar, GitHub, Tavily.

All fetchers: httpx + retry, graceful degradation (a failed source returns
[] and is reported as a coverage gap - it never sinks the run), and
explicit honesty about abstract-only results.
"""

import asyncio
import re
from dataclasses import dataclass, field

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.retry import retry_external

logger = get_logger("sources")

_TIMEOUT = httpx.Timeout(connect=10, read=45, write=15, pool=10)


@dataclass
class PaperHit:
    source: str                 # arxiv | semantic_scholar
    external_id: str
    title: str
    abstract: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    url: str = ""
    pdf_url: str = ""
    doi: str | None = None
    arxiv_id: str | None = None
    citation_count: int = 0
    venue: str = ""


@dataclass
class RepoHit:
    full_name: str
    description: str
    url: str
    stars: int
    readme: str = ""


@dataclass
class BlogHit:
    title: str
    url: str
    content: str
    domain: str = ""


@retry_external
async def _get(url: str, **kwargs) -> httpx.Response:
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url, **kwargs)
    resp.raise_for_status()
    return resp


@retry_external
async def _post(url: str, **kwargs) -> httpx.Response:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, **kwargs)
    resp.raise_for_status()
    return resp


# ── arXiv ────────────────────────────────────────────────────────────────

_ARXIV_ENTRY = re.compile(r"<entry>(.*?)</entry>", re.DOTALL)


def _xml_field(blob: str, tag: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", blob, re.DOTALL)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


async def search_arxiv(query: str, max_results: int = 15,
                       sort_by: str = "relevance",
                       since_year: int | None = None) -> list[PaperHit]:
    # Apply the time window at SEARCH time, not just at retrieval: every paper
    # we fetch costs a PDF download + parse + embed (~30-45s each), so filtering
    # after ingest burns minutes on documents we then discard.
    search_query = f"all:{query}"
    if since_year:
        search_query += f" AND submittedDate:[{since_year}01010000 TO 999912312359]"
    try:
        resp = await _get(
            "https://export.arxiv.org/api/query",
            params={"search_query": search_query, "max_results": max_results,
                    "sortBy": sort_by, "sortOrder": "descending"},
        )
    except httpx.HTTPError:
        logger.warning("arxiv search failed", extra={"query": query[:80]})
        return []
    hits: list[PaperHit] = []
    for entry in _ARXIV_ENTRY.findall(resp.text):
        raw_id = _xml_field(entry, "id")
        arxiv_id = raw_id.rsplit("/abs/", 1)[-1].split("v")[0] if "/abs/" in raw_id else ""
        published = _xml_field(entry, "published")
        year = int(published[:4]) if published[:4].isdigit() else None
        authors = re.findall(r"<name>(.*?)</name>", entry)
        hits.append(PaperHit(
            source="arxiv", external_id=arxiv_id, arxiv_id=arxiv_id,
            title=_xml_field(entry, "title"), abstract=_xml_field(entry, "summary"),
            authors=authors, year=year, url=raw_id,
            pdf_url=f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else "",
        ))
    return hits


# ── Semantic Scholar ─────────────────────────────────────────────────────

async def search_semantic_scholar(query: str, max_results: int = 15,
                                  since_year: int | None = None) -> list[PaperHit]:
    settings = get_settings()
    headers = {}
    if settings.semantic_scholar_api_key:
        headers["x-api-key"] = settings.semantic_scholar_api_key
    params: dict = {
        "query": query, "limit": max_results,
        "fields": "title,abstract,year,authors,externalIds,openAccessPdf,url,"
                  "citationCount,venue",
    }
    if since_year:
        params["year"] = f"{since_year}-"   # S2 open-ended range, e.g. "2021-"
    try:
        resp = await _get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params=params,
            headers=headers,
        )
    except httpx.HTTPError:
        logger.warning("semantic scholar search failed", extra={"query": query[:80]})
        return []
    hits: list[PaperHit] = []
    for row in resp.json().get("data", []) or []:
        ext = row.get("externalIds") or {}
        pdf = (row.get("openAccessPdf") or {}).get("url", "")
        arxiv_id = ext.get("ArXiv")
        # arXiv fallback: when S2 has no open-access PDF but knows the arXiv
        # id, fetch the full text from arXiv directly.
        if not pdf and arxiv_id:
            pdf = f"https://arxiv.org/pdf/{arxiv_id}"
        hits.append(PaperHit(
            source="semantic_scholar", external_id=row.get("paperId", ""),
            title=row.get("title", "") or "", abstract=row.get("abstract") or "",
            authors=[a.get("name", "") for a in row.get("authors", [])],
            year=row.get("year"), url=row.get("url", "") or "", pdf_url=pdf or "",
            doi=ext.get("DOI"), arxiv_id=arxiv_id,
            citation_count=row.get("citationCount") or 0, venue=row.get("venue") or "",
        ))
    return hits


async def fetch_references(s2_id: str, max_refs: int = 80) -> list[dict]:
    """References cited by a paper. s2_id like 'ARXIV:2401.12345' or 'DOI:10..'.
    Returns each referenced paper's externalIds ({ArXiv, DOI, ...}). Best-effort."""
    settings = get_settings()
    headers = {}
    if settings.semantic_scholar_api_key:
        headers["x-api-key"] = settings.semantic_scholar_api_key
    try:
        resp = await _get(
            f"https://api.semanticscholar.org/graph/v1/paper/{s2_id}/references",
            params={"fields": "externalIds", "limit": max_refs}, headers=headers,
        )
    except httpx.HTTPError:
        return []
    out = []
    for row in resp.json().get("data", []) or []:
        ext = (row.get("citedPaper") or {}).get("externalIds") or {}
        if ext:
            out.append(ext)
    return out


def _is_safe_public_url(url: str) -> bool:
    """SSRF guard: only http(s) to a host that resolves to public IPs. Blocks
    fetches to loopback / private / link-local / reserved ranges (e.g. the
    cloud metadata endpoint 169.254.169.254) even when the URL comes from an
    external record we don't fully trust."""
    import ipaddress
    import socket
    from urllib.parse import urlparse

    try:
        parts = urlparse(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443)
    except OSError:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


async def download_pdf(url: str, *, max_mb: int = 50) -> bytes | None:
    # SSRF check before dialing out. (Residual: a redirect to a private host is
    # still followed by httpx; production should also pin an egress allowlist /
    # disable auto-redirect for untrusted fetches.)
    if not await asyncio.to_thread(_is_safe_public_url, url):
        logger.warning("blocked non-public PDF url", extra={"url": url[:120]})
        return None
    try:
        resp = await _get(url)
    except httpx.HTTPError:
        return None
    data = resp.content
    if len(data) > max_mb * 1024 * 1024 or not data.startswith(b"%PDF"):
        return None
    return data


# ── GitHub ───────────────────────────────────────────────────────────────

async def search_github(query: str, max_results: int = 8) -> list[RepoHit]:
    settings = get_settings()
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    try:
        resp = await _get(
            "https://api.github.com/search/repositories",
            params={"q": query, "sort": "stars", "per_page": max_results},
            headers=headers,
        )
    except httpx.HTTPError:
        logger.warning("github search failed", extra={"query": query[:80]})
        return []
    hits: list[RepoHit] = []
    for row in resp.json().get("items", []):
        hits.append(RepoHit(
            full_name=row.get("full_name", ""), description=row.get("description") or "",
            url=row.get("html_url", ""), stars=row.get("stargazers_count", 0),
        ))
    # READMEs in parallel; a missing README is fine.
    async def fetch_readme(hit: RepoHit) -> None:
        try:
            r = await _get(
                f"https://api.github.com/repos/{hit.full_name}/readme",
                headers={**headers, "Accept": "application/vnd.github.raw+json"},
            )
            hit.readme = r.text[:20_000]
        except httpx.HTTPError:
            pass
    await asyncio.gather(*(fetch_readme(h) for h in hits))
    return hits


# ── Tavily (whitelisted blogs) ───────────────────────────────────────────

async def search_blogs(query: str, max_results: int = 6) -> list[BlogHit]:
    settings = get_settings()
    if not settings.tavily_api_key:
        logger.info("tavily not configured; blog agent disabled")
        return []
    try:
        resp = await _post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.tavily_api_key, "query": query,
                "max_results": max_results, "include_raw_content": True,
                "include_domains": settings.blog_domain_whitelist,
            },
        )
    except httpx.HTTPError:
        logger.warning("tavily search failed", extra={"query": query[:80]})
        return []
    hits: list[BlogHit] = []
    for row in resp.json().get("results", []):
        url = row.get("url", "")
        domain = url.split("/")[2] if url.startswith("http") else ""
        content = (row.get("raw_content") or row.get("content") or "")[:30_000]
        if content:
            hits.append(BlogHit(title=row.get("title", ""), url=url,
                                content=content, domain=domain))
    return hits
