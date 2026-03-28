# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for api/audit.py — structured security audit logging.

Verifies that every security-relevant event is emitted at WARNING level as
a parseable JSON entry with the required fields.
"""

import json
import logging

from engramia.api.audit import AuditEvent, log_event


class TestAuditEvent:
    def test_all_event_values_are_lowercase_strings(self):
        """AuditEvent values must be lowercase — used as JSON field values."""
        assert AuditEvent.AUTH_FAILURE == "auth_failure"
        assert AuditEvent.PATTERN_DELETED == "pattern_deleted"
        assert AuditEvent.RATE_LIMITED == "rate_limited"
        assert AuditEvent.BULK_IMPORT == "bulk_import"

    def test_new_events_present(self):
        """Phase 5.2 key-management and quota events must be present."""
        assert AuditEvent.KEY_CREATED == "key_created"
        assert AuditEvent.KEY_REVOKED == "key_revoked"
        assert AuditEvent.KEY_ROTATED == "key_rotated"
        assert AuditEvent.QUOTA_EXCEEDED == "quota_exceeded"


class TestLogEvent:
    def test_emits_at_warning_level(self, caplog):
        with caplog.at_level(logging.WARNING, logger="engramia.audit"):
            log_event(AuditEvent.AUTH_FAILURE, ip="1.2.3.4")

        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.WARNING

    def test_output_contains_valid_json(self, caplog):
        """log_event() must emit 'AUDIT {json}' where {json} is valid JSON."""
        with caplog.at_level(logging.WARNING, logger="engramia.audit"):
            log_event(AuditEvent.AUTH_FAILURE, ip="1.2.3.4", reason="invalid_key")

        message = caplog.records[0].message
        assert message.startswith("AUDIT ")
        parsed = json.loads(message[len("AUDIT "):])

        assert parsed["audit"] is True
        assert parsed["event"] == "auth_failure"
        assert "timestamp" in parsed

    def test_extra_kwargs_appear_in_output(self, caplog):
        """Caller-supplied kwargs must be included in the JSON entry."""
        with caplog.at_level(logging.WARNING, logger="engramia.audit"):
            log_event(AuditEvent.PATTERN_DELETED, key="patterns/abc123", user="admin")

        parsed = json.loads(caplog.records[0].message[len("AUDIT "):])
        assert parsed["event"] == "pattern_deleted"
        assert parsed["key"] == "patterns/abc123"
        assert parsed["user"] == "admin"

    def test_timestamp_is_utc_iso8601(self, caplog):
        """Timestamp must be in ISO-8601 UTC format (ends with Z)."""
        with caplog.at_level(logging.WARNING, logger="engramia.audit"):
            log_event(AuditEvent.RATE_LIMITED, ip="10.0.0.1", count=5)

        parsed = json.loads(caplog.records[0].message[len("AUDIT "):])
        ts = parsed["timestamp"]
        assert "T" in ts, f"Expected ISO-8601, got: {ts}"
        assert ts.endswith("Z"), f"Expected UTC (Z suffix), got: {ts}"

    def test_all_event_types_emit_correctly(self, caplog):
        """Every AuditEvent variant should produce exactly one log record."""
        with caplog.at_level(logging.WARNING, logger="engramia.audit"):
            for event in AuditEvent:
                log_event(event)

        assert len(caplog.records) == len(AuditEvent)
        emitted_events = {
            json.loads(r.message[len("AUDIT "):])["event"]
            for r in caplog.records
        }
        assert emitted_events == {e.value for e in AuditEvent}
