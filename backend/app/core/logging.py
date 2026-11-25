"""Structured logging.

JSON lines in prod (machine-parseable, ships to any log aggregator),
human-readable console format in dev. A request_id contextvar is stamped
onto every record emitted during a request or pipeline run so a single
grep reconstructs the full story of one request.
"""

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
run_id_var: ContextVar[str] = ContextVar("run_id", default="-")

_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message",
}


# ── Secret redaction (defence in depth) ───────────────────────────────────
# The root cause of the one real leak (Gemini's key in the request URL, printed
# by every retry warning) is fixed at the call site. This is the backstop for
# the next one: a credential that reaches a log line through an exception
# message, a third-party logger, or a URL someone formats into `extra`. It runs
# on the FINAL formatted line, so message, extras and tracebacks are all
# covered, and it never raises — a redaction bug must not cost a log line.
_SECRET_PATTERNS = (
    # ?key=… &api_key=… &access_token=… in any URL
    (re.compile(r"(?i)([?&](?:key|api[_-]?key|apikey|access_token|token|"
                r"client_secret|sig|signature)=)[^&\s'\"<>)]+"), r"\1[REDACTED]"),
    # Authorization: Bearer … / "authorization": "Bearer …"
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1[REDACTED]"),
    # x-goog-api-key / x-api-key header values echoed into a message
    (re.compile(r"(?i)((?:x-goog-api-key|x-api-key|api-key)['\"]?\s*[:=]\s*['\"]?)"
                r"[A-Za-z0-9._-]{8,}"), r"\1[REDACTED]"),
    # Google API key shapes, wherever they appear
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "[REDACTED]"),
    (re.compile(r"\bAQ\.[0-9A-Za-z_-]{20,}"), "[REDACTED]"),
    # OpenAI / Anthropic / Groq / OpenRouter style secret keys
    (re.compile(r"\b(?:sk|gsk|sk-or|sk-ant)-[A-Za-z0-9_-]{16,}"), "[REDACTED]"),
)


def redact(text: str) -> str:
    try:
        for pattern, repl in _SECRET_PATTERNS:
            text = pattern.sub(repl, text)
    except Exception:
        pass
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(self._format(record))

    def _format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
            "run_id": run_id_var.get(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(self._format(record))

    def _format(self, record: logging.LogRecord) -> str:
        extras = " ".join(
            f"{k}={v}" for k, v in record.__dict__.items()
            if k not in _RESERVED and not k.startswith("_")
        )
        base = (
            f"{datetime.now().strftime('%H:%M:%S')} "
            f"{record.levelname:<7} [{request_id_var.get()[:8]}] "
            f"{record.name}: {record.getMessage()}"
        )
        if extras:
            base += f"  ({extras})"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else ConsoleFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Quiet noisy third-party loggers; their errors still surface.
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
