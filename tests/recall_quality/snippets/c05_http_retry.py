# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""C05 — HTTP Retry Client snippets."""

GOOD: dict = {
    "eval_score": 9.0,
    "output": "GET https://api.example.com/data → 200 OK (attempt 1)",
    "code": '''\
import time
import urllib.error
import urllib.request
from typing import Any


def get_with_retry(
    url: str,
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    timeout: int = 30,
) -> bytes:
    """GET a URL with exponential backoff retry on 5xx errors.

    Args:
        url: URL to fetch.
        max_attempts: Maximum number of attempts (default 3).
        base_delay: Seconds to wait before first retry (doubles each time).
        timeout: Per-request timeout in seconds.

    Returns:
        Response body as bytes.

    Raises:
        urllib.error.HTTPError: If all attempts fail (re-raises last error).
        urllib.error.URLError: If connection cannot be established.
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                raise  # 4xx — not retryable
            last_exc = exc
            if attempt < max_attempts:
                time.sleep(base_delay * (2 ** (attempt - 1)))
        except urllib.error.URLError as exc:
            last_exc = exc
            if attempt < max_attempts:
                time.sleep(base_delay * (2 ** (attempt - 1)))

    raise last_exc  # type: ignore[misc]
''',
}

MEDIUM: dict = {
    "eval_score": 6.0,
    "output": "Response received.",
    "code": '''\
import time
import urllib.request
import urllib.error

def fetch_with_retry(url, max_retries=3):
    for i in range(max_retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code < 500 or i == max_retries - 1:
                raise
            time.sleep(1)
    return None
''',
}

BAD: dict = {
    "eval_score": 2.0,
    "output": "",
    "code": '''\
import requests

def get_url(url):
    # BAD: no timeout, no retry, requests not in stdlib
    response = requests.get(url)
    return response.text
''',
}
