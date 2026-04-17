# API Versioning and Deprecation Policy

## Versioning Strategy

Engramia uses **URL-prefix versioning**. All stable API endpoints are mounted under `/v1/`:

```
POST   /v1/learn
POST   /v1/recall
POST   /v1/evaluate
POST   /v1/compose
POST   /v1/evolve
GET    /v1/feedback
GET    /v1/metrics
GET    /v1/health
GET    /v1/health/deep
GET    /v1/export
POST   /v1/import
DELETE /v1/patterns/{pattern_key}
POST   /v1/aging
POST   /v1/feedback/decay
POST   /v1/analyze-failures
POST   /v1/skills/register
POST   /v1/skills/search
GET    /v1/version
```

The version prefix is an integer major version. It changes only when a breaking change is introduced. Minor feature additions and non-breaking changes are shipped within the same major version.

### Version identifier

The active API version is available at runtime:

```http
GET /v1/version
```

```json
{
  "app_version": "0.6.0",
  "api_version": "1",
  "git_commit": "abc1234",
  "build_time": "2026-04-07T00:00:00Z"
}
```

`api_version` reflects the URL prefix number (`"1"` for `/v1/`).

## Stability Guarantees

### Stable (current: v1)

Within a major version, Engramia guarantees:

- **No removal of endpoints** without a deprecation period (see below).
- **No removal of response fields** — new fields may be added at any time; existing fields will not disappear.
- **No change in field types** — a field that returns a string will always return a string.
- **No change in required request fields** — optional fields may be added; required fields will not be added without a deprecation cycle.
- **Backward-compatible error format** — the `error_code` and `error_message` fields will always be present in error responses.

### Non-stable endpoints

Endpoints marked `[BETA]` in the API reference (`/v1/governance/*`, `/v1/analytics/*`) may change within the same major version. Breaking changes to beta endpoints are communicated via the changelog with at least 30 days notice.

## Breaking vs. Non-Breaking Changes

| Change type | Classification |
|---|---|
| Add new optional request field | Non-breaking |
| Add new response field | Non-breaking |
| Add new endpoint | Non-breaking |
| Remove or rename response field | Breaking |
| Change field type | Breaking |
| Remove endpoint | Breaking |
| Add new required request field | Breaking |
| Change error code for an existing error | Breaking |
| Change HTTP status code for an existing error | Breaking |

## Deprecation Policy

When a breaking change is required, Engramia follows this process:

### 1. Announce deprecation (minimum 6 months before removal)

Deprecated endpoints or fields are announced via:

- The `CHANGELOG.md` entry in the release that introduces the deprecation.
- A `Deprecation` response header on the deprecated endpoint:
  ```
  Deprecation: true
  Sunset: Sat, 01 Aug 2026 00:00:00 GMT
  Link: <https://engramia.dev/docs/api-versioning#migration-v1-to-v2>; rel="successor-version"
  ```
- The API reference documentation, with a `[DEPRECATED]` banner and the sunset date.

### 2. Parallel operation period

During the deprecation period, both the old and new versions operate simultaneously. Clients can migrate at their own pace.

### 3. Removal

After the sunset date, the deprecated endpoint or field is removed. A new major version prefix is assigned (e.g. `/v2/`).

### Minimum timelines

| Scenario | Minimum notice period |
|---|---|
| Remove a stable endpoint | 6 months |
| Remove a stable response field | 6 months |
| Add a required request field | 6 months |
| Remove a beta endpoint | 30 days |

## Migration Guides

### v1 (current)

No migration required — v1 is the current stable version.

### Future: v1 → v2

When v2 is introduced, a dedicated migration guide will be published at `docs/migration-v1-v2.md` with:

- A full list of breaking changes.
- Side-by-side before/after request and response examples.
- A migration checklist.
- A timeline for v1 sunset.

## Client Recommendations

- **Pin to a major version prefix** (`/v1/`) rather than a specific endpoint path, so non-breaking additions are available automatically.
- **Treat unknown response fields as ignored**, not as errors — this allows forward-compatible clients.
- **Subscribe to release notes** to be notified of deprecations before they reach sunset.
- **Check the `Deprecation` response header** programmatically if you want to automate detection of deprecated usage in your integration tests.

## Error Response Format

All API errors (regardless of version) return a structured JSON body:

```json
{
  "error_code": "UNAUTHORIZED",
  "error_message": "Invalid API key."
}
```

Contextual fields are included where relevant:

```json
{
  "error_code": "QUOTA_EXCEEDED",
  "error_message": "Pattern quota reached. Delete old patterns or upgrade your plan.",
  "current": 10000,
  "limit": 10000
}
```

```json
{
  "error_code": "RATE_LIMITED",
  "error_message": "Rate limit exceeded. Max 60 requests per minute.",
  "retry_after": 60
}
```

### Error code reference

| `error_code` | HTTP status | Description |
|---|---|---|
| `BAD_REQUEST` | 400 | Malformed or semantically invalid request |
| `UNAUTHORIZED` | 401 | Missing or invalid API key / JWT token |
| `FORBIDDEN` | 403 | Authenticated but lacking permission for this operation |
| `NOT_FOUND` | 404 | Resource does not exist |
| `CONFLICT` | 409 | Resource already exists (e.g. duplicate email on registration) |
| `PAYLOAD_TOO_LARGE` | 413 | Request body exceeds the configured size limit |
| `VALIDATION_ERROR` | 422 | Request body failed schema validation |
| `QUOTA_EXCEEDED` | 429 | Pattern quota for the tenant/project has been reached |
| `RATE_LIMITED` | 429 | Too many requests in the current time window |
| `PROVIDER_NOT_CONFIGURED` | 501 | Operation requires an LLM provider that is not configured |
| `SERVICE_UNAVAILABLE` | 503 | API is in maintenance mode or a required backend is down |
