"""Application error hierarchy.

Every raised error carries a stable machine code (for clients and logs)
and an HTTP status. Internal details never leak to API responses in prod.
"""

from typing import Any


class AppError(Exception):
    code = "app_error"
    status = 500

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class NotFoundError(AppError):
    code = "not_found"
    status = 404


class ValidationFailed(AppError):
    code = "validation_failed"
    status = 422


class AuthError(AppError):
    code = "unauthorized"
    status = 401


class ConflictError(AppError):
    code = "conflict"
    status = 409


class ExternalServiceError(AppError):
    """A dependency (LLM provider, scholarly API, store) failed after retries."""
    code = "external_service_error"
    status = 502


class RateLimitedError(ExternalServiceError):
    code = "rate_limited"
    status = 429


class BudgetExceededError(AppError):
    """A pipeline run hit its hard budget; partial results are still delivered."""
    code = "budget_exceeded"
    status = 200  # not an HTTP failure: the run completes with explicit gaps


class IngestError(AppError):
    code = "ingest_error"
    status = 422


class VerificationUnavailable(AppError):
    """The gate cannot run (e.g. NLI model missing) - we refuse to ship unverified output."""
    code = "verification_unavailable"
    status = 503
