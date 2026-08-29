# Veriscope backend — serves both the API and the worker (same image, different
# command). Build:  docker build -t veriscope-backend ./backend
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Toggle the heavy local-ML stack (torch/sentence-transformers/transformers).
# Default ON so embeddings + the NLI gate work out of the box; set to "0" for a
# lean BM25-only image.
ARG INSTALL_ML=1

# Dependencies FIRST, source LAST — otherwise every code change invalidates the
# install layer and re-downloads ~2GB of Torch. We install against a stub
# package so the editable install resolves, then copy the real source over it.
COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py
# INSTALL_ML toggles the heavy ML stack; OTel is always included so the
# observability profile produces traces out of the box (no-op unless enabled).
RUN pip install --upgrade pip \
    && if [ "$INSTALL_ML" = "1" ]; then pip install -e ".[ml,otel]"; else pip install -e ".[otel]"; fi

# Source changes now rebuild only these cheap layers.
COPY app ./app
COPY evals ./evals
# Migration tooling — shipped so `alembic upgrade head` can run in the container.
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000

# Entrypoint optionally runs migrations (RUN_MIGRATIONS=1) before the CMD.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
# Default command runs the API; the worker overrides CMD (see docker-compose).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
