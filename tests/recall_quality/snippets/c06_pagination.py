# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""C06 — Paginated API Fetch snippets."""

GOOD: dict = {
    "eval_score": 9.0,
    "output": "Fetched 3 pages, 87 total items.",
    "code": '''\
import json
import urllib.request
from collections.abc import Iterator
from typing import Any


def paginated_fetch(
    base_url: str,
    *,
    cursor_field: str = "next_cursor",
    items_field: str = "items",
    api_key: str | None = None,
    page_limit: int = 100,
) -> Iterator[dict[str, Any]]:
    """Yield all items from a cursor-paginated REST endpoint.

    Args:
        base_url: URL of the first page (without cursor param).
        cursor_field: Response field containing the next cursor.
        items_field: Response field containing the items list.
        api_key: Optional Bearer token.
        page_limit: Safety limit on number of pages (default 100).

    Yields:
        Individual item dicts from each page.
    """
    cursor: str | None = None
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    for _ in range(page_limit):
        url = f"{base_url}&cursor={cursor}" if cursor else base_url
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        yield from data.get(items_field, [])

        cursor = data.get(cursor_field)
        if not cursor:
            break
''',
}

MEDIUM: dict = {
    "eval_score": 5.5,
    "output": "Fetched all pages.",
    "code": """\
import json
import urllib.request

def fetch_all_pages(url):
    all_items = []
    cursor = None
    while True:
        full_url = f"{url}&cursor={cursor}" if cursor else url
        with urllib.request.urlopen(full_url) as r:
            data = json.loads(r.read())
        all_items.extend(data.get("items", []))
        cursor = data.get("next_cursor")
        if not cursor:
            break
    return all_items
""",
}

BAD: dict = {
    "eval_score": 2.5,
    "output": "",
    "code": """\
import json
import urllib.request

# BAD: recursive implementation with no base case guard → stack overflow
def fetch_page(url, cursor=None, results=None):
    if results is None:
        results = []
    full_url = url + ("&cursor=" + cursor if cursor else "")
    data = json.loads(urllib.request.urlopen(full_url).read())
    results.extend(data["items"])
    # BUG: will raise KeyError if "next_cursor" not present
    return fetch_page(url, data["next_cursor"], results)
""",
}
