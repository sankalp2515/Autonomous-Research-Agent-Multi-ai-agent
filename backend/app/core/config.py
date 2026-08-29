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
    # LangSmith — LangGraph-native tracing + eval datasets. Enabled only when a
    # key is set. Because we run a LangGraph pipeline, setting the LANGCHAIN_*
    # env vars at startup makes every node emit a trace to LangSmith for free;
    # the raw-httpx LLM calls are logged as LangSmith runs from the trace hook so
    # generations show up too. Pick Langfuse OR LangSmith — no need to run both.
    langsmith_api_key: str = ""
    langsmith_project: str = "veriscope"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
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
    # Schema management. True (dev/test default): init_db runs create_all so the
    # app is self-bootstrapping. Set FALSE in production so Alembic is the single
    # source of truth for schema — `alembic upgrade head` runs in the deploy step
    # and init_db never mutates the schema out from under a migration.
    db_auto_create: bool = True

    # Backpressure — shed load gracefully instead of melting the worker pool.
    max_concurrent_runs_per_project: int = 2   # per-project admission cap
    max_queue_depth: int = 200                 # global shed threshold (503 above this)

    # Per-caller API rate limit (requests/min, fixed window). Coarse DoS/abuse
    # guard applied in middleware; keyed on the auth token when present, else IP.
    # Per-caller API rate limit. Raised well above the old 120 because a single
    # active user legitimately generates a lot of requests (runs list polls every
    # ~2.5s, evidence/report fetches, status). 120 was throttling normal use and
    # surfaced as spurious "too many requests". Streaming/status endpoints are
    # exempt from counting in the middleware.
    rate_limit_per_min: int = 900
    # Email (org invites). Optional: if SMTP_HOST is unset, invites are recorded
    # and the link is LOGGED (no send) rather than failing — so the flow works in
    # dev without a mail server. app_base_url builds the link in the email.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "Veriscope <no-reply@veriscope.app>"
    smtp_starttls: bool = True
    app_base_url: str = "http://localhost:8080"

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
    # Voice for the report's audio briefing. Uses the same GEMINI_API_KEY; with
    # no key the /tts endpoint reports itself unconfigured and the client falls
    # back to the browser's own speech synthesis rather than failing.
    gemini_tts_model: str = "gemini-2.5-flash-preview-tts"
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
    # NVIDIA NIM — OpenAI-compatible. Higher RPM than the free fleet; used as a
    # fast, capable tier for draft/chat/query steps once NVIDIA_API_KEY is set.
    nvidia_api_key: str = ""
    nvidia_model: str = "meta/llama-3.3-70b-instruct"
    nvidia_rpm: int = 40
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

    # Verification gate thresholds.
    #
    # CALIBRATION STATUS (see evals/calibrate.py + docs/CALIBRATION.md): these are
    # the operating points the gate ships with. Run the calibration harness in an
    # ML-enabled environment to (re)validate them against the labeled set before
    # trusting the numbers — they were seeded by judgement, not yet by data.
    #
    # nli_entailment_threshold is RESERVED / NOT YET ENFORCED. The gate today
    # rejects contradictions and strong-neutrals but does NOT require a minimum
    # POSITIVE entailment score, so a weakly-entailed claim can pass. calibrate.py
    # reports what enforcing this bar would change; wire it only once the data
    # says the false-reject cost is acceptable.
    nli_entailment_threshold: float = 0.60
    nli_contradiction_threshold: float = 0.40
    # Strong-neutral reject bar: a quote-matched claim whose chunk is judged
    # NEUTRAL this confidently is out-of-context quoting -> fail. Promoted from a
    # hardcoded literal so it is calibratable.
    nli_neutral_reject_threshold: float = 0.85
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

    # ── Evidence matrix (Phase 1) ────────────────────────────────────────
    # Per-paper structured extraction. Each paper costs ONE llm call, so this is
    # the second-biggest cost dial after research_max_papers.
    evidence_max_papers: int = 22
    evidence_chunks_per_paper: int = 8      # legacy single-query window (fallback path)
    evidence_extract_concurrency: int = 8   # papers extracted per wave

    # ── P0-B: dimension-directed retrieval ───────────────────────────────
    # MEASURED FAILURE this replaces: papers average ~63 chunks, extraction read
    # 8 of them chosen by ONE generic objective query, and 31 of 100 matrix cells
    # were empty despite the evidence being in the corpus (e.g. a paper with 16
    # latency-bearing chunks whose latency cell rendered as a silent study).
    #
    # NOT a global top_k increase — that just buys more of the same badly-aimed
    # ranking. Each required dimension runs its own vocabulary-rich search inside
    # the paper, and the per-paper window is allocated round-robin ACROSS
    # dimensions so no axis can starve the others.
    evidence_dimension_retrieval: bool = True   # kill switch -> legacy single-query path
    evidence_chunks_per_dimension: int = 6      # ceiling per axis, before dedup
    evidence_max_chunks_per_paper: int = 24     # total window (was effectively 8)
    # Cross-encoder rerank inside each dimension's candidate set. Local model, no
    # API cost, but it is lock-serialized — turn off if ingest wall-time matters
    # more than per-axis precision.
    evidence_dimension_rerank: bool = True

    # ── P0-C: completeness audit + targeted recovery ─────────────────────
    # After first-pass extraction, every REQUIRED dimension a study did not fill
    # is UNRESOLVED — which is not the same as absent. Recovery re-reads the paper
    # with retrieval aimed at exactly those axes. Batched to ONE call per paper
    # (not one per cell), so a 20-study run costs ~20 calls, not ~60.
    evidence_recovery_enabled: bool = True
    evidence_recovery_max_papers: int = 24
    evidence_recovery_concurrency: int = 8
    # Extra candidate depth for an axis the paper's abstract says it reports
    # (Phase 2b). Additive only — it never shortens another axis's row, so a
    # wrong profile costs a little wasted retrieval, never a starved dimension.
    evidence_profile_bonus_k: int = 3
    # Coverage bar a 'not reported' verdict must clear (below it -> uncertain).
    evidence_absence_min_queries: int = 2
    evidence_absence_min_chunks: int = 4
    # Shared comparison axes. Above this count, one consolidation call merges
    # near-duplicate labels — without it, per-paper wording drift produces a wide,
    # mostly-empty grid (the exact failure this rework set out to remove).
    evidence_max_dimensions: int = 6

    # Pipeline budgets
    # RAISED 60 -> 150: the evidence-matrix pass spends one call per paper
    # (~22) on top of clarify/plan/screen/outline/draft/regen/abstract. At 60
    # the extraction pass alone would have starved drafting and every section
    # would have closed as a budget gap.
    # RAISED 150 -> 200 for P0-C: the recovery pass costs at most one call per
    # study with unresolved required dimensions (~20), plus one schema call. The
    # rest of the P0 rework is retrieval-side and costs no API calls at all.
    run_max_llm_calls: int = 200
    # RAISED 1800 -> 5400. This was calibrated when a run ingested ~10 papers.
    # With a real corpus (28) the ingest alone spends most of 30 minutes, and
    # the LAST sections were closing as "budget exhausted" gaps while only 11 of
    # 150 llm calls had been used - i.e. the report was being truncated by wall
    # clock, not by cost, and the gaps looked like evidence gaps to the reader.
    # Depth is the product; a deep-research run is allowed to take 45-60 min.
    run_max_wall_seconds: int = 5400
    section_max_regens: int = 2
    # Sections are drafted concurrently. Measured at 4 on a 5-6 section outline
    # this turns the pipeline's second-largest block (draft_sections, ~25% of
    # wall time) from N sequential retrieve->draft->gate cycles into ~2 waves.
    # Bounded rather than unlimited because each section can issue up to
    # (1 + section_max_regens) LLM calls, and a wide outline firing them all at
    # once trips provider rate limits — which cost more in retries than the
    # concurrency saves.
    section_draft_concurrency: int = 8
    subquestion_max_replans: int = 1
    # Inference tier (Phase 2). When set (e.g. http://models:8100), embeddings /
    # rerank / NLI are served by a SEPARATE, independently-scalable model service
    # instead of running in-process behind the API's global inference lock. Empty
    # = in-process (unchanged single-node behaviour). The lock still exists inside
    # the model server (torch thread-safety), but it is off the API's hot path so
    # API workers no longer serialize behind each other.
    inference_service_url: str = ""
    inference_service_timeout: float = 120.0
    # Concurrent requests allowed IN FLIGHT to the model tier. The tier
    # serializes internally, so anything above a small number does not add
    # throughput — it only moves the queue from our side to theirs, where every
    # request's wall clock absorbs the whole backlog and the slowest cross
    # `inference_service_timeout` and are thrown away. Keeping a couple in
    # flight hides request latency without building a queue. Raise this only
    # alongside `--scale models=N`.
    inference_max_concurrency: int = 2
    # Texts per /embed call. Keeps a request's duration a function of THIS
    # constant rather than of how long the paper was, so the timeout below
    # means "the tier is wedged", not "this paper had many chunks".
    inference_embed_batch: int = 48
    ingest_max_pdf_mb: int = 50
    # In-flight papers during ingest. Safe to raise above the old 2: all local
    # embedding is serialized behind a single _infer_lock (ml/local_models.py),
    # so extra concurrency only overlaps the I/O-bound download + PDF parse of
    # other papers while one embeds — cutting ingest wall-time without adding
    # inference contention. 4 keeps memory bounded on small infra.
    ingest_pdf_concurrency: int = 8
    # Downloads are I/O-bound and don't touch the inference lock, so they can run
    # at much higher concurrency than parse+embed — overlapping network fetches
    # while parse/embed serialize is the main ingest-latency win.
    ingest_download_concurrency: int = 10
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
    # SAFETY CEILING on how many candidates the screen sees — no longer a
    # "screening window".
    #
    # It used to be 50, and the 257 candidates past it were concatenated back
    # onto the kept set UNSCREENED, where the ingest cap sliced them into the
    # corpus. That is how an AI-alignment review acquired a paper on peripheral
    # artery disease. Nothing unscreened may reach ingest, so the cut has to be
    # high enough that it effectively never binds; a paper beyond it is recorded
    # as an explicit exclusion, not silently promoted.
    screen_max_candidates: int = 400
    # Screening is now BATCHED and concurrent rather than one call over one
    # truncated list: an abstract gets a few tokens of attention when 50 of them
    # share a call, and 300-character truncation cut most abstracts to their
    # first sentence. Smaller batches also mean one bad batch loses 30 papers,
    # not all of them.
    # MEASURED: 30 x 1200 chars is ~10k tokens of abstract in one prompt. On the
    # free fleet (llama-3.3-70b class) that crowded the context enough that one
    # batch failed outright and the rest returned degraded verdicts — a live run
    # rejected 237 of 237 candidates and produced an EMPTY corpus. Sized back to
    # ~4k tokens per batch, which is close to the old single-call prompt that
    # screened acceptably, while still giving each abstract real attention.
    screen_batch_size: int = 15
    screen_batch_concurrency: int = 6
    # Abstracts are passed whole up to this bound (was a flat 300 chars, which
    # cut most abstracts to their first sentence).
    screen_abstract_chars: int = 700
    # Papers ingested per run. MEASURED: each paper costs ~30-45s
    # (download + parse + chunk + embed, serialized behind the inference lock),
    # so this dial is the single biggest driver of wall-clock time.
    # History: 25->40 added ~15min for little gain, then LOWERED to 16 on the
    # theory that depth comes from section_max_per_doc, not corpus size. That
    # conclusion was measured on a POISONED corpus — the screen was discarding
    # every arXiv paper (see _screen_papers), so extra papers were extra noise
    # and of course didn't help. With pool interleaving the marginal paper is
    # now much more likely to be a real one, so this goes back up.
    research_max_papers: int = 28
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

    @property
    def nli_required(self) -> bool:
        """Whether the NLI entailment layer is a HARD requirement (fail closed).

        The gate's truth check is quote-match + NLI entailment. With NLI off, a
        verbatim quote lifted OUT OF CONTEXT still passes — the exact silent
        downgrade the grounding contract (G1/G4) forbids. In production we refuse
        to verify on quote-match alone: the gate raises VerificationUnavailable
        rather than ship a claim it could not fully check. Dev/staging keep the
        soft-skip so the stack runs without torch installed."""
        return self.app_env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
