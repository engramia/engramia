# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Data Governance + Privacy layer (Phase 5.6).

Provides GDPR-compliant operations on top of the core Engramia storage layer:

- RetentionManager  — configurable TTL per project/tenant, auto-cleanup
- RedactionPipeline — pre-storage PII/secrets masking pipeline
- ScopedDeletion    — GDPR Art. 17 right-to-erasure (tenant/project wipe)
- DataExporter      — GDPR Art. 20 data portability (scoped streaming export)
- LifecycleJobs     — compaction, dedup, job/audit cleanup

Usage (low-level, from Memory or API routes)::

    from engramia.governance import RetentionManager, RedactionPipeline, ScopedDeletion

    retention = RetentionManager(engine=engine)
    result = retention.apply(dry_run=False)

    pipeline = RedactionPipeline.default()
    clean_design, findings = pipeline.process({"code": "...", "output": "..."})
"""

from engramia.governance.deletion import DeletionResult, ScopedDeletion
from engramia.governance.export import DataExporter
from engramia.governance.lifecycle import LifecycleJobs
from engramia.governance.redaction import Finding, RedactionPipeline
from engramia.governance.retention import PurgeResult, RetentionManager

__all__ = [
    "DataExporter",
    "DeletionResult",
    "Finding",
    "LifecycleJobs",
    "PurgeResult",
    "RedactionPipeline",
    "RetentionManager",
    "ScopedDeletion",
]
