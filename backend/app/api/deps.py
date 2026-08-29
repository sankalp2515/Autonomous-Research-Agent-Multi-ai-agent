"""API dependencies: Supabase auth.

How verification works (production path):
- The FRONTEND signs users in with supabase-js using SUPABASE_PUBLISHABLE_KEY
  and sends the resulting access token as a Bearer header.
- The BACKEND verifies that token against Supabase's public JWKS endpoint
  ({SUPABASE_URL}/auth/v1/.well-known/jwks.json) - asymmetric (RS256/ES256),
  no shared secret needed, keys cached and refreshed hourly.
- Legacy projects that still sign HS256 tokens can set SUPABASE_JWT_SECRET.

The publishable key is deliberately NOT used for verification - it is a
client identifier, not a signing secret.
"""

import time

import httpx
import jwt
from fastapi import Depends, Header
from jwt import PyJWKClient

from app.core.config import get_settings
from app.core.exceptions import AuthError
from app.core.logging import get_logger

logger = get_logger("auth")

_jwk_client: PyJWKClient | None = None
_jwk_client_at: float = 0.0
_JWKS_TTL = 3600


def _jwks() -> PyJWKClient:
    global _jwk_client, _jwk_client_at
    now = time.time()
    if _jwk_client is None or now - _jwk_client_at > _JWKS_TTL:
        settings = get_settings()
        if not settings.supabase_url:
            raise AuthError("SUPABASE_URL not configured for JWT verification")
        url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        _jwk_client = PyJWKClient(url, cache_keys=True, lifespan=_JWKS_TTL)
        _jwk_client_at = now
    return _jwk_client


def _expected_issuer(settings) -> str:
    """Issuer we require on access tokens. Explicit override wins; otherwise
    derive Supabase's standard issuer from SUPABASE_URL."""
    if settings.supabase_jwt_issuer:
        return settings.supabase_jwt_issuer.rstrip("/")
    if settings.supabase_url:
        return f"{settings.supabase_url.rstrip('/')}/auth/v1"
    return ""


def _verify(token: str) -> dict:
    settings = get_settings()
    header = jwt.get_unverified_header(token)
    alg = header.get("alg", "")

    # Claim checks: verify audience and issuer when configured, so a token
    # minted for a different audience/issuer (even under the same project) is
    # rejected. Signature (below) still binds the token cryptographically; this
    # is defense-in-depth against token reuse across audiences.
    audience = settings.supabase_jwt_audience or None
    issuer = _expected_issuer(settings) or None
    kwargs: dict = {"options": {"verify_aud": audience is not None}}
    if audience:
        kwargs["audience"] = audience
    if issuer:
        kwargs["issuer"] = issuer

    try:
        if alg == "HS256":
            # Reject symmetric tokens in production: HS256 relies on a shared
            # secret whose leak forges any user. Prod must use asymmetric JWKS.
            if settings.app_env == "prod":
                raise AuthError("HS256 tokens are not accepted in production; "
                                "use Supabase asymmetric (RS256/ES256) tokens")
            if not settings.supabase_jwt_secret:
                raise AuthError(
                    "token is HS256 but SUPABASE_JWT_SECRET is not set "
                    "(copy it from Supabase: Project Settings -> API)"
                )
            return jwt.decode(token, settings.supabase_jwt_secret,
                              algorithms=["HS256"], **kwargs)
        signing_key = _jwks().get_signing_key_from_jwt(token)
        return jwt.decode(token, signing_key.key,
                          algorithms=["RS256", "ES256"], **kwargs)
    except AuthError:
        raise
    except (jwt.PyJWTError, httpx.HTTPError) as exc:
        logger.info("token rejected", extra={"reason": str(exc)[:120]})
        raise AuthError("invalid or expired token") from exc


async def user_from_token(token: str | None) -> str:
    """Resolve a user id from a raw access token (no HTTP header).

    Used by the WebSocket run-status endpoint: browser WebSockets can't set an
    Authorization header, so the client sends the bearer token as the first
    socket message — keeping it OUT of the URL (query strings get logged/cached)
    while still verifying it against the same JWKS path as HTTP requests.

    Same isolation rule as current_user: a present token is never collapsed to
    the shared "local" identity, so WS subscribers stay per-user."""
    settings = get_settings()
    if not token:
        if settings.auth_disabled:
            return "local"
        raise AuthError("missing token")
    return await current_user(f"Bearer {token}")


async def current_user(authorization: str | None = Header(default=None)) -> str:
    """Resolve the caller's user id — the tenant key every project/run/memory
    is scoped by.

    CRITICAL isolation rule: a request that carries a bearer token is NEVER
    collapsed to the shared "local" workspace, even when AUTH_DISABLED is set.
    The old behaviour returned "local" for everyone whenever auth was disabled,
    so two different signed-in users (frontend has Supabase, backend has auth
    off) both wrote/read as "local" and saw each other's data. Now:
      - No token + auth disabled  -> "local" (genuine single-user local dev).
      - Token present             -> identity ALWAYS comes from the token.
    """
    settings = get_settings()
    has_token = bool(authorization and authorization.lower().startswith("bearer "))

    if not has_token:
        if settings.auth_disabled:
            return "local"
        raise AuthError("missing bearer token")

    token = authorization.split(" ", 1)[1]

    if not settings.auth_disabled:
        # Strict: signature-verified subject only.
        payload = _verify(token)
        sub = payload.get("sub")
        if not sub:
            raise AuthError("token missing subject")
        return sub

    # Auth disabled but a token was supplied. Keep users ISOLATED rather than
    # merging them into "local". Verify if the backend is configured to; else
    # (dev only — prod refuses auth_disabled at boot) fall back to the token's
    # unverified subject so distinct users stay distinct. Loud, never silent.
    try:
        payload = _verify(token)
    except Exception:
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError:
            logger.warning("undecodable token while auth disabled; using 'local'")
            return "local"
        logger.warning("AUTH_DISABLED but a token was presented — isolating by "
                       "UNVERIFIED subject. Set AUTH_DISABLED=false + Supabase "
                       "JWKS for real verification before any multi-user use.")
    sub = payload.get("sub") or payload.get("email")
    return sub or "local"


async def current_name(authorization: str | None = Header(default=None)) -> str:
    """Best-effort display name from the token (name / full_name / email local
    part), or "". Never raises."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return ""
    token = authorization.split(" ", 1)[1]
    try:
        try:
            p = _verify(token)
        except Exception:
            p = jwt.decode(token, options={"verify_signature": False})
        meta = p.get("user_metadata") or {}
        name = (p.get("name") or meta.get("full_name") or meta.get("name") or "")
        if not name and p.get("email"):
            name = str(p["email"]).split("@")[0]
        return str(name).strip()[:200]
    except jwt.PyJWTError:
        return ""


async def current_email(authorization: str | None = Header(default=None)) -> str:
    """The caller's email from the token (lowercased), or "" if unavailable.
    Used to auto-match pending org invitations. Never raises — a missing email
    simply means no invites can be matched for this request."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return ""
    token = authorization.split(" ", 1)[1]
    try:
        try:
            payload = _verify(token)
        except Exception:
            payload = jwt.decode(token, options={"verify_signature": False})
        return (payload.get("email") or "").strip().lower()
    except jwt.PyJWTError:
        return ""


UserDep = Depends(current_user)
