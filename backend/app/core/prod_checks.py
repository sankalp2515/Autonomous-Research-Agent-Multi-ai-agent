"""Boot-time refusal to run production on development settings.

Every setting in config.py has a default that makes a laptop work: auth off,
schema auto-created, localhost everywhere, metrics open. Each of those defaults
is a production incident if it survives into a deploy, and none of them fails
loudly on its own - an open /metrics or a localhost CORS list just quietly
works wrong. So in APP_ENV=prod the process checks its own configuration and
refuses to start on an ERROR, listing every problem at once (fixing them one
redeploy at a time is how a launch slips a day).

WARNINGS are logged and do not block: they are legitimate in some topologies
(e.g. metrics scraped over a private network) but should be a decision, not an
accident.

Both the API and the worker call this. tests/test_prod_checks.py pins each rule.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger("prod_checks")

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


@dataclass
class Finding:
    level: str   # "error" | "warning"
    setting: str
    message: str


def _is_local(url: str) -> bool:
    u = (url or "").lower()
    return any(h in u for h in _LOCAL_HOSTS)


def check_production_settings(s: Settings, process: str = "api") -> list[Finding]:
    """Every problem with `s` for a production deploy. Pure; no I/O."""
    out: list[Finding] = []

    def err(setting: str, msg: str) -> None:
        out.append(Finding("error", setting, msg))

    def warn(setting: str, msg: str) -> None:
        out.append(Finding("warning", setting, msg))

    # ── identity & access ──────────────────────────────────────────────────
    if s.auth_disabled:
        err("AUTH_DISABLED", "auth is disabled; every caller would share one workspace")
    if not s.supabase_url:
        err("SUPABASE_URL", "required to verify access tokens (JWKS)")
    elif not s.supabase_url.lower().startswith("https://"):
        err("SUPABASE_URL", "must be https")
    if s.supabase_jwt_secret:
        warn("SUPABASE_JWT_SECRET", "set but unused in prod (HS256 is refused); remove it "
             "so a leaked secret cannot be mistaken for a live one")
    if not s.cors_allow_origins:
        err("CORS_ALLOW_ORIGINS", "empty; the web app could not call the API")
    for origin in s.cors_allow_origins:
        if origin.strip() == "*":
            err("CORS_ALLOW_ORIGINS", "'*' with credentials is never acceptable")
        elif _is_local(origin):
            err("CORS_ALLOW_ORIGINS", f"contains a local origin ({origin})")
        elif not origin.lower().startswith("https://"):
            err("CORS_ALLOW_ORIGINS", f"non-https origin ({origin})")

    # ── data stores ────────────────────────────────────────────────────────
    if s.db_auto_create:
        err("DB_AUTO_CREATE", "must be false; Alembic owns the production schema")
    if _is_local(s.database_url) and "/cloudsql/" not in s.database_url:
        err("DATABASE_URL", "points at localhost")
    if "postgres:postgres@" in s.database_url:
        err("DATABASE_URL", "uses the default postgres/postgres credentials")
    if _is_local(s.redis_url):
        err("REDIS_URL", "points at localhost")
    if s.blob_backend == "local":
        err("BLOB_BACKEND", "'local' writes the paper library to the container "
            "filesystem, which is per-instance and lost on restart; use gcs or s3")
    if s.blob_backend == "gcs" and not s.gcs_bucket:
        err("GCS_BUCKET", "required when BLOB_BACKEND=gcs")
    if s.blob_backend == "s3" and not s.s3_bucket:
        err("S3_BUCKET", "required when BLOB_BACKEND=s3")
    if s.vector_backend == "qdrant" and _is_local(s.qdrant_url):
        err("QDRANT_URL", "vector backend is qdrant but QDRANT_URL is localhost")
    if s.vector_dual_write:
        warn("VECTOR_DUAL_WRITE", "migration aid only; turn off once the cut-over is done")

    # ── models ─────────────────────────────────────────────────────────────
    providers = [s.gemini_api_key, s.groq_api_key, s.deepseek_api_key,
                 s.openrouter_api_key, s.nvidia_api_key]
    if not any(providers) and not s.vertex_project:
        err("LLM providers", "no LLM provider is configured")
    if s.gemini_api_key and not s.vertex_project:
        warn("GEMINI_API_KEY", "AI Studio free-tier keys may use prompts (user papers) "
             "to improve Google's products; production should use VERTEX_PROJECT")
    if s.openrouter_api_key and s.openrouter_model.endswith(":free"):
        warn("OPENROUTER_MODEL", "a ':free' model may retain or train on prompts, "
             "which include user-uploaded papers; check the provider's data policy")
    if not s.ml_nli_enabled:
        err("ML_NLI_ENABLED", "the verification gate needs NLI in production")

    # ── operations ─────────────────────────────────────────────────────────
    if process == "api" and not s.metrics_token:
        err("METRICS_TOKEN", "/metrics would be public; set a token (or scrape over a "
            "private network and set one anyway)")
    if _is_local(s.app_base_url):
        err("APP_BASE_URL", "is localhost; invite emails and share links would point there")
    if s.log_format != "json":
        warn("LOG_FORMAT", "console logs are not parsed by Cloud Logging; use json")
    if not s.sentry_dsn:
        warn("SENTRY_DSN", "no error tracking; unhandled exceptions are only in logs")
    if not s.trust_forwarded_for:
        warn("TRUST_FORWARDED_FOR", "behind Cloud Run / a load balancer every client "
             "shares the proxy's IP, so unauthenticated rate limiting is one bucket")
    if s.smtp_host == "" and process == "worker":
        warn("SMTP_HOST", "invite emails will be logged, not sent")
    return out


def enforce_production_settings(s: Settings, process: str = "api") -> list[Finding]:
    """Raise if APP_ENV=prod and any ERROR finding exists. Logs warnings.
    No-op outside prod."""
    if s.app_env != "prod":
        return []
    findings = check_production_settings(s, process)
    for f in findings:
        if f.level == "warning":
            logger.warning("production config warning",
                           extra={"setting": f.setting, "detail": f.message})
    errors = [f for f in findings if f.level == "error"]
    if errors:
        lines = "\n".join(f"  - {f.setting}: {f.message}" for f in errors)
        raise RuntimeError(
            f"refusing to start {process} with APP_ENV=prod; fix these settings:\n{lines}")
    return findings
