"""Move every Supabase Auth user into Google Cloud Identity Platform, keeping
each user's id, password and Google link.

WHY THE ID MATTERS. Every project, run, memory and org membership row is owned
by the token's `sub`. A user re-created with a NEW id would sign in to an empty
workspace while their research sat orphaned under the old one. Identity
Platform's import accepts a caller-chosen uid, so each user is imported under
the Supabase UUID they already have, and nothing in Veriscope's database moves.

WHAT IS CARRIED OVER
  uid              auth.users.id (unchanged)
  email            + email_verified from email_confirmed_at
  password         the bcrypt hash Supabase stores, imported with BCRYPT, so
                   users keep their password and no reset email is needed
  Google link      auth.identities rows with provider 'google' become a
                   google.com provider entry, so "Continue with Google" lands
                   on the same account
  disabled         banned users stay unable to sign in
  display name     user_metadata full_name / name
Soft-deleted users (deleted_at set) are skipped.

USAGE
  # 1. read-only: counts, problems, and a report WITHOUT any password hash
  SUPABASE_DB_URL=postgresql://postgres:...@db.<ref>.supabase.co:5432/postgres \\
      python -m scripts.migrate_supabase_users --report migration-report.json
  # 2. import (needs `pip install firebase-admin` and ADC for the target project)
  python -m scripts.migrate_supabase_users --apply --project veriscope-515119

  Re-running is safe: a uid that already exists is reported as an error by
  Identity Platform and the rest of the batch still imports.

Runbook: docs/RUNBOOK.md, "Switching sign-in to Identity Platform".
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

USERS_SQL = """
select u.id::text as id, u.email, u.encrypted_password, u.email_confirmed_at,
       u.raw_user_meta_data, u.banned_until, u.deleted_at, u.is_sso_user
from auth.users u
order by u.created_at
"""
IDENTITIES_SQL = """
select i.user_id::text as user_id, i.provider,
       coalesce(i.provider_id, i.identity_data->>'sub') as provider_uid,
       i.identity_data->>'email' as email
from auth.identities i
"""

# Supabase providers that have a direct Identity Platform equivalent.
_PROVIDER_MAP = {"google": "google.com"}


def _meta(row: dict) -> dict:
    raw = row.get("raw_user_meta_data") or {}
    return json.loads(raw) if isinstance(raw, str) else dict(raw)


def to_import_record(row: dict, identities: list[dict], now: datetime | None = None) -> dict | None:
    """One Supabase user -> the fields of an Identity Platform ImportUserRecord.
    Pure: returns plain data (the hash as bytes) so it is testable without the
    Firebase SDK. None = skip (soft-deleted)."""
    if row.get("deleted_at"):
        return None
    now = now or datetime.now(timezone.utc)
    meta = _meta(row)
    rec: dict = {
        "uid": row["id"],
        "email": (row.get("email") or "").strip().lower() or None,
        "email_verified": bool(row.get("email_confirmed_at")),
        "display_name": (meta.get("full_name") or meta.get("name") or "").strip() or None,
        "disabled": bool(row.get("banned_until") and row["banned_until"] > now),
        "provider_data": [],
        "password_hash": None,
    }
    pw = row.get("encrypted_password") or ""
    if pw.startswith(("$2a$", "$2b$", "$2y$")):
        rec["password_hash"] = pw.encode("utf-8")
    for ident in identities:
        target = _PROVIDER_MAP.get(ident.get("provider") or "")
        if target and ident.get("provider_uid"):
            rec["provider_data"].append({
                "uid": ident["provider_uid"], "provider_id": target,
                "email": (ident.get("email") or rec["email"]),
            })
    return rec


def problems_of(rec: dict, identities: list[dict]) -> list[str]:
    """What the migration cannot carry, per user, so nobody is surprised."""
    out = []
    unmapped = sorted({i.get("provider") for i in identities
                       if i.get("provider") not in _PROVIDER_MAP and i.get("provider") != "email"})
    if unmapped:
        out.append(f"identity providers with no mapping: {', '.join(unmapped)}")
    if not rec["password_hash"] and not rec["provider_data"]:
        out.append("no password and no linked Google identity: the user must use a reset link")
    if rec["email"] is None:
        out.append("no email")
    return out


async def _read(db_url: str) -> tuple[list[dict], dict[str, list[dict]]]:
    import asyncpg
    conn = await asyncpg.connect(db_url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        users = [dict(r) for r in await conn.fetch(USERS_SQL)]
        idents: dict[str, list[dict]] = {}
        for r in await conn.fetch(IDENTITIES_SQL):
            idents.setdefault(r["user_id"], []).append(dict(r))
    finally:
        await conn.close()
    return users, idents


def _apply(records: list[dict], project: str) -> dict:
    import firebase_admin
    from firebase_admin import auth, credentials

    app = firebase_admin.initialize_app(credentials.ApplicationDefault(), {"projectId": project})
    ok, failed = 0, []
    batch: list = []

    def flush(items):
        nonlocal ok
        if not items:
            return
        res = auth.import_users(items, hash_alg=auth.UserImportHash.bcrypt(), app=app)
        ok += res.success_count
        for e in res.errors:
            failed.append({"uid": items[e.index].uid, "reason": str(e.reason)[:200]})

    for r in records:
        batch.append(auth.ImportUserRecord(
            uid=r["uid"], email=r["email"], email_verified=r["email_verified"],
            display_name=r["display_name"], disabled=r["disabled"],
            password_hash=r["password_hash"],
            provider_data=[auth.UserProvider(uid=p["uid"], provider_id=p["provider_id"],
                                             email=p["email"]) for p in r["provider_data"]],
        ))
        if len(batch) == 1000:               # the API's per-call limit
            flush(batch)
            batch = []
    flush(batch)
    return {"imported": ok, "failed": failed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="import (default: read-only report)")
    ap.add_argument("--project", default=os.getenv("IDENTITY_PLATFORM_PROJECT_ID", ""))
    ap.add_argument("--report", help="write a report (never contains password hashes)")
    args = ap.parse_args()
    db_url = os.getenv("SUPABASE_DB_URL", "")
    if not db_url:
        raise SystemExit("set SUPABASE_DB_URL (Supabase: Project Settings -> Database)")

    users, idents = asyncio.run(_read(db_url))
    records, report = [], {"users": len(users), "skipped_deleted": 0, "problems": []}
    for row in users:
        rec = to_import_record(row, idents.get(row["id"], []))
        if rec is None:
            report["skipped_deleted"] += 1
            continue
        records.append(rec)
        for p in problems_of(rec, idents.get(row["id"], [])):
            report["problems"].append({"uid": rec["uid"], "problem": p})
    report.update({
        "to_import": len(records),
        "with_password": sum(1 for r in records if r["password_hash"]),
        "with_google": sum(1 for r in records if r["provider_data"]),
        "email_verified": sum(1 for r in records if r["email_verified"]),
        "disabled": sum(1 for r in records if r["disabled"]),
    })
    print(json.dumps({k: v for k, v in report.items() if k != "problems"}, indent=1))
    print(f"{len(report['problems'])} user(s) with a problem (see --report)")

    if args.apply:
        if not args.project:
            raise SystemExit("--project (or IDENTITY_PLATFORM_PROJECT_ID) is required to import")
        report["result"] = _apply(records, args.project)
        print(json.dumps(report["result"], indent=1)[:2000])
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1, default=str)
    return 1 if args.apply and report["result"]["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
