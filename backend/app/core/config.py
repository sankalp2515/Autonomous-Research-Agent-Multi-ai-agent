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

    # System of record
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/research"

    # Auth / Supabase
    auth_disabled: bool = True
    supabase_url: str = ""
    supabase_publishable_key: str = ""   # frontend sign-in key (not a secret)
    supabase_jwt_secret: str = ""        # legacy HS256 only; JWKS is preferred

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
    retrieval_top_k: int = 12
    rrf_k: int = 60
    # Citation-count prior in ranking: small so relevance dominates and
    # citations only break near-ties. 0 disables it.
    citation_weight: float = 0.15
    # Corpus retention: beyond this many embedded chunks per project, the
    # oldest uncited documents go cold (vectors evicted, rebuildable).
    corpus_max_embedded_chunks: int = 4000


@lru_cache
def get_settings() -> Settings:
    return Settings()
