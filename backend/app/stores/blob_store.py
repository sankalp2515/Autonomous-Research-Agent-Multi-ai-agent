"""Device-local paper library: PDF + parsed markdown on disk.

Keyed by a stable paper identity (arXiv id / DOI / external id), so the same
paper is downloaded from the network at most once and reused across runs and
projects. This is the "real library" the user asked for.

Next phase: swap the filesystem for S3 by reimplementing these functions with
the same signatures (callers depend only on this module's interface).
"""

import re
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("library")

_SAFE = re.compile(r"[^a-z0-9._-]+")


def _base() -> Path:
    p = Path(get_settings().library_dir)
    (p / "pdf").mkdir(parents=True, exist_ok=True)
    (p / "md").mkdir(parents=True, exist_ok=True)
    return p


def library_key(*, arxiv_id: str | None = None, doi: str | None = None,
                external_id: str | None = None, sha256: str | None = None) -> str | None:
    """Stable, filesystem-safe key from the best available identifier."""
    raw = None
    if arxiv_id:
        raw = f"arxiv_{arxiv_id}"
    elif doi:
        raw = f"doi_{doi}"
    elif external_id:
        raw = f"ext_{external_id}"
    elif sha256:
        raw = f"sha_{sha256}"
    if not raw:
        return None
    return _SAFE.sub("_", raw.lower()).strip("_")[:120]


def has_pdf(key: str) -> bool:
    return get_settings().library_enabled and (_base() / "pdf" / f"{key}.pdf").exists()


def load_pdf(key: str) -> bytes | None:
    path = _base() / "pdf" / f"{key}.pdf"
    if not path.exists():
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def save_pdf(key: str, data: bytes) -> None:
    if not get_settings().library_enabled:
        return
    try:
        (_base() / "pdf" / f"{key}.pdf").write_bytes(data)
        logger.info("paper saved to library", extra={"key": key, "bytes": len(data)})
    except OSError as exc:
        logger.warning("library save failed", extra={"key": key, "error": str(exc)[:120]})


def save_markdown(key: str, markdown: str) -> None:
    if not get_settings().library_enabled:
        return
    try:
        (_base() / "md" / f"{key}.md").write_text(markdown, encoding="utf-8")
    except OSError:
        pass


def load_markdown(key: str) -> str | None:
    path = _base() / "md" / f"{key}.md"
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None
