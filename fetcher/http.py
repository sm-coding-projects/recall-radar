from __future__ import annotations

import logging
import random
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "recall-radar/0.1 (+https://github.com/sm-coding-projects/recall-radar)"

# Every source here is a public government API with no key and no published
# concurrency allowance, so we stay single-threaded and back off generously.
DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=15.0)
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5


def build_client() -> httpx.Client:
    return httpx.Client(
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*"},
    )


def get(client: httpx.Client, url: str, **kwargs: Any) -> httpx.Response:
    """GET with exponential backoff on transient failures.

    Honours Retry-After when the server sends one; otherwise backs off
    2^n seconds with jitter. Non-retryable 4xx raise immediately -- retrying
    a 403 or 404 just wastes the upstream's time.
    """
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.get(url, **kwargs)
        except httpx.RequestError as exc:
            last_error = exc
            if attempt == MAX_ATTEMPTS:
                raise
            delay = _backoff(attempt)
            log.warning("%s (attempt %d/%d), retrying in %.1fs", exc, attempt, MAX_ATTEMPTS, delay)
            time.sleep(delay)
            continue

        if response.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS:
            delay = _retry_after(response) or _backoff(attempt)
            log.warning(
                "HTTP %d from %s (attempt %d/%d), retrying in %.1fs",
                response.status_code, url, attempt, MAX_ATTEMPTS, delay,
            )
            time.sleep(delay)
            continue

        response.raise_for_status()
        return response

    raise RuntimeError(f"unreachable: {url}") from last_error


def _backoff(attempt: int) -> float:
    return min(2.0 ** attempt, 30.0) + random.uniform(0, 0.5)


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return min(float(value), 60.0)
    except ValueError:
        return None
