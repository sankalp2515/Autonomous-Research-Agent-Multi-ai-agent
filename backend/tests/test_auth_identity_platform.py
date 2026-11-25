"""Identity Platform token verification — every accept and every reject.

Tokens are signed with a throwaway RSA key and verified by the REAL `_verify`,
with only the key lookup (`_jwks`) pointed at that key. So audience, issuer,
algorithm, subject, auth_time, tenant and expiry are all exercised the way a
production Firebase ID token is.
"""

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.api import deps
from app.core.config import Settings
from app.core.exceptions import AuthError

PROJECT = "veriscope-test"
ISSUER = f"https://securetoken.google.com/{PROJECT}"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _settings(**over):
    base = dict(app_env="prod", auth_disabled=False,
                resolved_auth_provider="identity_platform",
                identity_platform_project_id=PROJECT, identity_platform_tenant_id="",
                supabase_url="", supabase_jwt_secret="", supabase_jwt_audience="",
                supabase_jwt_issuer="")
    base.update(over)
    return SimpleNamespace(**base)


def _token(*, sub="uid-123", aud=PROJECT, iss=ISSUER, key=KEY, alg="RS256",
           exp_delta=3600, auth_time_delta=-10, tenant=None, **claims):
    now = int(time.time())
    payload = {"sub": sub, "aud": aud, "iss": iss, "iat": now, "exp": now + exp_delta,
               "auth_time": now + auth_time_delta, **claims}
    if tenant is not None:
        payload["firebase"] = {"sign_in_provider": "password", "tenant": tenant}
    return jwt.encode(payload, key if alg == "RS256" else "x" * 32, algorithm=alg,
                      headers={"kid": "test"})


class _Keys:
    def get_signing_key_from_jwt(self, _token):
        return SimpleNamespace(key=KEY.public_key())


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(deps, "get_settings", lambda: _settings())
    monkeypatch.setattr(deps, "_jwks", lambda settings=None: _Keys())


def test_a_valid_identity_platform_token_is_accepted():
    assert deps._verify(_token())["sub"] == "uid-123"


@pytest.mark.parametrize("bad", [
    {"aud": "some-other-project"},
    {"iss": "https://securetoken.google.com/some-other-project"},
    {"iss": "https://proj.supabase.co/auth/v1"},
    {"key": OTHER_KEY},                       # signed by a key Google does not hold
    {"exp_delta": -10},                       # expired
    {"sub": ""},
    {"auth_time_delta": 3600},                # authenticated in the future
    {"alg": "HS256"},                         # symmetric token, wrong family
])
def test_each_invalid_token_is_rejected(bad):
    with pytest.raises(AuthError):
        deps._verify(_token(**bad))


def test_missing_auth_time_is_rejected():
    now = int(time.time())
    tok = jwt.encode({"sub": "u", "aud": PROJECT, "iss": ISSUER, "iat": now,
                      "exp": now + 60}, KEY, algorithm="RS256")
    with pytest.raises(AuthError):
        deps._verify(tok)


def test_tenant_tokens_only_reach_their_own_deployment(monkeypatch):
    # No tenant configured: a tenant-scoped token is someone else's user pool.
    with pytest.raises(AuthError):
        deps._verify(_token(tenant="lab-a"))
    monkeypatch.setattr(deps, "get_settings", lambda: _settings(identity_platform_tenant_id="lab-a"))
    assert deps._verify(_token(tenant="lab-a"))["sub"] == "uid-123"
    with pytest.raises(AuthError):
        deps._verify(_token(tenant="lab-b"))
    with pytest.raises(AuthError):
        deps._verify(_token())                # project-level token, tenant API


def test_unconfigured_project_fails_closed(monkeypatch):
    monkeypatch.setattr(deps, "get_settings", lambda: _settings(identity_platform_project_id=""))
    with pytest.raises(AuthError):
        deps._verify(_token())


async def test_current_user_is_the_token_subject():
    assert await deps.current_user(f"Bearer {_token(sub='uid-xyz')}") == "uid-xyz"


@pytest.mark.parametrize("claims,expected", [
    ({"email": "Alice@Lab.edu", "email_verified": True}, "alice@lab.edu"),
    ({"email": "alice@lab.edu", "email_verified": False}, ""),
    ({"email": "alice@lab.edu"}, ""),
])
async def test_only_a_verified_email_can_match_invitations(claims, expected):
    """An email/password user gets a token before verifying the address; that
    address must not unlock someone else's invitation."""
    assert await deps.current_email(f"Bearer {_token(**claims)}") == expected


def test_provider_is_inferred_from_configuration():
    assert Settings(_env_file=None, auth_provider="", identity_platform_project_id="p",
                    supabase_url="https://x.supabase.co").resolved_auth_provider == "identity_platform"
    assert Settings(_env_file=None, auth_provider="", identity_platform_project_id="",
                    supabase_url="https://x.supabase.co").resolved_auth_provider == "supabase"
    assert Settings(_env_file=None, auth_provider="supabase", identity_platform_project_id="p",
                    supabase_url="https://x.supabase.co").resolved_auth_provider == "supabase"
    assert Settings(_env_file=None, auth_provider="", identity_platform_project_id="",
                    supabase_url="").resolved_auth_provider == "identity_platform"
