# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Engramia billing module.

Provides plan enforcement, usage metering, and Stripe integration for
the Cloud SaaS offering. All components are no-ops when no DB engine
is configured (dev / JSON-storage mode).

Public surface:
    BillingService   — main facade; stored on app.state.billing_service
    PLAN_LIMITS      — tier → {eval_runs, patterns, projects} mapping
"""

from engramia.billing.models import PLAN_LIMITS
from engramia.billing.service import BillingService

__all__ = ["BillingService", "PLAN_LIMITS"]
