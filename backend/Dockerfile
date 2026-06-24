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

# Install dependencies first for better layer caching.
COPY pyproject.toml ./
COPY app ./app
COPY evals ./evals
RUN pip install --upgrade pip \
    && if [ "$INSTALL_ML" = "1" ]; then pip install -e ".[ml]"; else pip install -e .; fi

EXPOSE 8000

# Default command runs the API; the worker overrides CMD (see docker-compose).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
