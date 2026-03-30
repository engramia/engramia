# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""ROI Analytics package (Phase 5.7).

Public surface:
    ROICollector  — records learn/recall events into storage
    ROIAggregator — aggregates events into per-scope ROIRollup snapshots
"""

from engramia.analytics.aggregator import ROIAggregator
from engramia.analytics.collector import ROICollector

__all__ = ["ROIAggregator", "ROICollector"]
