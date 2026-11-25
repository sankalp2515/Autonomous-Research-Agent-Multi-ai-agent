"""API dependencies: who is calling.

Tokens come from one of two issuers (settings.resolved_auth_provider):

  identity_platform  Google Cloud Identity Platform. The frontend signs users in
                     with the Firebase Auth SDK and sends the ID token as a
                     Bearer header. Verified per Google's rules for Firebase ID
                     tokens: RS256 against the public securetoken keys,
                     aud == project id, iss == https://securetoken.google.com/<project>,
                     a non-empty `sub`, `auth_time` not in the future, and (when
                     configured) the tenant.
  supabase           the previous provider, kept for the cut-over and rollback:
                     RS256/ES256 against {SUPABASE_URL}/auth/v1/.well-known/jwks.json;
                     HS256 only outside production (legacy projects).

Either way the user id is the token's `sub`, which is what every project, run
and memory row is owned by. scripts/migrate_supabase_users.py imports users into
Identity Platform UNDER THEIR EXISTING ids, so the switch does not orphan data.

The browser API key / publishable key is never used for verification: it is a
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

# Google publishes the keys that sign Identity Platform / Firebase ID tokens here.
IDENTITY_PLATFORM_JWKS_URL = (
    "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com")
_IDP_ISSUER_PREFIX = "https://securetoken.google.com/"

_jwk_clients: dict[str, tuple[PyJWKClient, float]] = {}
_JWKS_TTL = 3600


def _provider(settings) -> str:
    return getattr(settings, "resolved_auth_provider", "") or "identity_platform"


def _jwks_url(settings) -> str:
    if _provider(settings) == "identity_platform":
        return IDENTITY_PLATFORM_JWKS_URL
    if not settings.supabase_url:
        raise AuthError("SUPABASE_URL not configured for JWT verification")
    return f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


def _jwks(settings=None) -> PyJWKClient:
    settings = settings or get_settings()
    url = _jwks_url(settings)
    now = time.time()
    hit = _jwk_clients.get(url)
    if hit is None or now - hit[1] > _JWKS_TTL:
        hit = (PyJWKClient(url, cache_keys=True, lifespan=_JWKS_TTL), now)
        _jwk_clients[url] = hit
    return hit[0]


def _idp_project(settings) -> str:
    pid = (getattr(settings, "identity_platform_project_id", "") or "").strip()
    if not pid:
        raise AuthError("IDENTITY_PLATFORM_PROJECT_ID not configured for JWT verification")
    return pid


def _expected_issuer(settings) -> str:
    """Issuer we require on access tokens."""
    if _provider(settings) == "identity_platform":
        return _IDP_ISSUER_PREFIX + _idp_project(settings)
    if settings.supabase_jwt_issuer:
        return settings.supabase_jwt_issuer.rstrip("/")
    if settings.supabase_url:
        return f"{settings.supabase_url.rstrip('/')}/auth/v1"
    return ""


def _expected_audience(settings) -> str | None:
    if _provider(settings) == "identity_platform":
        return _idp_project(settings)
    return settings.supabase_jwt_audience or None


def _check_identity_platform_claims(payload: dict, settings) -> None:
    """The Firebase ID-token rules PyJWT does not cover on its own."""
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub or len(sub) > 128:
        raise AuthError("token has no valid subject")
    auth_time = payload.get("auth_time")
    if not isinstance(auth_time, (int, float)) or auth_time > time.time() + 60:
        raise AuthError("token auth_time is missing or in the future")
    tenant = (payload.get("firebase") or {}).get("tenant") or ""
    want = (getattr(settings, "identity_platform_tenant_id", "") or "").strip()
    # A tenant token is only acceptable to an API configured for that tenant,
    # and an API configured for a tenant accepts nothing else. Otherwise a user
    # of tenant A could call an API meant for tenant B with a valid token.
    if tenant != want:
        raise AuthError("token tenant does not match this deployment")


def _verify(token: str) -> dict:
    settings = get_settings()
    provider = _provider(settings)
    header = jwt.get_unverified_header(token)
    alg = header.get("alg", "")

    # Claim checks: verify audience and issuer, so a token minted for another
    # project or audience is rejected even if its signature is genuine.
    audience = _expected_audience(settings)
    issuer = _expected_issuer(settings) or None
    kwargs: dict = {"options": {"verify_aud": audience is not None}}
    if audience:
        kwargs["audience"] = audience
    if issuer:
        kwargs["issuer"] = issuer

    try:
        if alg == "HS256":
            if provider == "identity_platform":
                raise AuthError("Identity Platform tokens are RS256; HS256 is refused")
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
        algorithms = ["RS256"] if provider == "identity_platform" else ["RS256", "ES256"]
        signing_key = _jwks(settings).get_signing_key_from_jwt(token)
        payload = jwt.decode(token, signing_key.key, algorithms=algorithms, **kwargs)
        if provider == "identity_platform":
            _check_identity_platform_claims(payload, settings)
        return payload
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
                       "UNVERIFIED subject. Set AUTH_DISABLED=false and configure "
                       "the auth provider before any multi-user use.")
    sub = payload.get("sub") or payload.get("email")
    return sub or "local"


def _claims(token: str) -> dict | None:
    """Verified claims; or, ONLY when auth is disabled (local dev), unverified.

    These helpers used to fall back to an unverified decode whenever
    verification failed - in production too. current_email feeds invitation
    matching, so a forged token naming someone else's email was one missing
    `current_user` dependency away from accepting their invite."""
    try:
        return _verify(token)
    except Exception:
        if get_settings().auth_disabled:
            try:
                return jwt.decode(token, options={"verify_signature": False})
            except jwt.PyJWTError:
                return None
        return None


async def current_name(authorization: str | None = Header(default=None)) -> str:
    """Best-effort display name from the token (name / full_name / email local
    part), or "". Never raises."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return ""
    token = authorization.split(" ", 1)[1]
    try:
        p = _claims(token)
        if p is None:
            return ""
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
        payload = _claims(token)
        if payload is None:
            return ""
        # Identity Platform issues tokens to email/password users BEFORE they
        # verify the address. Matching invitations on an unverified email would
        # let anyone who signs up as someone else's address accept that
        # person's invite, so only a verified email counts. (Google sign-in
        # emails arrive verified.)
        if (_provider(get_settings()) == "identity_platform"
                and payload.get("email_verified") is not True):
            return ""
        return (payload.get("email") or "").strip().lower()
    except jwt.PyJWTError:
        return ""


UserDep = Depends(current_user)
