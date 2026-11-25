"""Device-local paper library: PDF + parsed markdown on disk.

Keyed by a stable paper identity (arXiv id / DOI / external id), so the same
paper is downloaded from the network at most once and reused across runs and
projects. This is the "real library" the user asked for.

Backends: local filesystem (one node), Google Cloud Storage, or S3-compatible.
Callers depend only on this module's interface.

ASYNC CALLERS MUST USE THE a* FUNCTIONS. The plain functions do blocking
network I/O on the gcs/s3 backends; called from a coroutine they stall the
event loop for the length of a PDF download, and with it every heartbeat that
loop is supposed to send (run lock, job lease). The a* wrappers run them in a
thread.
"""

import asyncio

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


# ── object-store backends ──────────────────────────────────────────────
# Lazily constructed so each SDK is only imported when its backend is enabled.
# Object keys mirror the local layout ({prefix}/pdf/{key}.pdf, {prefix}/md/...).

_s3 = None
_gcs_bucket = None


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


def _gcs():
    global _gcs_bucket
    if _gcs_bucket is None:
        from google.cloud import storage  # lazy: only with blob_backend="gcs"
        _gcs_bucket = storage.Client().bucket(get_settings().gcs_bucket)
    return _gcs_bucket


def _object_key(kind: str, name: str) -> str:
    s = get_settings()
    prefix = s.gcs_prefix if s.blob_backend == "gcs" else s.s3_prefix
    return f"{prefix.strip('/')}/{kind}/{name}"


def _exists(kind: str, name: str) -> bool:
    backend = get_settings().blob_backend
    if backend == "gcs":
        return _gcs().blob(_object_key(kind, name)).exists()
    if backend == "s3":
        from botocore.exceptions import ClientError
        try:
            _s3_client().head_object(Bucket=get_settings().s3_bucket,
                                     Key=_object_key(kind, name))
            return True
        except ClientError:
            return False
    return (_base() / kind / name).exists()


def _get(kind: str, name: str) -> bytes | None:
    backend = get_settings().blob_backend
    try:
        if backend == "gcs":
            from google.api_core.exceptions import NotFound
            try:
                return _gcs().blob(_object_key(kind, name)).download_as_bytes()
            except NotFound:
                return None
        if backend == "s3":
            from botocore.exceptions import ClientError
            try:
                obj = _s3_client().get_object(Bucket=get_settings().s3_bucket,
                                              Key=_object_key(kind, name))
                return obj["Body"].read()
            except ClientError:
                return None
        path = _base() / kind / name
        return path.read_bytes() if path.exists() else None
    except OSError:
        return None


def _put(kind: str, name: str, data: bytes, content_type: str) -> None:
    backend = get_settings().blob_backend
    if backend == "gcs":
        _gcs().blob(_object_key(kind, name)).upload_from_string(
            data, content_type=content_type)
    elif backend == "s3":
        _s3_client().put_object(Bucket=get_settings().s3_bucket,
                                Key=_object_key(kind, name), Body=data,
                                ContentType=content_type)
    else:
        (_base() / kind / name).write_bytes(data)


# ── public interface ────────────────────────────────────────────────────

def has_pdf(key: str) -> bool:
    if not get_settings().library_enabled:
        return False
    try:
        return _exists("pdf", f"{key}.pdf")
    except Exception as exc:
        logger.warning("library lookup failed", extra={"key": key, "error": str(exc)[:120]})
        return False


def load_pdf(key: str) -> bytes | None:
    try:
        return _get("pdf", f"{key}.pdf")
    except Exception as exc:
        logger.warning("library read failed", extra={"key": key, "error": str(exc)[:120]})
        return None


def save_pdf(key: str, data: bytes) -> None:
    if not get_settings().library_enabled:
        return
    try:
        _put("pdf", f"{key}.pdf", data, "application/pdf")
        logger.info("paper saved to library",
                    extra={"key": key, "bytes": len(data), "backend": get_settings().blob_backend})
    except Exception as exc:  # OSError (local) or SDK errors (gcs / s3)
        logger.warning("library save failed", extra={"key": key, "error": str(exc)[:120]})


def save_markdown(key: str, markdown: str) -> None:
    if not get_settings().library_enabled:
        return
    try:
        _put("md", f"{key}.md", markdown.encode("utf-8"), "text/markdown; charset=utf-8")
    except Exception as exc:
        logger.warning("library markdown save failed",
                       extra={"key": key, "error": str(exc)[:120]})


def load_markdown(key: str) -> str | None:
    try:
        raw = _get("md", f"{key}.md")
    except Exception:
        return None
    return raw.decode("utf-8", "ignore") if raw is not None else None


async def ahas_pdf(key: str) -> bool:
    return await asyncio.to_thread(has_pdf, key)


async def aload_pdf(key: str) -> bytes | None:
    return await asyncio.to_thread(load_pdf, key)


async def asave_pdf(key: str, data: bytes) -> None:
    await asyncio.to_thread(save_pdf, key, data)


async def health() -> str:
    """'ok' or 'down: ...' for /readyz. Local backend: the directory exists."""
    def _probe() -> None:
        backend = get_settings().blob_backend
        if backend == "gcs":
            _gcs().reload()  # bucket metadata: proves identity + bucket exist
        elif backend == "s3":
            _s3_client().head_bucket(Bucket=get_settings().s3_bucket)
        else:
            _base()
    try:
        await asyncio.to_thread(_probe)
        return "ok"
    except Exception as exc:
        return f"down: {str(exc)[:80]}"
