"""Application configuration.

Single source of truth for all tunables. Values come from the environment
(.env in dev). Nothing else in the codebase reads os.environ directly.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Runtime
    app_env: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # Error tracking + LLM tracing (all optional — enabled only if keys set).
    sentry_dsn: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    # OpenTelemetry distributed tracing (optional; pip install .[otel]).
    # Exports the API->queue->worker->node->provider span tree via OTLP/HTTP.
    otel_enabled: bool = False
    otel_service_name: str = "veriscope-api"
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"

    # System of record
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/research"
    # Connection pool — tune to (workers × in-flight sessions). Defaults suit a
    # single API process; raise proportionally when scaling out horizontally.
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Backpressure — shed load gracefully instead of melting the worker pool.
    max_concurrent_runs_per_project: int = 2   # per-project admission cap
    max_queue_depth: int = 200                 # global shed threshold (503 above this)

    # Auth / Supabase
    auth_disabled: bool = True   # dev convenience; refused at boot when app_env=prod
    supabase_url: str = ""
    # CORS: browser origins allowed to call the API (credentialed). Never "*".
    cors_allow_origins: list[str] = [
        "http://localhost:5173", "http://127.0.0.1:5173",
    ]
    # If set, /metrics requires this token (Bearer or ?token=). Leave empty in
    # dev; set it (or bind /metrics to an internal network) in production.
    metrics_token: str = ""
    # Trust X-Forwarded-For for the client IP (enable ONLY behind a proxy you
    # control, or clients can spoof their rate-limit identity).
    trust_forwarded_for: bool = False
    # Tighter per-subject budget for the expensive pipeline endpoint.
    pipeline_rate_limit_per_min: int = 10
    supabase_publishable_key: str = ""   # frontend sign-in key (not a secret)
    supabase_jwt_secret: str = ""        # legacy HS256 only; JWKS is preferred
    # Access-token claim checks. Supabase signs aud="authenticated" and
    # iss="{SUPABASE_URL}/auth/v1". Leave a value empty to skip that check
    # (e.g. a non-standard provider); both default on when supabase_url is set.
    supabase_jwt_audience: str = "authenticated"
    supabase_jwt_issuer: str = ""        # defaults to {supabase_url}/auth/v1

    # Stores
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "chunks"

    # LLM providers (free tier)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    gemini_rpm: int = 10
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_rpm: int = 25
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_rpm: int = 20
    openrouter_api_key: str = ""
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    openrouter_rpm: int = 15
    huggingface_api_key: str = ""
    llm_cache_ttl_seconds: int = 86_400

    # External sources
    tavily_api_key: str = ""
    github_token: str = ""
    semantic_scholar_api_key: str = ""
    blog_domain_whitelist: list[str] = [
        "huggingface.co", "openai.com", "anthropic.com", "deepmind.google",
        "ai.googleblog.com", "engineering.fb.com", "netflixtechblog.com",
        "eng.uber.com", "blog.research.google", "distill.pub", "thegradient.pub",
    ]

    # Local ML
    ml_embeddings_enabled: bool = True
    ml_rerank_enabled: bool = True
    ml_nli_enabled: bool = True
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    nli_model: str = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
    embedding_dim: int = 384

    # Verification gate thresholds
    nli_entailment_threshold: float = 0.60
    nli_contradiction_threshold: float = 0.40
    quote_fuzzy_threshold: float = 0.92
    # Over-specification guard: fail a claim that names a specific entity (a
    # law, acronym, product, org) absent from its cited source, even if the
    # quote matches and NLI doesn't contradict. Catches "grounded but mis-
    # attributed" claims. Deterministic; disable if too strict for a corpus.
    gate_entity_check_enabled: bool = True

    # ── Source scope ─────────────────────────────────────────────────────
    # TODO(practitioner-sources): GitHub + engineering-blog agents are disabled
    # for now — they complicated the report (evidence-class mixing, extra wall
    # time) for little gain on scholarly questions. The agent code in
    # app/agents/sources.py (search_github/search_blogs) is kept intact; flip
    # this to re-enable the practitioner track end-to-end.
    practitioner_sources_enabled: bool = False
    # TODO(map-citation-edges): reference edges come from the Semantic Scholar
    # references API, which is heavily rate-limited without a key and made the
    # map hang. Similarity edges (local embeddings) are fast and always on; flip
    # this (and ideally set SEMANTIC_SCHOLAR_API_KEY) to add citation edges back.
    map_citation_edges_enabled: bool = False

    # Pipeline budgets
    run_max_llm_calls: int = 60
    run_max_wall_seconds: int = 1800
    section_max_regens: int = 2
    subquestion_max_replans: int = 1
    ingest_max_pdf_mb: int = 50
    ingest_pdf_concurrency: int = 2
    # Device-local paper library (PDF + parsed markdown). Checked before any
    # download so a paper is fetched from the network at most once.
    # Next phase: swap this for S3 by reimplementing app/stores/blob_store.py.
    library_enabled: bool = True
    library_dir: str = "data/library"
    # Blob backend for the paper library. "local" = filesystem (single node);
    # "s3" = shared object store (S3 / MinIO / R2) so multiple API+worker
    # replicas share one library — required for horizontal scaling.
    blob_backend: Literal["local", "s3"] = "local"
    s3_bucket: str = ""
    s3_prefix: str = "library"
    s3_endpoint_url: str = ""            # set for MinIO/R2; empty = real AWS S3
    s3_region: str = ""
    retrieval_top_k: int = 12
    # Per-section drafting: a wider evidence window than a plain lookup, with a
    # per-document cap so each section draws on many papers instead of
    # clustering on one. Directly controls how substantial a report is.
    section_top_k: int = 20
    section_max_per_doc: int = 3
    # Papers ingested per run. MEASURED: each paper costs ~30-45s
    # (download + parse + chunk + embed, serialized behind the inference lock),
    # so this dial is the single biggest driver of wall-clock time.
    # Raising it 25->40 added ~15min for little gain: report depth actually
    # comes from section_max_per_doc + the drafting prompt, not raw corpus
    # size. Kept slightly above the old 25 for headroom, no further.
    # LOWERED to 16: with the practitioner agents off, scholarly depth comes from
    # section_max_per_doc + drafting, and 28 papers dominated the 14-min runs.
    research_max_papers: int = 16
    rrf_k: int = 60
    # Citation-count prior in ranking: small so relevance dominates and
    # citations only break near-ties. 0 disables it.
    citation_weight: float = 0.15
    # Recency prior in ranking. ON BY DEFAULT (data-quality priority): among
    # comparably-relevant passages, newer work ranks higher, so a run that
    # doesn't pick a time window still favors recent evidence over stale.
    # Papers older than `recency_horizon_years` get no recency credit.
    recency_weight: float = 0.20
    recency_horizon_years: int = 15
    # Corpus retention: beyond this many embedded chunks per project, the
    # oldest uncited documents go cold (vectors evicted, rebuildable).
    corpus_max_embedded_chunks: int = 4000


@lru_cache
def get_settings() -> Settings:
    return Settings()
