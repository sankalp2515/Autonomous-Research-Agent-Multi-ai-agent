"""Retry policies.

One place defines how the system retries, so behavior is uniform and
tunable. External I/O gets exponential backoff with jitter; rate limits
get longer waits; nothing retries forever.
"""

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
    before_sleep_log,
)
import logging

from app.core.exceptions import RateLimitedError

logger = logging.getLogger("retry")


def _is_retryable_http(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout,
                        httpx.PoolTimeout, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    if isinstance(exc, RateLimitedError):
        return True
    return False


# External HTTP calls: scholarly APIs, Tavily, GitHub.
retry_external = retry(
    retry=retry_if_exception(_is_retryable_http),
    wait=wait_random_exponential(multiplier=1, max=30),
    stop=stop_after_attempt(4),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)

# LLM provider calls: fewer attempts here because the router has its own
# provider-fallback layer above this; double-retrying multiplies latency.
retry_llm = retry(
    retry=retry_if_exception(_is_retryable_http),
    wait=wait_random_exponential(multiplier=2, max=45),
    stop=stop_after_attempt(3),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
