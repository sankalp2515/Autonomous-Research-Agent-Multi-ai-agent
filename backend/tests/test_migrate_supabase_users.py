"""The Supabase -> Identity Platform user migration keeps what users need.

The one property that cannot break: a user keeps their id, because every row
in Veriscope is owned by it. Then: their password (bcrypt hash carried over),
their Google link, their verification and ban state.
"""

from datetime import datetime, timedelta, timezone

from scripts.migrate_supabase_users import problems_of, to_import_record

NOW = datetime(2026, 11, 25, tzinfo=timezone.utc)
BCRYPT = "$2a$10$abcdefghijklmnopqrstuuOtq3sLc7ZEGr4cR1xwZTq3l3ZV1n5Ky"


def _row(**over):
    base = {"id": "6f1c8d2e-0000-4000-8000-000000000001", "email": "Ada@Lab.edu",
            "encrypted_password": BCRYPT, "email_confirmed_at": NOW,
            "raw_user_meta_data": {"full_name": "Ada Lovelace"},
            "banned_until": None, "deleted_at": None, "is_sso_user": False}
    base.update(over)
    return base


def test_the_user_id_is_preserved_exactly():
    rec = to_import_record(_row(), [], NOW)
    assert rec["uid"] == "6f1c8d2e-0000-4000-8000-000000000001"


def test_password_email_and_name_carry_over():
    rec = to_import_record(_row(), [], NOW)
    assert rec["password_hash"] == BCRYPT.encode()
    assert rec["email"] == "ada@lab.edu" and rec["email_verified"] is True
    assert rec["display_name"] == "Ada Lovelace"


def test_a_google_identity_stays_linked():
    idents = [{"provider": "google", "provider_uid": "1098765", "email": "ada@lab.edu"}]
    rec = to_import_record(_row(encrypted_password=""), idents, NOW)
    assert rec["provider_data"] == [{"uid": "1098765", "provider_id": "google.com",
                                     "email": "ada@lab.edu"}]
    assert problems_of(rec, idents) == []


def test_unconfirmed_banned_and_deleted_users_keep_their_state():
    assert to_import_record(_row(email_confirmed_at=None), [], NOW)["email_verified"] is False
    assert to_import_record(_row(banned_until=NOW + timedelta(days=1)), [], NOW)["disabled"] is True
    assert to_import_record(_row(banned_until=NOW - timedelta(days=1)), [], NOW)["disabled"] is False
    assert to_import_record(_row(deleted_at=NOW), [], NOW) is None


def test_metadata_stored_as_json_text_is_read():
    rec = to_import_record(_row(raw_user_meta_data='{"name": "A. L."}'), [], NOW)
    assert rec["display_name"] == "A. L."


def test_what_cannot_migrate_is_reported_not_dropped():
    rec = to_import_record(_row(encrypted_password=""), [{"provider": "github",
                                                         "provider_uid": "9"}], NOW)
    problems = problems_of(rec, [{"provider": "github", "provider_uid": "9"}])
    assert any("github" in p for p in problems)
    assert any("reset link" in p for p in problems)
