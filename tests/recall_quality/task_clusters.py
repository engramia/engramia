# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Task cluster definitions for recall quality tests.

All task strings are raw (no run_id prefix).  Test fixtures add the prefix.

Design constraints:
- 12 clusters × 5 variants each.
- Intra-cluster: semantically similar, Jaccard < 0.7 (avoids recall dedup).
- Cross-cluster: semantically distinct.
- 15 noise tasks: completely unrelated to any cluster.
- 8 boundary tasks: straddle two clusters.
"""
from engramia._util import jaccard

# ---------------------------------------------------------------------------
# Clusters
# ---------------------------------------------------------------------------

CLUSTERS: dict[str, list[str]] = {
    "C01": [
        "Load CSV file and filter rows where column 'status' equals 'active'",
        "Read a spreadsheet in CSV format, select only active entries",
        "Import comma-separated data, keep records matching status=active",
        "Open tabular CSV dataset, extract rows by status field value",
        "CSV row selection: retain entries where the status attribute is active",
    ],
    "C02": [
        "Group CSV by 'category' column and sum the 'amount' field",
        "Aggregate tabular data: compute total amounts per category",
        "Summarize CSV — calculate category-wise sum of amount values",
        "Pivot CSV by category label, produce sum of numeric amount column",
        "Per-group totals from comma-separated dataset grouped on category",
    ],
    "C03": [
        "Parse TOML config file and validate required keys exist",
        "Read configuration in TOML format, raise error on missing fields",
        "TOML loader with mandatory key checking and type validation",
        "Verify TOML configuration contains all necessary settings",
        "Configuration validator: load TOML, assert required entries present",
    ],
    "C04": [
        "Merge two YAML config files, environment variables override file values",
        "Combine base and override YAML configs with env var precedence",
        "Configuration layering: YAML defaults plus environment overrides",
        "Load hierarchical YAML settings, let env vars take priority",
        "Multi-source config merger: base.yaml plus os.environ overrides",
    ],
    "C05": [
        "GET request with automatic retry on 5xx errors, max 3 attempts",
        "Resilient HTTP fetch: backoff and retry for server failures",
        "URL retrieval with exponential backoff on transient HTTP errors",
        "HTTP client that retries failed requests up to three times",
        "Fault-tolerant GET request handler with configurable retry logic",
    ],
    "C06": [
        "Paginated API fetch: collect all pages until no next_cursor",
        "Iterate REST endpoint pages, accumulate results until exhausted",
        "Cursor-based pagination client for REST APIs",
        "Collect every page from a paginated JSON endpoint automatically",
        "Auto-pagination wrapper: follow next links until empty response",
    ],
    "C07": [
        "Compute rolling 7-day moving average over time series data",
        "Calculate sliding window mean with period=7 for sequential values",
        "Time series smoothing: 7-point rolling arithmetic mean",
        "Apply moving average filter with window=7 to numeric sequence",
        "Windowed average computation across temporal data points",
    ],
    "C08": [
        "Z-score normalize a list of numeric values",
        "Standardize array: subtract mean, divide by standard deviation",
        "Feature scaling using z-score transformation",
        "Normalize numbers to zero mean and unit variance",
        "Statistical standardization of numeric dataset via z-scores",
    ],
    "C09": [
        "Fetch multiple URLs concurrently with asyncio, limit to 5 simultaneous",
        "Async batch downloader with semaphore-bounded concurrency",
        "Parallel HTTP requests using asyncio gather with max 5 connections",
        "Concurrent URL fetching: async event loop with connection limiter",
        "Non-blocking multi-URL retrieval, cap simultaneous requests at five",
    ],
    "C10": [
        "Extract all email addresses from text using regex",
        "Find valid emails in a string via regular expression matching",
        "Regex-based email parser: scan text, return address list",
        "Pattern matching to extract email addresses from document text",
        "Email finder: identify and collect addresses using regex patterns",
    ],
    "C11": [
        "Bulk upsert records into PostgreSQL table, skip duplicates on primary key",
        "Batch INSERT ON CONFLICT DO UPDATE for Postgres table",
        "PostgreSQL mass upsert: handle key collisions with update strategy",
        "Efficient bulk write to Postgres with duplicate key resolution",
        "Database batch operation: insert-or-update rows in PostgreSQL",
    ],
    "C12": [
        "Scan directory recursively and remove duplicate files by MD5 hash",
        "Find duplicates in folder tree using content-based hashing",
        "File dedup tool: hash every file, delete copies keeping first",
        "Directory cleaner: identify and remove duplicate files by checksum",
        "Recursive file deduplication using MD5 fingerprinting",
    ],
}

# ---------------------------------------------------------------------------
# Noise tasks (completely unrelated to any cluster)
# ---------------------------------------------------------------------------

NOISE_TASKS: list[str] = [
    "Resize JPEG image to 800x600 preserving aspect ratio",
    "Generate QR code from arbitrary URL string",
    "Extract audio waveform peaks from MP3 file",
    "Scan nearby Bluetooth devices and list their names",
    "Add diagonal watermark text overlay to PDF pages",
    "Establish SSH tunnel with local port forwarding",
    "Capture video frames at 1 FPS and export as PNG sequence",
    "Retrieve current weather forecast from public meteorology API",
    "Perform DNS lookup: resolve hostname to IPv4 and IPv6 addresses",
    "Generate 4096-bit RSA key pair and save as PEM files",
    "Run OCR text extraction on a scanned PNG document",
    "Convert HTML table elements into Python list of row dicts",
    "Compress entire folder into password-protected ZIP archive",
    "Dispatch Slack notification via incoming webhook URL",
    "Monitor system CPU usage percentage, alert when exceeding 90%",
]

# ---------------------------------------------------------------------------
# Boundary tasks (straddle two clusters)
# ---------------------------------------------------------------------------

BOUNDARY_TASKS: list[tuple[str, str, str]] = [
    # (task, cluster_a, cluster_b)
    ("Load CSV file, fetch missing values from REST API", "C01", "C05"),
    ("Parse TOML config and validate numeric ranges are within bounds", "C03", "C08"),
    ("Async concurrent CSV row export to cloud storage endpoint", "C09", "C02"),
    ("Normalize CSV column values using z-score standardization", "C01", "C08"),
    ("Retry failed PostgreSQL upsert on deadlock error with backoff", "C11", "C05"),
    ("Extract email addresses from paginated API response", "C10", "C06"),
    ("Deduplicate files listed in YAML configuration manifest", "C12", "C04"),
    ("Rolling moving average of async concurrent HTTP request latency", "C07", "C09"),
]

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_jaccard_diversity(threshold: float = 0.7) -> list[str]:
    """Return warnings for any intra-cluster task pair with Jaccard >= threshold.

    All variants within a cluster must have Jaccard < threshold to avoid
    being collapsed by recall deduplication (which uses the same threshold).

    Args:
        threshold: Maximum allowed Jaccard similarity between variants.

    Returns:
        List of warning strings (empty means all clusters are OK).
    """
    warnings: list[str] = []
    for cluster_id, tasks in CLUSTERS.items():
        for i, a in enumerate(tasks):
            for j, b in enumerate(tasks):
                if j <= i:
                    continue
                sim = jaccard(a, b)
                if sim >= threshold:
                    warnings.append(
                        f"{cluster_id} variants {i}↔{j}: Jaccard={sim:.3f} >= {threshold} "
                        f"('{a[:40]}…' / '{b[:40]}…')"
                    )
    return warnings


if __name__ == "__main__":
    issues = validate_jaccard_diversity()
    if issues:
        print("⚠ Jaccard diversity warnings:")
        for w in issues:
            print(" ", w)
    else:
        print("OK: All intra-cluster task pairs have Jaccard < 0.7")
