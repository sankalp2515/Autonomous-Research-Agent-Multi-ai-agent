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


def _verify(token: str) -> dict:
    settings = get_settings()
    header = jwt.get_unverified_header(token)
    alg = header.get("alg", "")
    options = {"verify_aud": False}
    try:
        if alg == "HS256":
            if not settings.supabase_jwt_secret:
                raise AuthError(
                    "token is HS256 but SUPABASE_JWT_SECRET is not set "
                    "(copy it from Supabase: Project Settings -> API)"
                )
            return jwt.decode(token, settings.supabase_jwt_secret,
                              algorithms=["HS256"], options=options)
        signing_key = _jwks().get_signing_key_from_jwt(token)
        return jwt.decode(token, signing_key.key,
                          algorithms=["RS256", "ES256"], options=options)
    except AuthError:
        raise
    except (jwt.PyJWTError, httpx.HTTPError) as exc:
        logger.info("token rejected", extra={"reason": str(exc)[:120]})
        raise AuthError("invalid or expired token") from exc


async def current_user(authorization: str | None = Header(default=None)) -> str:
    """Returns the authenticated user id ('local' when AUTH_DISABLED)."""
    settings = get_settings()
    if settings.auth_disabled:
        return "local"
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("missing bearer token")
    payload = _verify(authorization.split(" ", 1)[1])
    sub = payload.get("sub")
    if not sub:
        raise AuthError("token missing subject")
    return sub


UserDep = Depends(current_user)
