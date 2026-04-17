# API Stability and Deprecation Policy

## Versioning

All REST API endpoints are under the `/v1/` prefix. The Python library exposes
its public API through the `Memory` class in `engramia/__init__.py`.

## Stability guarantees

| Surface | Guarantee |
|---------|-----------|
| `Memory` class public methods | Stable since v0.4.0. Signature changes are breaking. |
| REST API `/v1/*` endpoints | Stable. New endpoints may be added; existing ones will not change incompatibly. |
| Response fields | Additive only — new fields may appear, existing fields will not be removed or change type. |
| Pydantic models in `types.py` | Stable. Field additions are non-breaking; removals/renames are breaking. |
| Internal modules (`_context`, `_util`, `_factory`) | Unstable — may change without notice. |
| CLI commands | Stable. New commands/options may be added; existing ones preserved. |

## Deprecation process

When a breaking change is necessary:

1. **Announce** — Deprecation notice in CHANGELOG.md and a `DeprecationWarning` in code (minimum 2 minor releases before removal)
2. **Document** — Migration guide in the release notes
3. **Grace period** — The deprecated feature continues to work for at least 2 minor releases
4. **Remove** — The feature is removed in the next major version or after the grace period

## API version migration

When `/v2/` is introduced (no current timeline):

- `/v1/` will remain available for at least 6 months after `/v2/` GA
- Both versions will be served simultaneously during the overlap period
- A migration guide will document all breaking changes

## Experimental features

Features marked as **Experimental** in the README (`compose`, `evolve_prompt`, `analyze_failures`)
may change without the full deprecation process. They are explicitly documented as unstable.
