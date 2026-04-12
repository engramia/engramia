# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""C09 — Async HTTP Batch snippets."""

GOOD: dict = {
    "eval_score": 9.0,
    "output": "Fetched 20 URLs in 1.2s (max 5 concurrent).",
    "code": '''\
import asyncio
from typing import Any


async def fetch_all(
    urls: list[str],
    *,
    concurrency: int = 5,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """Fetch multiple URLs concurrently with bounded parallelism.

    Args:
        urls: List of URLs to fetch.
        concurrency: Maximum simultaneous connections (default 5).
        timeout: Per-request timeout in seconds.

    Returns:
        List of result dicts with keys ``url``, ``status``, ``body`` (or ``error``).
    """
    try:
        import aiohttp
    except ImportError as exc:
        raise ImportError("aiohttp is required: pip install aiohttp") from exc

    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_one(session: aiohttp.ClientSession, url: str) -> dict[str, Any]:
        async with semaphore:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    body = await resp.text()
                    return {"url": url, "status": resp.status, "body": body}
            except Exception as exc:
                return {"url": url, "status": 0, "error": str(exc)}

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_one(session, url) for url in urls]
        return await asyncio.gather(*tasks)
''',
}

MEDIUM: dict = {
    "eval_score": 5.5,
    "output": "Fetched all URLs.",
    "code": """\
import asyncio
import urllib.request

async def fetch_all(urls):
    # BAD: asyncio.gather with unbounded concurrency
    # BAD: uses blocking urllib in async context
    async def fetch(url):
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read()

    return await asyncio.gather(*[fetch(u) for u in urls])
""",
}

BAD: dict = {
    "eval_score": 2.0,
    "output": "",
    "code": """\
import threading
import urllib.request

# BAD: not actually async — uses threads which is fine but defeats the purpose
# BAD: no error handling, no concurrency limit, no timeout
def fetch_all(urls):
    results = []
    threads = []
    for url in urls:
        def worker(u):
            results.append(urllib.request.urlopen(u).read())
        t = threading.Thread(target=worker, args=(url,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    return results
""",
}
