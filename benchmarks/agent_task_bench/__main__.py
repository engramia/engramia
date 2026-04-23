# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""CLI entry point.

``python -m benchmarks.agent_task_bench`` runs the full comparison
(baseline + engramia). See :mod:`benchmarks.agent_task_bench.runner`
for arguments.
"""

from benchmarks.agent_task_bench.runner import main

raise SystemExit(main())
