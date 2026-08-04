"""Auth verification is a security boundary — test accept AND every reject.

We mint HS256 tokens (symmetric secret, no key infra needed) and drive the
real _verify / current_user code so audience, issuer, expiry, signature and
subject checks are all exercised end to end.
"""

import time
from types import SimpleNamespace

import jwt
import pytest

from app.api import deps
from app.core.exceptions import AuthError

# 32+ bytes: matches a real Supabase JWT secret length (avoids pyjwt's
# short-key warning and keeps the test representative).
SECRET = "test-signing-secret-at-least-32-bytes-long"
ISSUER = "https://proj.supabase.co/auth/v1"


def _settings(**over):
    base = dict(
        app_env="dev",
        auth_disabled=False,
        supabase_jwt_secret=SECRET,
        supabase_jwt_audience="authenticated",
        supabase_jwt_issuer="",
        supabase_url="https://proj.supabase.co",
    )
    base.update(over)
    return SimpleNamespace(**base)


def _token(*, sub="user-123", aud="authenticated", iss=ISSUER,
           exp_delta=3600, secret=SECRET, alg="HS256"):
    now = int(time.time())
    payload = {"sub": sub, "aud": aud, "iss": iss, "iat": now, "exp": now + exp_delta}
    return jwt.encode(payload, secret, algorithm=alg)


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch):
    """Default: standard, well-configured settings. Individual tests override."""
    monkeypatch.setattr(deps, "get_settings", lambda: _settings())


def test_valid_token_accepted():
    payload = deps._verify(_token())
    assert payload["sub"] == "user-123"


def test_expected_issuer_derived_from_supabase_url():
    assert deps._expected_issuer(_settings()) == ISSUER


def test_explicit_issuer_override_wins():
    s = _settings(supabase_jwt_issuer="https://custom.example/auth/")
    assert deps._expected_issuer(s) == "https://custom.example/auth"


def test_wrong_audience_rejected(monkeypatch):
    with pytest.raises(AuthError):
        deps._verify(_token(aud="anon"))


def test_wrong_issuer_rejected():
    # e.g. a token from a different project / missing the /auth/v1 suffix.
    with pytest.raises(AuthError):
        deps._verify(_token(iss="https://proj.supabase.co"))


def test_expired_token_rejected():
    with pytest.raises(AuthError):
        deps._verify(_token(exp_delta=-60))


def test_bad_signature_rejected():
    with pytest.raises(AuthError):
        deps._verify(_token(secret="a-different-attacker-secret-32-bytes-plus"))


def test_audience_check_skippable_when_unconfigured(monkeypatch):
    # Empty audience => aud is not verified (opt-out for non-standard providers).
    monkeypatch.setattr(deps, "get_settings",
                        lambda: _settings(supabase_jwt_audience="", supabase_jwt_issuer="",
                                          supabase_url=""))
    payload = deps._verify(_token(aud="whatever", iss="https://anything"))
    assert payload["sub"] == "user-123"


async def test_current_user_returns_sub_for_valid_bearer():
    sub = await deps.current_user(f"Bearer {_token()}")
    assert sub == "user-123"


async def test_current_user_rejects_missing_header():
    with pytest.raises(AuthError):
        await deps.current_user(None)


async def test_current_user_rejects_non_bearer():
    with pytest.raises(AuthError):
        await deps.current_user(_token())  # no "Bearer " prefix


async def test_current_user_rejects_token_without_subject():
    with pytest.raises(AuthError):
        await deps.current_user(f"Bearer {_token(sub='')}")


async def test_auth_disabled_returns_local(monkeypatch):
    monkeypatch.setattr(deps, "get_settings", lambda: _settings(auth_disabled=True))
    assert await deps.current_user(None) == "local"


def test_hs256_rejected_in_prod(monkeypatch):
    # A valid HS256 token must be refused when app_env=prod (asymmetric only).
    monkeypatch.setattr(deps, "get_settings", lambda: _settings(app_env="prod"))
    with pytest.raises(AuthError):
        deps._verify(_token())
