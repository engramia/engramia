"""Structured audit logging for the Agent Brain API.

Audit events cover security-relevant operations that should be traceable:
- AUTH_FAILURE: invalid or missing Bearer token
- PATTERN_DELETED: pattern removed via DELETE /v1/patterns/{key}
- RATE_LIMITED: request rejected by the rate limiter

Usage:
    from agent_brain.api.audit import AuditEvent, log_event
    log_event(AuditEvent.AUTH_FAILURE, ip="1.2.3.4", reason="invalid_key")

Output goes to the ``agent_brain.audit`` logger at WARNING level so that
standard logging configuration captures it separately from debug noise.
"""

import json
import logging
import time
from enum import Enum
from typing import Any

_audit_log = logging.getLogger("agent_brain.audit")


class AuditEvent(str, Enum):
    AUTH_FAILURE = "auth_failure"
    PATTERN_DELETED = "pattern_deleted"
    RATE_LIMITED = "rate_limited"


def log_event(event: AuditEvent, **kwargs: Any) -> None:
    """Emit a structured audit log entry at WARNING level.

    The entry is serialized as JSON for machine-parseable audit trails.

    Args:
        event: The audit event type.
        **kwargs: Additional context fields (ip, path, reason, etc.).
    """
    entry = {
        "audit": True,
        "event": event.value,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **kwargs,
    }
    _audit_log.warning("AUDIT %s", json.dumps(entry, default=str))
