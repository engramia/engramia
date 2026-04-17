# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Service layer — thin, single-responsibility classes extracted from Memory.

Each service owns one domain of the Memory façade:
- LearningService   — learn()
- RecallService     — recall()
- EvaluationService — evaluate()
- CompositionService — compose()
"""

from engramia.core.services.composition import CompositionService
from engramia.core.services.evaluation import EvaluationService
from engramia.core.services.learning import LearningService
from engramia.core.services.recall import RecallService

__all__ = [
    "CompositionService",
    "EvaluationService",
    "LearningService",
    "RecallService",
]
