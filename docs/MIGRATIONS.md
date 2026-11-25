# Database migrations (Alembic)

Veriscope now uses **Alembic** for versioned schema changes. This replaces the
old "just run `create_all` on boot" approach, which could create new tables but
**could not alter existing columns** — the #1 production-launch blocker.

## Schema ownership

Controlled by `DB_AUTO_CREATE`:

| Env | `DB_AUTO_CREATE` | Who owns the schema |
|-----|------------------|---------------------|
| dev / tests | `true` (default) | `init_db()` runs `create_all` — self-bootstrapping. |
| **production** | **`false`** | **Alembic.** `alembic upgrade head` runs in deploy; `init_db()` only checks connectivity + hot indexes. |

## First-time adoption

Both fresh and existing databases use the same command — the baseline runs
`create_all(checkfirst=True)` (adds only missing tables) and later migrations are
written idempotently, so upgrading is always safe:

```bash
cd backend
alembic upgrade head
```

This creates anything missing and applies real `ALTER`s (e.g. the tenancy
migration adds `projects.org_id` and backfills a personal org per legacy owner).

> Only use `alembic stamp <rev>` if you are certain the live schema already
> matches that revision exactly — it records the revision as applied **without
> running it**, which would skip column adds/backfills.

## Everyday workflow (making a schema change)

1. Edit the models in `app/db/models.py`.
2. Autogenerate the delta and **review it** (autogenerate is a draft, not gospel):
   ```bash
   alembic revision --autogenerate -m "add share_links.expires_at"
   ```
3. Apply it:
   ```bash
   alembic upgrade head
   ```

## In containers

The image ships `alembic.ini` + `alembic/` and an entrypoint that runs
migrations when `RUN_MIGRATIONS=1`. In production, set that on exactly one
service (the API, or a dedicated migrate job) together with `DB_AUTO_CREATE=false`:

```yaml
environment:
  DB_AUTO_CREATE: "false"
  RUN_MIGRATIONS: "1"
```

## Notes

- `env.py` pulls both the URL (`DATABASE_URL`) and the target metadata from the
  app itself, so migrations always match the running models. It runs async
  (asyncpg) online and supports `--sql` offline for review.
- The baseline (`0001_baseline`) is intentionally **not** downgradable.
