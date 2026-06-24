"""Document dedup: sha256 exact -> DOI/arXiv id -> fuzzy title+authors.

Preprint vs published pairs are LINKED (supersedes_id), never collapsed -
they are different texts and citations must point at the right one.
"""

import hashlib
import re
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document

_WORD = re.compile(r"[a-z0-9]+")
FUZZY_TITLE_THRESHOLD = 0.93


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _norm_title(title: str) -> str:
    return " ".join(_WORD.findall(title.lower()))


def titles_match(a: str, b: str) -> bool:
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= FUZZY_TITLE_THRESHOLD


def _first_author_surname(authors: list) -> str:
    if not authors:
        return ""
    first = str(authors[0])
    return _WORD.findall(first.lower())[-1] if _WORD.findall(first.lower()) else ""


async def find_duplicate(
    session: AsyncSession,
    project_id: str,
    *,
    sha256: str | None = None,
    doi: str | None = None,
    arxiv_id: str | None = None,
    title: str = "",
    authors: list | None = None,
) -> Document | None:
    """Returns the existing document this one duplicates, else None."""
    if sha256:
        row = await session.scalar(
            select(Document).where(Document.project_id == project_id,
                                   Document.sha256 == sha256)
        )
        if row:
            return row
    if doi:
        row = await session.scalar(
            select(Document).where(Document.project_id == project_id,
                                   Document.doi == doi.lower())
        )
        if row:
            return row
    if arxiv_id:
        row = await session.scalar(
            select(Document).where(Document.project_id == project_id,
                                   Document.arxiv_id == arxiv_id)
        )
        if row:
            return row
    if title:
        candidates = (await session.scalars(
            select(Document).where(Document.project_id == project_id)
        )).all()
        surname = _first_author_surname(authors or [])
        for cand in candidates:
            if titles_match(title, cand.title):
                cand_surname = _first_author_surname(cand.authors or [])
                if not surname or not cand_surname or surname == cand_surname:
                    return cand
    return None
