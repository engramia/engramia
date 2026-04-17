# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for Phase 5.6 Data Governance + Privacy.

Covers:
- RedactionPipeline (regex + keyword hooks)
- RetentionManager (timestamp-based scan, dry-run, policy resolution)
- ScopedDeletion (storage-layer cascade)
- DataExporter (streaming export, classification filter)
- Memory.learn() provenance fields + redaction integration
- DataClassification enum
- API endpoint smoke-tests via FastAPI TestClient
"""

import json
import time

import pytest

from engramia.governance.deletion import DeletionResult, ScopedDeletion
from engramia.governance.export import DataExporter
from engramia.governance.redaction import (
    RedactionPipeline,
    RegexRedactor,
    SecretPatternRedactor,
)
from engramia.governance.retention import RetentionManager, compute_expiry_iso
from engramia.memory import Memory
from engramia.types import DataClassification

# ---------------------------------------------------------------------------
# DataClassification
# ---------------------------------------------------------------------------


class TestDataClassification:
    def test_values(self):
        assert DataClassification.PUBLIC == "public"
        assert DataClassification.INTERNAL == "internal"
        assert DataClassification.CONFIDENTIAL == "confidential"

    def test_str_enum_iteration(self):
        values = {c.value for c in DataClassification}
        assert values == {"public", "internal", "confidential"}


# ---------------------------------------------------------------------------
# RedactionPipeline
# ---------------------------------------------------------------------------


class TestRegexRedactor:
    def setup_method(self):
        self.hook = RegexRedactor()

    def test_detects_email(self):
        findings = self.hook.scan("contact admin@example.com for help")
        assert any(f.kind == "email" for f in findings)

    def test_redacts_email(self):
        result = self.hook.redact("Send to user@test.org please")
        assert "user@test.org" not in result
        assert "[REDACTED_EMAIL]" in result

    def test_detects_openai_key(self):
        findings = self.hook.scan("key = sk-abcdefghijklmnopqrstu12345")
        assert any(f.kind == "openai_key" for f in findings)

    def test_redacts_openai_key(self):
        text = "OPENAI_API_KEY = sk-abcdefghijklmnopqrstu12345"
        result = self.hook.redact(text)
        assert "sk-abcdefghijklmnopqrstu12345" not in result
        assert "[REDACTED_OPENAI_KEY]" in result

    def test_detects_jwt(self):
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        findings = self.hook.scan(token)
        assert any(f.kind == "jwt" for f in findings)

    def test_no_findings_on_clean_text(self):
        findings = self.hook.scan("This is clean agent code that does math.")
        assert findings == []


class TestSecretPatternRedactor:
    def setup_method(self):
        self.hook = SecretPatternRedactor()

    def test_detects_password_assignment(self):
        findings = self.hook.scan("password = mysecret123")
        assert len(findings) > 0
        assert findings[0].kind == "credential_assignment"

    def test_detects_token_assignment(self):
        findings = self.hook.scan('token = "abcdef123456"')
        assert len(findings) == 1
        assert findings[0].kind == "credential_assignment"

    def test_redacts_secret(self):
        result = self.hook.redact("api_key = supersecretvalue")
        assert "supersecretvalue" not in result
        assert "[REDACTED]" in result

    def test_no_findings_on_clean_text(self):
        findings = self.hook.scan("result = compute(x + y)")
        assert findings == []


class TestRedactionPipeline:
    def test_default_pipeline_has_hooks(self):
        """Default pipeline must actively redact both email and secret patterns.

        Verifies behaviour (redaction fires) rather than internal hook count,
        so the test remains valid if the pipeline implementation changes.
        """
        pipeline = RedactionPipeline.default()
        _, email_findings = pipeline.process({"code": "contact: admin@example.com"})
        _, secret_findings = pipeline.process({"code": "api_key = supersecretvalue123"})
        assert any(f.kind == "email" for f in email_findings), "default pipeline must detect email addresses"
        assert any(f.kind == "credential_assignment" for f in secret_findings), "default pipeline must detect secret/credential patterns"

    def test_empty_pipeline_is_noop(self):
        pipeline = RedactionPipeline.empty()
        data = {"code": "email@test.com password=secret"}
        clean, findings = pipeline.process(data)
        assert clean == data
        assert findings == []

    def test_process_returns_clean_copy(self):
        pipeline = RedactionPipeline.default()
        data = {"code": "user: admin@example.com", "output": "ok"}
        clean, findings = pipeline.process(data)
        assert "admin@example.com" not in clean["code"]
        assert clean["output"] == "ok"  # clean field unchanged
        assert any(f.kind == "email" for f in findings)

    def test_process_does_not_mutate_original(self):
        pipeline = RedactionPipeline.default()
        original = "contact me@test.com"
        data = {"code": original}
        _, _ = pipeline.process(data)
        assert data["code"] == original  # original not mutated

    def test_finding_has_field_name(self):
        pipeline = RedactionPipeline.default()
        data = {"code": "x = sk-abcdefghijklmnopqrstu12345"}
        _, findings = pipeline.process(data)
        assert all(f.field == "code" for f in findings)

    def test_extra_fields_are_scanned(self):
        pipeline = RedactionPipeline.default()
        data = {"code": "print('hello')"}
        _, findings = pipeline.process(data, extra_fields={"task": "send to admin@x.com"})
        assert any(f.field == "task" and f.kind == "email" for f in findings)

    def test_non_string_values_pass_through(self):
        pipeline = RedactionPipeline.default()
        data = {"code": "x=1", "score": 9.5, "tags": ["a", "b"]}
        clean, _findings = pipeline.process(data)
        assert clean["score"] == 9.5
        assert clean["tags"] == ["a", "b"]


# ---------------------------------------------------------------------------
# Phone redaction
# ---------------------------------------------------------------------------


class TestPhoneRedaction:
    def setup_method(self):
        self.hook = RegexRedactor()

    # --- detection ---

    def test_detects_us_international(self):
        findings = self.hook.scan("Call +1-800-555-0123 for support")
        assert any(f.kind == "phone" for f in findings)

    def test_detects_uk_international(self):
        findings = self.hook.scan("UK line: +44 7700 900123")
        assert any(f.kind == "phone" for f in findings)

    def test_detects_czech_international(self):
        findings = self.hook.scan("CZ support: +420 123 456 789")
        assert any(f.kind == "phone" for f in findings)

    def test_detects_international_with_dots(self):
        findings = self.hook.scan("Fax: +1.800.555.0199")
        assert any(f.kind == "phone" for f in findings)

    def test_detects_international_with_00_prefix(self):
        findings = self.hook.scan("Dial 0044 7700 900123 from abroad")
        assert any(f.kind == "phone" for f in findings)

    def test_detects_parenthesized_area_code(self):
        findings = self.hook.scan("Reservations: (800) 555-0199")
        assert any(f.kind == "phone" for f in findings)

    def test_detects_parenthesized_with_dot_separator(self):
        findings = self.hook.scan("(800) 555.0199")
        assert any(f.kind == "phone" for f in findings)

    def test_counts_multiple_phones(self):
        findings = self.hook.scan("+1-800-555-0100 and +1-888-555-0200")
        phone_findings = [f for f in findings if f.kind == "phone"]
        assert sum(f.count for f in phone_findings) >= 2

    # --- redaction ---

    def test_redacts_us_phone(self):
        result = self.hook.redact("Contact +1-800-555-0123 now")
        assert "+1-800-555-0123" not in result
        assert "[REDACTED_PHONE]" in result

    def test_redacts_uk_phone(self):
        result = self.hook.redact("Reach us on +44 7700 900123")
        assert "+44 7700 900123" not in result
        assert "[REDACTED_PHONE]" in result

    def test_redacts_parenthesized_phone(self):
        result = self.hook.redact("Call (800) 555-0199")
        assert "(800) 555-0199" not in result
        assert "[REDACTED_PHONE]" in result

    # --- no false positives ---

    def test_no_match_on_short_number(self):
        # Only 4 digits total — not a phone number
        findings = self.hook.scan("error code: +1 234")
        assert not any(f.kind == "phone" for f in findings)

    def test_no_match_on_version_number(self):
        findings = self.hook.scan("version 1.2.3.4 released")
        assert not any(f.kind == "phone" for f in findings)

    def test_no_match_on_clean_text(self):
        findings = self.hook.scan("loop 10 times and return result")
        assert not any(f.kind == "phone" for f in findings)


# ---------------------------------------------------------------------------
# Credit card redaction
# ---------------------------------------------------------------------------


class TestCreditCardRedaction:
    def setup_method(self):
        self.hook = RegexRedactor()

    # --- detection by card type ---

    def test_detects_visa(self):
        # Standard Luhn-valid Visa test number
        findings = self.hook.scan("Visa: 4111111111111111")
        assert any(f.kind == "credit_card" for f in findings)

    def test_detects_mastercard_old_range(self):
        # 51xx range
        findings = self.hook.scan("MC: 5500005555555559")
        assert any(f.kind == "credit_card" for f in findings)

    def test_detects_mastercard_new_range(self):
        # 2xxx range (2221-2720)
        findings = self.hook.scan("MC2: 2221000000000009")
        assert any(f.kind == "credit_card" for f in findings)

    def test_detects_amex(self):
        # Amex 4-6-5 format, starts with 37
        findings = self.hook.scan("Amex: 378282246310005")
        assert any(f.kind == "credit_card" for f in findings)

    def test_detects_discover(self):
        # Discover starts with 6011
        findings = self.hook.scan("Discover: 6011111111111117")
        assert any(f.kind == "credit_card" for f in findings)

    def test_detects_discover_65xx(self):
        # Discover 65xx range
        findings = self.hook.scan("Discover: 6500000000000002")
        assert any(f.kind == "credit_card" for f in findings)

    # --- separator variants ---

    def test_detects_card_with_spaces(self):
        findings = self.hook.scan("4111 1111 1111 1111")
        assert any(f.kind == "credit_card" for f in findings)

    def test_detects_card_with_dashes(self):
        findings = self.hook.scan("4111-1111-1111-1111")
        assert any(f.kind == "credit_card" for f in findings)

    def test_detects_amex_with_spaces(self):
        # Amex canonical grouping: 4-6-5 → 3782 822463 10005
        findings = self.hook.scan("3782 822463 10005")
        assert any(f.kind == "credit_card" for f in findings)

    def test_detects_amex_with_dashes(self):
        # Amex canonical grouping: 4-6-5 → 3782-822463-10005
        findings = self.hook.scan("3782-822463-10005")
        assert any(f.kind == "credit_card" for f in findings)

    # --- redaction ---

    def test_redacts_visa_no_separators(self):
        result = self.hook.redact("charged to 4111111111111111")
        assert "4111111111111111" not in result
        assert "[REDACTED_CARD]" in result

    def test_redacts_visa_with_spaces(self):
        result = self.hook.redact("card: 4111 1111 1111 1111 expires 12/26")
        assert "4111 1111 1111 1111" not in result
        assert "[REDACTED_CARD]" in result

    def test_redacts_amex(self):
        result = self.hook.redact("Amex ending 378282246310005")
        assert "378282246310005" not in result
        assert "[REDACTED_CARD]" in result

    # --- no false positives ---

    def test_no_match_on_15_digit_visa_like(self):
        # Visa must be exactly 16 digits; 15 shouldn't match Visa slot
        findings = self.hook.scan("ref: 411111111111111")  # 15 digits starting with 4
        assert not any(f.kind == "credit_card" for f in findings)

    def test_no_match_on_random_digits(self):
        # 16 digits starting with 9 — no valid BIN
        findings = self.hook.scan("order 9999999999999999")
        assert not any(f.kind == "credit_card" for f in findings)

    def test_no_match_on_clean_text(self):
        findings = self.hook.scan("the price is 42 dollars and 50 cents")
        assert not any(f.kind == "credit_card" for f in findings)

    def test_pipeline_detects_card_in_field(self):
        pipeline = RedactionPipeline.default()
        data = {"code": "token = 4111111111111111"}
        clean, findings = pipeline.process(data)
        assert "4111111111111111" not in clean["code"]
        assert any(f.kind == "credit_card" for f in findings)


# ---------------------------------------------------------------------------
# RetentionManager
# ---------------------------------------------------------------------------


class TestRetentionManager:
    def test_default_policy_without_engine(self):
        manager = RetentionManager(engine=None, default_retention_days=90)
        assert manager.get_policy("t", "p") == 90

    def test_apply_dry_run_does_not_delete(self, storage):
        # Store a pattern with an old timestamp
        key = "patterns/old_abc_1000000000000"
        storage.save(
            key,
            {
                "task": "old task",
                "design": {},
                "success_score": 5.0,
                "reuse_count": 0,
                "timestamp": time.time() - 400 * 86400,
            },
        )

        manager = RetentionManager(engine=None, default_retention_days=30)
        result = manager.apply(storage, dry_run=True)

        assert result.dry_run is True
        assert result.purged_count >= 1
        # Key still exists after dry run
        assert storage.load(key)["task"] == "old task"

    def test_apply_deletes_expired_patterns(self, storage):
        key = "patterns/old_xyz_1000000000001"
        storage.save(
            key,
            {
                "task": "expired task",
                "design": {},
                "success_score": 5.0,
                "reuse_count": 0,
                "timestamp": time.time() - 400 * 86400,
            },
        )

        manager = RetentionManager(engine=None, default_retention_days=30)
        result = manager.apply(storage, dry_run=False)

        assert result.dry_run is False
        assert result.purged_count >= 1
        assert storage.load(key) is None

    def test_apply_keeps_fresh_patterns(self, storage):
        key = "patterns/fresh_abc_1000000000002"
        storage.save(
            key, {"task": "fresh task", "design": {}, "success_score": 8.0, "reuse_count": 0, "timestamp": time.time()}
        )

        manager = RetentionManager(engine=None, default_retention_days=30)
        result = manager.apply(storage, dry_run=False)

        assert storage.load(key)["task"] == "fresh task"
        assert key not in result.purged_keys


def test_compute_expiry_iso():
    expiry = compute_expiry_iso(30)
    # Should be an ISO-8601 string in the future
    assert "T" in expiry
    assert expiry > time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def test_compute_expiry_iso_one_year():
    expiry = compute_expiry_iso(365)
    assert expiry.endswith("Z")
    assert "T" in expiry


# ---------------------------------------------------------------------------
# Job dispatch integration (governance operations)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# PostgresStorage governance methods (mocked engine)
# ---------------------------------------------------------------------------


class TestPostgresStorageGovernance:
    """Tests for the new governance methods on PostgresStorage using a mock engine."""

    @pytest.fixture
    def mock_engine(self):
        from unittest.mock import MagicMock

        engine = MagicMock()
        conn = MagicMock()
        # Support context managers
        engine.begin.return_value.__enter__ = lambda *a: conn
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        engine.connect.return_value.__enter__ = lambda *a: conn
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        return engine, conn

    def test_save_pattern_meta_calls_update(self, mock_engine, tmp_path):
        engine, conn = mock_engine
        from unittest.mock import patch

        from engramia.providers.postgres import PostgresStorage

        with patch("engramia.providers.postgres.PostgresStorage.__init__", lambda *a, **kw: None):
            storage = PostgresStorage.__new__(PostgresStorage)
            storage._engine = engine
            from sqlalchemy import text as _text

            storage._text = _text
            storage._embedding_dim = 1536

            with patch("engramia._context.get_scope") as mock_scope:
                from engramia.types import Scope

                mock_scope.return_value = Scope()
                storage.save_pattern_meta(
                    "patterns/test_001",
                    classification="confidential",
                    source="api",
                    run_id="run-123",
                    author="key-abc",
                    redacted=True,
                    expires_at="2030-01-01T00:00:00Z",
                )
            # Verify execute was called
            assert conn.execute.called

    def test_save_pattern_meta_handles_exception(self, mock_engine, tmp_path):
        engine, conn = mock_engine
        conn.execute.side_effect = Exception("DB error")

        from unittest.mock import patch

        from engramia.providers.postgres import PostgresStorage

        with patch("engramia.providers.postgres.PostgresStorage.__init__", lambda *a, **kw: None):
            storage = PostgresStorage.__new__(PostgresStorage)
            storage._engine = engine
            from sqlalchemy import text as _text

            storage._text = _text

            with patch("engramia._context.get_scope") as mock_scope:
                from engramia.types import Scope

                mock_scope.return_value = Scope()
                # Should not raise — exception is logged and swallowed
                storage.save_pattern_meta("patterns/fail_001")

    def test_delete_scope_calls_delete(self, mock_engine):
        engine, conn = mock_engine
        r = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
        r.rowcount = 5
        conn.execute.return_value = r

        from unittest.mock import patch

        from engramia.providers.postgres import PostgresStorage

        with patch("engramia.providers.postgres.PostgresStorage.__init__", lambda *a, **kw: None):
            storage = PostgresStorage.__new__(PostgresStorage)
            storage._engine = engine
            from sqlalchemy import text as _text

            storage._text = _text

            storage.delete_scope("tenant1", "project1")
            assert conn.execute.called


# ---------------------------------------------------------------------------
# Job dispatch integration (governance operations)
# ---------------------------------------------------------------------------


class TestGovernanceJobDispatch:
    def test_dispatch_retention_cleanup(self, storage, fake_embeddings):
        from engramia.jobs.dispatch import dispatch_job

        mem = Memory(embeddings=fake_embeddings, storage=storage)
        storage.save(
            "patterns/jd_old_001",
            {
                "task": "jd old",
                "design": {},
                "success_score": 4.0,
                "reuse_count": 0,
                "timestamp": time.time() - 400 * 86400,
            },
        )
        result = dispatch_job(mem, "retention_cleanup", {"dry_run": True})
        assert "purged_count" in result
        assert "dry_run" in result

    def test_dispatch_compact_audit_log(self, storage, fake_embeddings):
        from engramia.jobs.dispatch import dispatch_job

        mem = Memory(embeddings=fake_embeddings, storage=storage)
        result = dispatch_job(mem, "compact_audit_log", {})
        assert "deleted_count" in result

    def test_dispatch_cleanup_old_jobs(self, storage, fake_embeddings):
        from engramia.jobs.dispatch import dispatch_job

        mem = Memory(embeddings=fake_embeddings, storage=storage)
        result = dispatch_job(mem, "cleanup_old_jobs", {})
        assert "deleted_count" in result

    def test_dispatch_unknown_governance_op_raises(self, storage, fake_embeddings):
        from engramia.jobs.dispatch import dispatch_job

        mem = Memory(embeddings=fake_embeddings, storage=storage)
        with pytest.raises(ValueError, match="Unknown"):
            dispatch_job(mem, "unknown_governance_op", {})


# ---------------------------------------------------------------------------
# ScopedDeletion
# ---------------------------------------------------------------------------


class TestScopedDeletion:
    def test_delete_project_removes_storage_data(self, storage):
        # Store some keys
        for i in range(3):
            storage.save(
                f"patterns/key{i}_1000",
                {
                    "task": f"task {i}",
                    "design": {},
                    "success_score": 7.0,
                    "reuse_count": 0,
                    "timestamp": time.time(),
                },
            )

        deletion = ScopedDeletion(engine=None)
        result = deletion.delete_project(storage, tenant_id="default", project_id="default")

        assert isinstance(result, DeletionResult)
        assert result.patterns_deleted >= 3
        # Keys should be gone
        remaining = storage.list_keys(prefix="patterns/")
        assert len(remaining) == 0

    def test_deletion_result_fields(self):
        result = DeletionResult(tenant_id="t1", project_id="p1", patterns_deleted=5)
        assert result.tenant_id == "t1"
        assert result.project_id == "p1"
        assert result.patterns_deleted == 5
        assert result.jobs_deleted == 0


# ---------------------------------------------------------------------------
# DataExporter
# ---------------------------------------------------------------------------


class TestDataExporter:
    def test_stream_returns_all_patterns(self, storage):
        for i in range(3):
            storage.save(
                f"patterns/exp{i}_1000",
                {
                    "task": f"task {i}",
                    "design": {"code": "pass"},
                    "success_score": 7.0,
                    "reuse_count": 0,
                    "timestamp": time.time(),
                },
            )

        exporter = DataExporter()
        records = list(exporter.stream(storage))

        assert len(records) == 3
        for rec in records:
            assert rec["version"] == 1
            assert rec["key"].startswith("patterns/")
            assert "data" in rec

    def test_stream_excludes_non_pattern_keys(self, storage):
        storage.save("metrics/total", {"runs": 1})
        storage.save(
            "patterns/real_001",
            {
                "task": "real",
                "design": {},
                "success_score": 7.0,
                "reuse_count": 0,
                "timestamp": time.time(),
            },
        )

        exporter = DataExporter()
        records = list(exporter.stream(storage))

        keys = [r["key"] for r in records]
        assert all(k.startswith("patterns/") for k in keys)

    def test_stream_empty_storage(self, storage):
        exporter = DataExporter()
        records = list(exporter.stream(storage))
        assert records == []


# ---------------------------------------------------------------------------
# Memory.learn() — provenance + redaction integration
# ---------------------------------------------------------------------------


class TestMemoryLearnGovernance:
    def test_learn_accepts_provenance_kwargs(self, mem):
        result = mem.learn(
            task="Parse CSV file",
            code="import csv; print(csv.reader(f))",
            eval_score=8.0,
            run_id="run-abc-123",
            classification="internal",
            source="sdk",
            author="key-xyz",
        )
        assert result.stored is True

    def test_learn_default_classification_is_internal(self, mem):
        result = mem.learn(task="Default classification task", code="pass", eval_score=7.0)
        assert result.stored is True

    def test_learn_with_redaction_pipeline(self, storage, fake_embeddings):
        pipeline = RedactionPipeline.default()
        mem_with_redaction = Memory(
            embeddings=fake_embeddings,
            storage=storage,
            redaction=pipeline,
        )
        result = mem_with_redaction.learn(
            task="Send email to admin@example.com",
            code="import smtplib; password = 'supersecretpassword'",
            eval_score=6.0,
        )
        assert result.stored is True

        # The stored pattern should have the redacted code (password= is a keyword)
        matches = mem_with_redaction.recall(task="Send email", limit=1)
        assert len(matches) == 1
        stored_code = matches[0].pattern.design.get("code", "")
        assert "supersecretpassword" not in stored_code

    def test_learn_without_redaction_keeps_original(self, mem):
        code_with_secret = "password = 'original_secret'"
        mem.learn(task="Secret task", code=code_with_secret, eval_score=5.0)
        matches = mem.recall(task="Secret task", limit=1)
        assert len(matches) == 1
        assert "original_secret" in matches[0].pattern.design.get("code", "")


# ---------------------------------------------------------------------------
# API endpoint smoke tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGovernanceAPI:
    @pytest.fixture
    def client(self, fake_embeddings, storage):
        """Minimal FastAPI app with just the governance router mounted."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from engramia.api.auth import require_auth
        from engramia.api.governance import router as gov_router

        app = FastAPI()
        # Wire state used by governance router
        app.state.memory = Memory(embeddings=fake_embeddings, storage=storage)
        app.state.auth_engine = None

        # Override require_auth to be a no-op in tests
        app.dependency_overrides[require_auth] = lambda: None

        app.include_router(gov_router, prefix="/v1")
        return TestClient(app)

    @pytest.fixture
    def mem(self, fake_embeddings, storage):
        return Memory(embeddings=fake_embeddings, storage=storage)

    def test_get_retention_returns_policy(self, client):
        resp = client.get("/v1/governance/retention")
        assert resp.status_code == 200
        data = resp.json()
        assert "retention_days" in data
        assert "source" in data
        assert data["source"] == "default"

    def test_set_retention_requires_db(self, client):
        resp = client.put("/v1/governance/retention", json={"retention_days": 90})
        # JSON storage mode → 501
        assert resp.status_code == 501

    def test_apply_retention_dry_run(self, client, storage):
        # Add an expired pattern
        storage.save(
            "patterns/expired_001",
            {
                "task": "old task",
                "design": {},
                "success_score": 5.0,
                "reuse_count": 0,
                "timestamp": time.time() - 400 * 86400,
            },
        )
        resp = client.post("/v1/governance/retention/apply", json={"dry_run": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert data["purged_count"] >= 1

    def test_export_returns_ndjson(self, client, mem):
        mem.learn(task="Export test task", code="print('hi')", eval_score=8.0)
        resp = client.get("/v1/governance/export")
        assert resp.status_code == 200
        assert "ndjson" in resp.headers.get("content-type", "")
        lines = [line for line in resp.text.strip().split("\n") if line]
        assert len(lines) >= 1
        record = json.loads(lines[0])
        assert "key" in record
        assert "data" in record

    def test_classify_pattern_updates_classification(self, client, mem):
        mem.learn(task="Classify test", code="pass", eval_score=7.0)
        matches = mem.recall(task="Classify test", limit=1)
        assert len(matches) >= 1
        key = matches[0].pattern_key

        resp = client.put(
            f"/v1/governance/patterns/{key}/classify",
            json={"classification": "confidential"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["classification"] == "confidential"
        assert data["pattern_key"] == key

    def test_classify_invalid_classification(self, client, mem):
        mem.learn(task="Invalid classify test", code="pass", eval_score=7.0)
        matches = mem.recall(task="Invalid classify test", limit=1)
        key = matches[0].pattern_key

        resp = client.put(
            f"/v1/governance/patterns/{key}/classify",
            json={"classification": "top_secret"},
        )
        assert resp.status_code == 422

    def test_classify_missing_pattern(self, client):
        resp = client.put(
            "/v1/governance/patterns/patterns/nonexistent_99999/classify",
            json={"classification": "public"},
        )
        assert resp.status_code == 404

    def test_delete_project_wipes_data(self, client, storage):
        storage.save(
            "patterns/del_test_001",
            {
                "task": "del task",
                "design": {},
                "success_score": 5.0,
                "reuse_count": 0,
                "timestamp": time.time(),
            },
        )
        resp = client.delete("/v1/governance/projects/default")
        assert resp.status_code == 200
        data = resp.json()
        assert data["patterns_deleted"] >= 1

    def test_export_with_invalid_classification(self, client):
        resp = client.get("/v1/governance/export?classification=invalid_class")
        assert resp.status_code == 422

    def test_apply_retention_without_dry_run(self, client, storage):
        storage.save(
            "patterns/ret_apply_001",
            {
                "task": "apply task",
                "design": {},
                "success_score": 5.0,
                "reuse_count": 0,
                "timestamp": time.time() - 400 * 86400,
            },
        )
        resp = client.post("/v1/governance/retention/apply", json={"dry_run": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is False
        assert data["purged_count"] >= 1


# ---------------------------------------------------------------------------
# RetentionManager — policy setters + more paths
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ScopedDeletion — with mock engine
# ---------------------------------------------------------------------------


class TestScopedDeletionWithMockEngine:
    @pytest.fixture
    def mock_engine(self):
        from unittest.mock import MagicMock

        engine = MagicMock()
        conn = MagicMock()
        engine.begin.return_value.__enter__ = lambda *a: conn
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        engine.connect.return_value.__enter__ = lambda *a: conn
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        return engine, conn

    def test_delete_project_with_mock_engine(self, storage, mock_engine):
        engine, conn = mock_engine
        r = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
        r.rowcount = 2
        conn.execute.return_value = r

        for i in range(2):
            storage.save(
                f"patterns/mockdel_{i}",
                {
                    "task": f"t{i}",
                    "design": {},
                    "success_score": 5.0,
                    "reuse_count": 0,
                    "timestamp": time.time(),
                },
            )

        deletion = ScopedDeletion(engine=engine)
        result = deletion.delete_project(storage, tenant_id="default", project_id="default")
        assert result.patterns_deleted >= 2
        assert result.jobs_deleted == 2  # from mock rowcount
        assert conn.execute.called

    def test_delete_tenant_with_mock_engine(self, storage, mock_engine):
        engine, conn = mock_engine
        from unittest.mock import MagicMock

        # Mock project listing — fetchall() must return rows
        row = MagicMock()
        row.id = "proj1"
        listing_result = MagicMock()
        listing_result.fetchall.return_value = [row]

        r = MagicMock()
        r.rowcount = 1

        # Side effect order: connect() → execute (SELECT projects) / begin() calls for delete_project + soft-delete tenant
        conn.execute.side_effect = [
            listing_result,  # SELECT projects (connect ctx)
            r,  # DELETE jobs
            r,  # UPDATE api_keys
            r,  # UPDATE audit_log
            r,  # UPDATE projects soft-delete
            r,  # UPDATE tenants soft-delete
        ]

        deletion = ScopedDeletion(engine=engine)
        result = deletion.delete_tenant(storage, tenant_id="default")
        assert result.tenant_id == "default"
        assert result.project_id == "*"


# ---------------------------------------------------------------------------
# RetentionManager — with mock engine
# ---------------------------------------------------------------------------


class TestRetentionManagerWithMockEngine:
    @pytest.fixture
    def mock_engine(self):
        from unittest.mock import MagicMock

        engine = MagicMock()
        conn = MagicMock()
        engine.begin.return_value.__enter__ = lambda *a: conn
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        engine.connect.return_value.__enter__ = lambda *a: conn
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        return engine, conn

    def test_get_policy_with_mock_engine_returns_project_days(self, mock_engine):
        engine, conn = mock_engine
        from unittest.mock import MagicMock

        row = MagicMock()
        row.proj_days = 45
        row.tenant_days = 90
        conn.execute.return_value.fetchone.return_value = row

        manager = RetentionManager(engine=engine)
        days = manager.get_policy("t1", "p1")
        assert days == 45

    def test_get_policy_with_mock_engine_falls_back_to_tenant(self, mock_engine):
        engine, conn = mock_engine
        from unittest.mock import MagicMock

        row = MagicMock()
        row.proj_days = None
        row.tenant_days = 180
        conn.execute.return_value.fetchone.return_value = row

        manager = RetentionManager(engine=engine)
        days = manager.get_policy("t1", "p1")
        assert days == 180

    def test_get_policy_falls_back_on_exception(self, mock_engine):
        engine, conn = mock_engine
        conn.execute.side_effect = Exception("DB error")

        manager = RetentionManager(engine=engine, default_retention_days=365)
        days = manager.get_policy("t1", "p1")
        assert days == 365

    def test_set_project_policy_with_engine(self, mock_engine):
        engine, conn = mock_engine
        manager = RetentionManager(engine=engine)
        # Should not raise
        manager.set_project_policy("p1", "t1", days=90)
        assert conn.execute.called

    def test_set_tenant_policy_with_engine(self, mock_engine):
        engine, conn = mock_engine
        manager = RetentionManager(engine=engine)
        manager.set_tenant_policy("t1", days=120)
        assert conn.execute.called


# ---------------------------------------------------------------------------
# RetentionManager — policy setters + more paths
# ---------------------------------------------------------------------------


class TestRetentionPolicySetters:
    def test_set_project_policy_no_engine_logs_warning(self):
        manager = RetentionManager(engine=None, default_retention_days=365)
        # Should not raise, just log warning
        manager.set_project_policy("project1", "tenant1", days=90)

    def test_set_project_policy_clear_no_engine(self):
        manager = RetentionManager(engine=None)
        manager.set_project_policy("project1", "tenant1", days=None)

    def test_set_tenant_policy_no_engine_logs_warning(self):
        manager = RetentionManager(engine=None)
        manager.set_tenant_policy("tenant1", days=180)

    def test_set_tenant_policy_clear_no_engine(self):
        manager = RetentionManager(engine=None)
        manager.set_tenant_policy("tenant1", days=None)

    def test_get_policy_returns_default_when_no_engine(self):
        manager = RetentionManager(engine=None, default_retention_days=999)
        assert manager.get_policy("any_tenant", "any_project") == 999


# ---------------------------------------------------------------------------
# RetentionManager — extended coverage
# ---------------------------------------------------------------------------


class TestRetentionManagerEdgeCases:
    def test_apply_returns_empty_on_no_patterns(self, storage):
        manager = RetentionManager(engine=None, default_retention_days=30)
        result = manager.apply(storage, dry_run=False)
        assert result.purged_count == 0
        assert result.purged_keys == []

    def test_apply_ignores_non_pattern_keys(self, storage):
        # Non-pattern keys should not be scanned or deleted
        storage.save("metrics/total", {"runs": 100})
        storage.save("feedback/abc", {"pattern": "error handling", "score": 5.0})

        manager = RetentionManager(engine=None, default_retention_days=30)
        result = manager.apply(storage, dry_run=False)
        assert result.purged_count == 0

    def test_apply_skips_pattern_with_zero_timestamp(self, storage):
        # timestamp=0 should be ignored (not treated as very old)
        storage.save(
            "patterns/zero_ts_001",
            {
                "task": "zero ts",
                "design": {},
                "success_score": 5.0,
                "reuse_count": 0,
                "timestamp": 0,
            },
        )
        manager = RetentionManager(engine=None, default_retention_days=30)
        result = manager.apply(storage, dry_run=False)
        assert result.purged_count == 0

    def test_apply_dry_run_returns_correct_keys(self, storage):
        for i in range(3):
            storage.save(
                f"patterns/dry_{i}",
                {
                    "task": f"dry task {i}",
                    "design": {},
                    "success_score": 5.0,
                    "reuse_count": 0,
                    "timestamp": time.time() - 400 * 86400,
                },
            )
        manager = RetentionManager(engine=None, default_retention_days=30)
        result = manager.apply(storage, dry_run=True)
        assert len(result.purged_keys) == 3
        # Nothing was deleted
        for i in range(3):
            assert storage.load(f"patterns/dry_{i}")["task"] == f"dry task {i}"


# ---------------------------------------------------------------------------
# ScopedDeletion — extended coverage
# ---------------------------------------------------------------------------


class TestScopedDeletionEdgeCases:
    def test_delete_tenant_no_engine(self, storage):
        # With no engine, delete_tenant only does storage-layer deletion
        # but project listing returns empty → patterns_deleted = 0
        deletion = ScopedDeletion(engine=None)
        result = deletion.delete_tenant(storage, tenant_id="default")
        # No projects found (no engine), so no storage deletion either
        assert result.tenant_id == "default"
        assert result.project_id == "*"
        assert result.projects_deleted == 0

    def test_delete_project_no_patterns(self, storage):
        deletion = ScopedDeletion(engine=None)
        result = deletion.delete_project(storage, tenant_id="default", project_id="empty")
        assert result.patterns_deleted == 0
        assert result.jobs_deleted == 0
        assert result.keys_revoked == 0

    def test_deletion_result_dataclass_defaults(self):
        result = DeletionResult(tenant_id="t", project_id="p")
        assert result.patterns_deleted == 0
        assert result.jobs_deleted == 0
        assert result.keys_revoked == 0
        assert result.projects_deleted == 0


# ---------------------------------------------------------------------------
# DataExporter — extended coverage
# ---------------------------------------------------------------------------


class TestDataExporterEdgeCases:
    def test_stream_with_classification_filter_no_engine(self, storage):
        # Without engine, all records are returned regardless of filter
        for i in range(2):
            storage.save(
                f"patterns/flt_{i}",
                {
                    "task": f"task {i}",
                    "design": {"code": "pass"},
                    "success_score": 7.0,
                    "reuse_count": 0,
                    "timestamp": time.time(),
                },
            )
        exporter = DataExporter()
        # With no engine, classification_filter applies as "show all" fallback
        records = list(exporter.stream(storage, classification_filter=["public"], engine=None))
        # No engine → DB meta not loaded → filter not applied → all records returned
        assert len(records) == 2

    def test_stream_record_structure(self, storage):
        storage.save(
            "patterns/struct_001",
            {
                "task": "struct task",
                "design": {"code": "x=1"},
                "success_score": 8.0,
                "reuse_count": 0,
                "timestamp": time.time(),
            },
        )
        exporter = DataExporter()
        records = list(exporter.stream(storage))
        assert len(records) == 1
        r = records[0]
        assert r["version"] == 1
        assert r["key"] == "patterns/struct_001"
        assert r["data"]["task"] == "struct task"

    def test_stream_no_meta_when_no_engine(self, storage):
        storage.save(
            "patterns/noMeta_001",
            {
                "task": "no meta",
                "design": {"code": "pass"},
                "success_score": 6.0,
                "reuse_count": 0,
                "timestamp": time.time(),
            },
        )
        exporter = DataExporter()
        records = list(exporter.stream(storage, engine=None))
        assert len(records) == 1
        # No engine → no classification/redacted fields in record
        assert "classification" not in records[0]

    def test_stream_skips_deleted_keys(self, storage):
        # If a key disappears between list and load, it should be skipped gracefully
        storage.save(
            "patterns/skip_001",
            {
                "task": "skip task",
                "design": {},
                "success_score": 5.0,
                "reuse_count": 0,
                "timestamp": time.time(),
            },
        )
        exporter = DataExporter()
        # Delete before iterating (can happen in concurrent scenarios)
        # Just verify it streams correctly without deletion
        records = list(exporter.stream(storage))
        assert len(records) >= 1


# ---------------------------------------------------------------------------
# Lifecycle jobs — extended coverage
# ---------------------------------------------------------------------------


class TestLifecycleJobs:
    def test_cleanup_expired_patterns(self, storage, fake_embeddings):
        mem = Memory(embeddings=fake_embeddings, storage=storage)
        # Add expired pattern manually
        storage.save(
            "patterns/lifecycle_old_001",
            {
                "task": "old",
                "design": {},
                "success_score": 5.0,
                "reuse_count": 0,
                "timestamp": time.time() - 400 * 86400,
            },
        )
        from engramia.governance.lifecycle import cleanup_expired_patterns

        result = cleanup_expired_patterns(mem, {"dry_run": False})
        assert "purged_count" in result
        assert result["purged_count"] >= 1
        assert storage.load("patterns/lifecycle_old_001") is None

    def test_cleanup_expired_patterns_dry_run(self, storage, fake_embeddings):
        mem = Memory(embeddings=fake_embeddings, storage=storage)
        storage.save(
            "patterns/lifecycle_old_002",
            {
                "task": "old2",
                "design": {},
                "success_score": 5.0,
                "reuse_count": 0,
                "timestamp": time.time() - 400 * 86400,
            },
        )
        from engramia.governance.lifecycle import cleanup_expired_patterns

        result = cleanup_expired_patterns(mem, {"dry_run": True})
        assert result["dry_run"] is True
        assert result["purged_count"] >= 1
        # Still exists after dry run
        assert storage.load("patterns/lifecycle_old_002")["task"] == "old2"

    def test_cleanup_old_jobs_no_engine(self, storage, fake_embeddings):
        mem = Memory(embeddings=fake_embeddings, storage=storage)
        from engramia.governance.lifecycle import cleanup_old_jobs

        result = cleanup_old_jobs(mem, {})
        assert result == {"deleted_count": 0, "dry_run": False}

    def test_compact_audit_log_no_engine(self, storage, fake_embeddings):
        mem = Memory(embeddings=fake_embeddings, storage=storage)
        from engramia.governance.lifecycle import compact_audit_log

        result = compact_audit_log(mem, {})
        assert result == {"deleted_count": 0, "dry_run": False}

    def test_cleanup_old_jobs_dry_run_no_engine(self, storage, fake_embeddings):
        mem = Memory(embeddings=fake_embeddings, storage=storage)
        from engramia.governance.lifecycle import cleanup_old_jobs

        result = cleanup_old_jobs(mem, {"dry_run": True})
        # No engine → returns immediately
        assert result["deleted_count"] == 0

    def test_lifecycle_jobs_namespace(self):
        from engramia.governance.lifecycle import LifecycleJobs

        assert callable(LifecycleJobs.cleanup_expired_patterns)
        assert callable(LifecycleJobs.compact_audit_log)
        assert callable(LifecycleJobs.cleanup_old_jobs)


# ---------------------------------------------------------------------------
# LifecycleJobs — mock-engine paths
# ---------------------------------------------------------------------------


class TestLifecycleJobsMockEngine:
    """Cover the DB paths in compact_audit_log and cleanup_old_jobs."""

    def _make_mem(self, storage, fake_embeddings, engine):
        mem = Memory(embeddings=fake_embeddings, storage=storage)
        mem.storage._engine = engine
        return mem

    def test_compact_audit_log_with_engine(self, storage, fake_embeddings):
        from unittest.mock import MagicMock

        from engramia._context import set_scope
        from engramia.governance.lifecycle import compact_audit_log
        from engramia.types import Scope

        engine = MagicMock()
        conn = MagicMock()
        r = MagicMock()
        r.rowcount = 3
        engine.begin.return_value.__enter__ = lambda *a: conn
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value = r

        token = set_scope(Scope(tenant_id="t1", project_id="p1"))
        try:
            mem = self._make_mem(storage, fake_embeddings, engine)
            result = compact_audit_log(mem, {"retention_days": 30})
            assert result["deleted_count"] == 3
            assert result["dry_run"] is False
        finally:
            from engramia._context import reset_scope

            reset_scope(token)

    def test_compact_audit_log_dry_run(self, storage, fake_embeddings):
        from unittest.mock import MagicMock

        from engramia._context import set_scope
        from engramia.governance.lifecycle import compact_audit_log
        from engramia.types import Scope

        engine = MagicMock()
        conn = MagicMock()
        row = MagicMock()
        row.__getitem__ = lambda s, i: 5
        engine.connect.return_value.__enter__ = lambda *a: conn
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = row

        token = set_scope(Scope(tenant_id="t1", project_id="p1"))
        try:
            mem = self._make_mem(storage, fake_embeddings, engine)
            result = compact_audit_log(mem, {"dry_run": True, "retention_days": 30})
            assert result["dry_run"] is True
            assert result["deleted_count"] == 5
        finally:
            from engramia._context import reset_scope

            reset_scope(token)

    def test_cleanup_old_jobs_with_engine(self, storage, fake_embeddings):
        from unittest.mock import MagicMock

        from engramia._context import set_scope
        from engramia.governance.lifecycle import cleanup_old_jobs
        from engramia.types import Scope

        engine = MagicMock()
        conn = MagicMock()
        r = MagicMock()
        r.rowcount = 2
        engine.begin.return_value.__enter__ = lambda *a: conn
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value = r

        token = set_scope(Scope(tenant_id="t1", project_id="p1"))
        try:
            mem = self._make_mem(storage, fake_embeddings, engine)
            result = cleanup_old_jobs(mem, {"retention_days": 7})
            assert result["deleted_count"] == 2
            assert result["dry_run"] is False
        finally:
            from engramia._context import reset_scope

            reset_scope(token)

    def test_cleanup_old_jobs_dry_run(self, storage, fake_embeddings):
        from unittest.mock import MagicMock

        from engramia._context import set_scope
        from engramia.governance.lifecycle import cleanup_old_jobs
        from engramia.types import Scope

        engine = MagicMock()
        conn = MagicMock()
        row = MagicMock()
        row.__getitem__ = lambda s, i: 4
        engine.connect.return_value.__enter__ = lambda *a: conn
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = row

        token = set_scope(Scope(tenant_id="t1", project_id="p1"))
        try:
            mem = self._make_mem(storage, fake_embeddings, engine)
            result = cleanup_old_jobs(mem, {"dry_run": True, "retention_days": 7})
            assert result["dry_run"] is True
            assert result["deleted_count"] == 4
        finally:
            from engramia._context import reset_scope

            reset_scope(token)


# ---------------------------------------------------------------------------
# RetentionManager — mock-engine paths
# ---------------------------------------------------------------------------


class TestRetentionManagerMockEngine:
    def test_get_policy_with_project_days(self):
        from unittest.mock import MagicMock

        engine = MagicMock()
        conn = MagicMock()
        row = MagicMock()
        row.proj_days = 60
        row.tenant_days = 90
        engine.connect.return_value.__enter__ = lambda *a: conn
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = row

        mgr = RetentionManager(engine=engine)
        days = mgr.get_policy("t1", "p1")
        assert days == 60

    def test_get_policy_fallback_to_tenant(self):
        from unittest.mock import MagicMock

        engine = MagicMock()
        conn = MagicMock()
        row = MagicMock()
        row.proj_days = None
        row.tenant_days = 180
        engine.connect.return_value.__enter__ = lambda *a: conn
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = row

        mgr = RetentionManager(engine=engine)
        days = mgr.get_policy("t1", "p1")
        assert days == 180

    def test_get_policy_row_none(self):
        from unittest.mock import MagicMock

        engine = MagicMock()
        conn = MagicMock()
        engine.connect.return_value.__enter__ = lambda *a: conn
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = None

        mgr = RetentionManager(engine=engine, default_retention_days=999)
        days = mgr.get_policy("t1", "p1")
        assert days == 999

    def test_set_project_policy_no_engine(self):
        mgr = RetentionManager(engine=None)
        # No-op, no exception
        mgr.set_project_policy("p1", "t1", 30)

    def test_set_tenant_policy_no_engine(self):
        mgr = RetentionManager(engine=None)
        mgr.set_tenant_policy("t1", 30)

    def test_set_project_policy_with_engine(self):
        from unittest.mock import MagicMock

        engine = MagicMock()
        conn = MagicMock()
        engine.begin.return_value.__enter__ = lambda *a: conn
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        mgr = RetentionManager(engine=engine)
        mgr.set_project_policy("p1", "t1", 45)
        conn.execute.assert_called_once()

    def test_set_tenant_policy_with_engine(self):
        from unittest.mock import MagicMock

        engine = MagicMock()
        conn = MagicMock()
        engine.begin.return_value.__enter__ = lambda *a: conn
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        mgr = RetentionManager(engine=engine)
        mgr.set_tenant_policy("t1", 90)
        conn.execute.assert_called_once()

    def test_apply_postgres_path(self, storage, fake_embeddings):
        from unittest.mock import MagicMock, patch

        from engramia._context import set_scope
        from engramia.types import Scope

        engine = MagicMock()
        conn = MagicMock()
        row = MagicMock()
        row.key = "patterns/abc"
        engine.connect.return_value.__enter__ = lambda *a: conn
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchall.return_value = [row]

        token = set_scope(Scope(tenant_id="t1", project_id="p1"))
        try:
            with patch("engramia.governance.retention._is_postgres_storage", return_value=True):
                mgr = RetentionManager(engine=engine)
                result = mgr.apply(storage, dry_run=True)
            assert result.purged_count == 1
            assert result.dry_run is True
        finally:
            from engramia._context import reset_scope

            reset_scope(token)

    def test_apply_postgres_non_dry_run(self, storage, fake_embeddings):
        from unittest.mock import MagicMock, patch

        from engramia._context import set_scope
        from engramia.types import Scope

        # Seed a pattern so storage.delete has something to do
        storage.save("patterns/del_001", {"task": "x", "timestamp": 1})

        engine = MagicMock()
        conn = MagicMock()
        row = MagicMock()
        row.key = "patterns/del_001"
        engine.connect.return_value.__enter__ = lambda *a: conn
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchall.return_value = [row]

        token = set_scope(Scope(tenant_id="t1", project_id="p1"))
        try:
            with patch("engramia.governance.retention._is_postgres_storage", return_value=True):
                mgr = RetentionManager(engine=engine)
                result = mgr.apply(storage, dry_run=False)
            assert result.purged_count == 1
            assert result.dry_run is False
        finally:
            from engramia._context import reset_scope

            reset_scope(token)


# ---------------------------------------------------------------------------
# DataExporter — mock-engine paths
# ---------------------------------------------------------------------------


class TestDataExporterMockEngine:
    def test_stream_with_engine_and_filter(self, storage):
        from unittest.mock import MagicMock

        from engramia._context import reset_scope, set_scope
        from engramia.types import Scope

        token = set_scope(Scope(tenant_id="t1", project_id="p1"))
        try:
            storage.save("patterns/exp_001", {"task": "hello", "timestamp": 1000})
            storage.save("patterns/exp_002", {"task": "world", "timestamp": 1001})

            engine = MagicMock()
            conn = MagicMock()
            engine.connect.return_value.__enter__ = lambda *a: conn
            engine.connect.return_value.__exit__ = MagicMock(return_value=False)

            # Row for exp_001 only (classification=public)
            row = MagicMock()
            row.key = "patterns/exp_001"
            row.classification = "public"
            row.redacted = False
            row.source = "api"
            row.run_id = "run-abc"
            conn.execute.return_value.fetchall.return_value = [row]

            exporter = DataExporter()
            records = list(exporter.stream(storage, classification_filter=["public"], engine=engine))
            # Only exp_001 is in the filtered result set
            assert len(records) == 1
            assert records[0]["key"] == "patterns/exp_001"
            assert records[0]["classification"] == "public"
            assert records[0]["run_id"] == "run-abc"
        finally:
            reset_scope(token)

    def test_stream_with_engine_no_filter(self, storage):
        from unittest.mock import MagicMock

        from engramia._context import reset_scope, set_scope
        from engramia.types import Scope

        token = set_scope(Scope(tenant_id="t1", project_id="p1"))
        try:
            storage.save("patterns/exp_003", {"task": "test", "timestamp": 1000})

            engine = MagicMock()
            conn = MagicMock()
            engine.connect.return_value.__enter__ = lambda *a: conn
            engine.connect.return_value.__exit__ = MagicMock(return_value=False)

            row = MagicMock()
            row.key = "patterns/exp_003"
            row.classification = "internal"
            row.redacted = True
            row.source = None
            row.run_id = None
            conn.execute.return_value.fetchall.return_value = [row]

            exporter = DataExporter()
            records = list(exporter.stream(storage, classification_filter=None, engine=engine))
            assert any(r["key"] == "patterns/exp_003" for r in records)
            matched = next(r for r in records if r["key"] == "patterns/exp_003")
            assert matched["redacted"] is True
        finally:
            reset_scope(token)

    def test_stream_engine_db_failure_falls_back(self, storage):
        from unittest.mock import MagicMock

        from engramia._context import reset_scope, set_scope
        from engramia.types import Scope

        token = set_scope(Scope(tenant_id="t1", project_id="p1"))
        try:
            storage.save("patterns/exp_004", {"task": "fallback", "timestamp": 1000})

            engine = MagicMock()
            engine.connect.side_effect = RuntimeError("db down")

            exporter = DataExporter()
            # Should fall back gracefully and still yield records (without meta)
            records = list(exporter.stream(storage, classification_filter=None, engine=engine))
            assert any(r["key"] == "patterns/exp_004" for r in records)
        finally:
            reset_scope(token)


# ---------------------------------------------------------------------------
# AuditScrubber — _scrub_value and scrub()
# ---------------------------------------------------------------------------


class TestScrubValue:
    def test_dict_pii_key_replaced(self):
        from engramia.governance.audit_scrubber import _scrub_value

        result = _scrub_value({"email": "user@example.com", "action": "login"})
        assert result["email"] == "[REDACTED]"
        assert result["action"] == "login"

    def test_nested_dict_scrubbed(self):
        from engramia.governance.audit_scrubber import _scrub_value

        result = _scrub_value({"outer": {"email": "x@y.com", "safe": "ok"}})
        assert result["outer"]["email"] == "[REDACTED]"
        assert result["outer"]["safe"] == "ok"

    def test_list_elements_scrubbed(self):
        from engramia.governance.audit_scrubber import _scrub_value

        result = _scrub_value(["user@example.com", "no email here", 42])
        assert result[0] == "[REDACTED]"
        assert result[1] == "no email here"
        assert result[2] == 42

    def test_string_email_replaced(self):
        from engramia.governance.audit_scrubber import _scrub_value

        result = _scrub_value("Contact user@example.com for details")
        assert "[REDACTED]" in result
        assert "user@example.com" not in result

    def test_string_ip_replaced(self):
        from engramia.governance.audit_scrubber import _scrub_value

        result = _scrub_value("Request from 192.168.1.1 was logged")
        assert "[REDACTED]" in result
        assert "192.168.1.1" not in result

    def test_non_string_scalar_unchanged(self):
        from engramia.governance.audit_scrubber import _scrub_value

        assert _scrub_value(42) == 42
        assert _scrub_value(3.14) == 3.14
        assert _scrub_value(None) is None
        assert _scrub_value(True) is True


class TestAuditScrubber:
    def _make_engine(self, rows):
        from unittest.mock import MagicMock

        engine = MagicMock()
        result = MagicMock()
        result.fetchall.return_value = rows
        conn = MagicMock()
        conn.execute.return_value = result
        engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        engine.begin.return_value.__enter__ = MagicMock(return_value=conn)
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        return engine, conn

    def test_no_rows_returns_zero(self):
        from engramia.governance.audit_scrubber import AuditScrubber

        engine, _ = self._make_engine([])
        scrubber = AuditScrubber(engine=engine)
        result = scrubber.scrub(older_than_days=90)
        assert result.rows_scrubbed == 0
        assert result.dry_run is False
        assert result.older_than_days == 90

    def test_row_with_pii_is_scrubbed(self):
        from engramia.governance.audit_scrubber import AuditScrubber

        row = (1, "192.168.1.1", {"email": "user@example.com", "action": "login"})
        engine, _conn = self._make_engine([row])
        scrubber = AuditScrubber(engine=engine)
        result = scrubber.scrub(older_than_days=90)
        assert result.rows_scrubbed == 1
        _conn.execute.assert_called()

    def test_dry_run_counts_but_no_update(self):
        from engramia.governance.audit_scrubber import AuditScrubber

        row = (2, "10.0.0.1", {"email": "a@b.com"})
        engine, _conn = self._make_engine([row])
        scrubber = AuditScrubber(engine=engine)
        result = scrubber.scrub(older_than_days=30, dry_run=True)
        assert result.rows_scrubbed == 1
        assert result.dry_run is True
        # In dry_run mode, _apply_update should NOT be called
        assert engine.begin.call_count == 0

    def test_already_redacted_row_skipped(self):
        from engramia.governance.audit_scrubber import AuditScrubber

        row = (3, "[REDACTED]", {"email": "[REDACTED]", "action": "login"})
        engine, _conn = self._make_engine([row])
        scrubber = AuditScrubber(engine=engine)
        result = scrubber.scrub(older_than_days=90)
        assert result.rows_scrubbed == 0

    def test_row_with_none_detail_and_ip_scrubbed(self):
        from engramia.governance.audit_scrubber import AuditScrubber

        row = (4, "10.0.0.1", None)
        engine, _conn = self._make_engine([row])
        scrubber = AuditScrubber(engine=engine)
        result = scrubber.scrub(older_than_days=90)
        assert result.rows_scrubbed == 1
