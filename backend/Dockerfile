# Veriscope backend: one image serves the API, the worker, the model tier and
# the migration job (different commands). Build:
#   docker build -t veriscope-backend ./backend
#   docker build --build-arg INSTALL_ML=0 -t veriscope-backend:lean ./backend
#
# Production properties this file is responsible for:
#   * runs as an unprivileged user (uid 10001), never root
#   * CPU-only torch wheels: the default PyPI torch pulls ~2.5GB of CUDA
#     libraries that a CPU container can never use
#   * model weights BAKED INTO THE IMAGE (BAKE_MODELS=1) and the hub set
#     offline at runtime. Downloading ~1GB from Hugging Face on every cold
#     start made each new Cloud Run instance slow to become ready, and
#     rate-limited downloads hung a worker for over ten minutes. A baked
#     image starts the same way every time, with no network dependency.
#   * honours $PORT (Cloud Run sets it) and shuts down gracefully on SIGTERM
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models

WORKDIR /app

# Toggle the heavy local-ML stack (torch/sentence-transformers/transformers).
ARG INSTALL_ML=1
# Bake the three model checkpoints into the image (needs INSTALL_ML=1).
ARG BAKE_MODELS=1

# Dependencies FIRST, source LAST, so a code change rebuilds only the cheap
# layers. Installed against a stub package so the editable install resolves.
COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py
RUN pip install --upgrade pip \
    && if [ "$INSTALL_ML" = "1" ]; then \
         pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.3" \
         && pip install -e ".[ml,otel,gcp]"; \
       else \
         pip install -e ".[otel,gcp]"; \
       fi

# Model weights: their own layer, keyed on the model ids, so they download once
# per model change rather than once per code change. Keep these ids in sync
# with EMBEDDING_MODEL / RERANK_MODEL / NLI_MODEL in app/core/config.py.
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
ARG RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
ARG NLI_MODEL=MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli
RUN if [ "$INSTALL_ML" = "1" ] && [ "$BAKE_MODELS" = "1" ]; then \
      python -c "import sys; \
from sentence_transformers import SentenceTransformer, CrossEncoder; \
from transformers import pipeline; \
SentenceTransformer(sys.argv[1]); CrossEncoder(sys.argv[2]); \
pipeline('text-classification', model=sys.argv[3], top_k=None)" \
        "$EMBEDDING_MODEL" "$RERANK_MODEL" "$NLI_MODEL"; \
    fi

# Source changes now rebuild only these layers.
COPY app ./app
COPY evals ./evals
COPY scripts ./scripts
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

# Unprivileged runtime user. /models stays readable; data/ is the only
# writable path (local library backend, dev only - prod uses GCS).
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/data /models \
    && chown -R app:app /app/data /models
USER 10001:10001

# Offline at runtime when the weights are baked: a missing model must fail at
# boot with a clear error, not silently reach for the network. The compose dev
# stack overrides this so a laptop can still pull models on first use.
ENV HF_HUB_OFFLINE=${BAKE_MODELS} \
    TRANSFORMERS_OFFLINE=${BAKE_MODELS} \
    PORT=8000 \
    APP_VERSION=dev

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os,urllib.request,sys; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/livez', timeout=4); sys.exit(0)" || exit 1

# Entrypoint optionally runs migrations (RUN_MIGRATIONS=1) before the CMD.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
# Default command runs the API. The worker overrides it with
# `python -m app.worker`; the model tier with `uvicorn app.model_server:app`.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --timeout-graceful-shutdown 25 --timeout-keep-alive 75 --no-server-header"]
