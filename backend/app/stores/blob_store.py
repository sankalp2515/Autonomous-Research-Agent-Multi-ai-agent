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


# ── S3 backend (shared library across replicas) ──────────────────────────
# Lazily constructed so boto3 is only needed when blob_backend="s3". Object
# keys mirror the local layout ({prefix}/pdf/{key}.pdf, {prefix}/md/{key}.md).

_s3 = None


def _s3_client():
    global _s3
    if _s3 is None:
        import boto3  # lazy: only required when the s3 backend is enabled
        s = get_settings()
        kwargs: dict = {}
        if s.s3_endpoint_url:
            kwargs["endpoint_url"] = s.s3_endpoint_url
        if s.s3_region:
            kwargs["region_name"] = s.s3_region
        _s3 = boto3.client("s3", **kwargs)
    return _s3


def _s3_key(kind: str, key: str) -> str:
    return f"{get_settings().s3_prefix.strip('/')}/{kind}/{key}"


def _use_s3() -> bool:
    return get_settings().blob_backend == "s3"


def has_pdf(key: str) -> bool:
    if not get_settings().library_enabled:
        return False
    if _use_s3():
        from botocore.exceptions import ClientError
        try:
            _s3_client().head_object(Bucket=get_settings().s3_bucket,
                                     Key=_s3_key("pdf", f"{key}.pdf"))
            return True
        except ClientError:
            return False
    return (_base() / "pdf" / f"{key}.pdf").exists()


def load_pdf(key: str) -> bytes | None:
    if _use_s3():
        from botocore.exceptions import ClientError
        try:
            obj = _s3_client().get_object(Bucket=get_settings().s3_bucket,
                                          Key=_s3_key("pdf", f"{key}.pdf"))
            return obj["Body"].read()
        except ClientError:
            return None
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
        if _use_s3():
            _s3_client().put_object(Bucket=get_settings().s3_bucket,
                                    Key=_s3_key("pdf", f"{key}.pdf"), Body=data)
        else:
            (_base() / "pdf" / f"{key}.pdf").write_bytes(data)
        logger.info("paper saved to library",
                    extra={"key": key, "bytes": len(data), "backend": get_settings().blob_backend})
    except Exception as exc:  # OSError (local) or ClientError (s3)
        logger.warning("library save failed", extra={"key": key, "error": str(exc)[:120]})


def save_markdown(key: str, markdown: str) -> None:
    if not get_settings().library_enabled:
        return
    try:
        if _use_s3():
            _s3_client().put_object(Bucket=get_settings().s3_bucket,
                                    Key=_s3_key("md", f"{key}.md"),
                                    Body=markdown.encode("utf-8"))
        else:
            (_base() / "md" / f"{key}.md").write_text(markdown, encoding="utf-8")
    except Exception:
        pass


def load_markdown(key: str) -> str | None:
    if _use_s3():
        from botocore.exceptions import ClientError
        try:
            obj = _s3_client().get_object(Bucket=get_settings().s3_bucket,
                                          Key=_s3_key("md", f"{key}.md"))
            return obj["Body"].read().decode("utf-8", "ignore")
        except ClientError:
            return None
    path = _base() / "md" / f"{key}.md"
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None
