"""Minimal BibTeX parser (no external dependency).

Extracts the fields we need to fetch or stub a paper: title, authors, year,
DOI, arXiv id, URL, abstract. Brace- and quote-delimited values are handled
with balanced-brace scanning; malformed entries are skipped, not fatal.
"""

import re
from dataclasses import dataclass, field

_ENTRY = re.compile(r"@(\w+)\s*\{", re.IGNORECASE)


@dataclass
class BibEntry:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    url: str = ""
    abstract: str = ""


def _split_entries(text: str) -> list[str]:
    out: list[str] = []
    for m in _ENTRY.finditer(text):
        i = m.end()  # just after the opening '{'
        depth = 1
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        out.append(text[m.start():i])
    return out


def _fields(block: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    # key = {value} | "value" | bareword , at top level of the entry body
    for fm in re.finditer(r"(\w+)\s*=\s*", block):
        key = fm.group(1).lower()
        j = fm.end()
        if j >= len(block):
            continue
        ch = block[j]
        if ch == "{":
            depth, k = 1, j + 1
            start = k
            while k < len(block) and depth:
                if block[k] == "{":
                    depth += 1
                elif block[k] == "}":
                    depth -= 1
                k += 1
            fields[key] = block[start:k - 1]
        elif ch == '"':
            k = j + 1
            start = k
            while k < len(block) and block[k] != '"':
                k += 1
            fields[key] = block[start:k]
        else:
            m = re.match(r"([^,\}\n]+)", block[j:])
            if m:
                fields[key] = m.group(1).strip()
    return fields


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("{", "").replace("}", "")).strip()


_ARXIV = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")


def parse_bibtex(text: str) -> list[BibEntry]:
    entries: list[BibEntry] = []
    for block in _split_entries(text):
        f = _fields(block)
        if not f.get("title"):
            continue
        authors = [_clean(a) for a in re.split(r"\s+and\s+", f.get("author", "")) if a.strip()]
        year_raw = re.search(r"\d{4}", f.get("year", ""))
        arxiv = None
        for src in (f.get("eprint", ""), f.get("arxivid", ""), f.get("url", ""), f.get("doi", "")):
            m = _ARXIV.search(src)
            if m and ("arxiv" in src.lower() or src is f.get("eprint", "") or not arxiv):
                arxiv = m.group(1)
                break
        doi = _clean(f.get("doi", "")) or None
        if doi and "arxiv" in doi.lower():
            doi = None
        entries.append(BibEntry(
            title=_clean(f["title"]),
            authors=authors[:12],
            year=int(year_raw.group()) if year_raw else None,
            doi=doi,
            arxiv_id=arxiv,
            url=_clean(f.get("url", "")),
            abstract=_clean(f.get("abstract", "")),
        ))
    return entries
