# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Data Governance + Privacy layer (Phase 5.6).

Provides GDPR-compliant operations on top of the core Engramia storage layer:

- RetentionManager  — configurable TTL per project/tenant, auto-cleanup
- RedactionPipeline — pre-storage PII/secrets masking pipeline
- ScopedDeletion    — GDPR Art. 17 right-to-erasure (tenant/project wipe)
- DataExporter      — GDPR Art. 20 data portability (scoped streaming export)
- LifecycleJobs     — compaction, dedup, job/audit cleanup
- AuditScrubber     — PII scrubbing of audit_log entries older than N days

Usage (low-level, from Memory or API routes)::

    from engramia.governance import RetentionManager, RedactionPipeline, ScopedDeletion

    retention = RetentionManager(engine=engine)
    result = retention.apply(dry_run=False)

    pipeline = RedactionPipeline.default()
    clean_design, findings = pipeline.process({"code": "...", "output": "..."})

Symbols whose implementations depend on ``sqlalchemy`` (available only with
the ``[postgres]`` extra) are imported lazily via ``__getattr__`` so that
``import engramia`` works on a bare ``pip install engramia`` without the
extras.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# Redaction has no sqlalchemy dependency and is used eagerly from
# engramia.memory / engramia.core.services.learning; keep it imported.
from engramia.governance.redaction import Finding, RedactionPipeline

_LAZY_ATTRS = {
    "AuditScrubber": ("engramia.governance.audit_scrubber", "AuditScrubber"),
    "ScrubResult": ("engramia.governance.audit_scrubber", "ScrubResult"),
    "DeletionResult": ("engramia.governance.deletion", "DeletionResult"),
    "ScopedDeletion": ("engramia.governance.deletion", "ScopedDeletion"),
    "DataExporter": ("engramia.governance.export", "DataExporter"),
    "LifecycleJobs": ("engramia.governance.lifecycle", "LifecycleJobs"),
    "PurgeResult": ("engramia.governance.retention", "PurgeResult"),
    "RetentionManager": ("engramia.governance.retention", "RetentionManager"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_ATTRS.get(name)
    if target is None:
        raise AttributeError(f"module 'engramia.governance' has no attribute {name!r}")
    module_name, attr_name = target
    from importlib import import_module

    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + list(_LAZY_ATTRS.keys()))


if TYPE_CHECKING:
    from engramia.governance.audit_scrubber import AuditScrubber, ScrubResult
    from engramia.governance.deletion import DeletionResult, ScopedDeletion
    from engramia.governance.export import DataExporter
    from engramia.governance.lifecycle import LifecycleJobs
    from engramia.governance.retention import PurgeResult, RetentionManager


__all__ = [
    "AuditScrubber",
    "DataExporter",
    "DeletionResult",
    "Finding",
    "LifecycleJobs",
    "PurgeResult",
    "RedactionPipeline",
    "RetentionManager",
    "ScopedDeletion",
    "ScrubResult",
]
