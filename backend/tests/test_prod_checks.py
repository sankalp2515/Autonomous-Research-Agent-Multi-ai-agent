"""APP_ENV=prod refuses to boot on development settings - every rule pinned."""

import pytest

from app.core.config import Settings
from app.core.prod_checks import check_production_settings, enforce_production_settings


def _good(**over) -> Settings:
    base = dict(
        app_env="prod", auth_disabled=False,
        supabase_url="https://abc.supabase.co",
        cors_allow_origins=["https://app.veriscope.example"],
        db_auto_create=False,
        database_url="postgresql+asyncpg://veriscope:s3cret@10.0.0.5:5432/veriscope",
        redis_url="redis://10.0.0.6:6379/0",
        blob_backend="gcs", gcs_bucket="veriscope-library",
        gemini_api_key="k", metrics_token="m",
        app_base_url="https://app.veriscope.example",
        log_format="json", sentry_dsn="https://x@o.ingest.sentry.io/1",
        trust_forwarded_for=True, smtp_host="smtp.example",
        ml_nli_enabled=True,
    )
    base.update(over)
    return Settings(_env_file=None, **base)


def _errors(s, process="api"):
    return {f.setting for f in check_production_settings(s, process) if f.level == "error"}


def test_a_correct_production_config_has_no_errors():
    assert _errors(_good()) == set()
    enforce_production_settings(_good())  # does not raise


@pytest.mark.parametrize("over,setting", [
    ({"auth_disabled": True}, "AUTH_DISABLED"),
    ({"supabase_url": ""}, "SUPABASE_URL"),
    ({"supabase_url": "http://abc.supabase.co"}, "SUPABASE_URL"),
    ({"cors_allow_origins": ["*"]}, "CORS_ALLOW_ORIGINS"),
    ({"cors_allow_origins": ["http://localhost:5173"]}, "CORS_ALLOW_ORIGINS"),
    ({"cors_allow_origins": ["http://app.example"]}, "CORS_ALLOW_ORIGINS"),
    ({"cors_allow_origins": []}, "CORS_ALLOW_ORIGINS"),
    ({"db_auto_create": True}, "DB_AUTO_CREATE"),
    ({"database_url": "postgresql+asyncpg://postgres:postgres@db:5432/x"}, "DATABASE_URL"),
    ({"database_url": "postgresql+asyncpg://u:p@localhost:5432/x"}, "DATABASE_URL"),
    ({"redis_url": "redis://localhost:6379/0"}, "REDIS_URL"),
    ({"blob_backend": "local"}, "BLOB_BACKEND"),
    ({"gcs_bucket": ""}, "GCS_BUCKET"),
    ({"gemini_api_key": ""}, "LLM providers"),
    ({"ml_nli_enabled": False}, "ML_NLI_ENABLED"),
    ({"metrics_token": ""}, "METRICS_TOKEN"),
    ({"app_base_url": "http://localhost:8080"}, "APP_BASE_URL"),
])
def test_each_development_default_is_refused_in_prod(over, setting):
    assert setting in _errors(_good(**over))


def test_cloud_sql_unix_socket_is_not_mistaken_for_localhost():
    url = ("postgresql+asyncpg://veriscope:pw@/veriscope"
           "?host=/cloudsql/veriscope-515119:asia-south1:veriscope-db")
    assert "DATABASE_URL" not in _errors(_good(database_url=url))


def test_the_worker_does_not_need_a_metrics_token():
    assert "METRICS_TOKEN" not in _errors(_good(metrics_token=""), process="worker")


def test_all_errors_are_reported_at_once():
    with pytest.raises(RuntimeError) as exc:
        enforce_production_settings(_good(auth_disabled=True, db_auto_create=True,
                                          metrics_token=""))
    msg = str(exc.value)
    assert "AUTH_DISABLED" in msg and "DB_AUTO_CREATE" in msg and "METRICS_TOKEN" in msg


def test_dev_is_never_blocked():
    assert enforce_production_settings(_good(app_env="dev", auth_disabled=True)) == []


def test_free_tier_model_that_may_train_on_uploads_is_flagged():
    findings = check_production_settings(
        _good(openrouter_api_key="k", openrouter_model="x/y:free"))
    assert any(f.setting == "OPENROUTER_MODEL" and f.level == "warning" for f in findings)
