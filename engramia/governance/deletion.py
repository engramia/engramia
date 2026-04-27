# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Scoped deletion — GDPR Art. 17 right to erasure (Phase 5.6).

Deletes all data for a tenant or project. Audit logs are retained (scrubbed)
for security/legal reasons. API keys are revoked rather than deleted to
preserve forensic key hashes.

Usage::

    deletion = ScopedDeletion(engine=engine)
    result = deletion.delete_project(storage, tenant_id="t1", project_id="p1")
    result = deletion.delete_tenant(storage, tenant_id="t1")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from sqlalchemy import text

_log = logging.getLogger(__name__)


@dataclass
class DeletionResult:
    """Summary of a scoped deletion operation.

    Args:
        tenant_id: Tenant that was targeted.
        project_id: Project that was targeted (``"*"`` for tenant-wide deletion).
        patterns_deleted: Number of patterns (memory_data rows) removed.
        embeddings_deleted: Number of embedding vectors removed.
        jobs_deleted: Number of job records removed.
        keys_revoked: Number of API keys revoked (not deleted — key hash retained).
        projects_deleted: Number of projects soft-deleted (tenant-wide deletion only).
        cloud_users_deleted: Number of cloud_user rows soft-deleted + anonymised
            (tenant-wide deletion only — a project-scoped delete never touches
            cloud_users since users belong to tenants, not projects).
    """

    tenant_id: str
    project_id: str
    patterns_deleted: int = 0
    embeddings_deleted: int = 0
    jobs_deleted: int = 0
    keys_revoked: int = 0
    projects_deleted: int = 0
    cloud_users_deleted: int = 0


class ScopedDeletion:
    """Performs GDPR-compliant scoped data erasure.

    Cascade order:
        1. memory_embeddings (scope)
        2. memory_data (scope)
        3. jobs (scope)
        4. audit_log — detail field scrubbed; rows retained for legal basis
        5. api_keys — revoked (revoked_at set), NOT deleted (key_hash kept for forensics)
        6. projects / tenants — soft-deleted (deleted_at timestamp)

    Args:
        engine: SQLAlchemy engine. Required for DB-backed operations.
    """

    def __init__(self, engine=None) -> None:
        self._engine = engine

    def delete_project(
        self,
        storage,
        tenant_id: str,
        project_id: str,
    ) -> DeletionResult:
        """Delete all data for a single project.

        Args:
            storage: StorageBackend (used for storage-layer key deletion).
            tenant_id: Tenant the project belongs to.
            project_id: Project to delete.

        Returns:
            DeletionResult with counts of deleted/revoked records.
        """
        result = DeletionResult(tenant_id=tenant_id, project_id=project_id)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Delete storage-layer data (embeddings + pattern data)
        deleted = storage.delete_scope(tenant_id=tenant_id, project_id=project_id)
        result.patterns_deleted = deleted

        if self._engine is None:
            _log.warning("ScopedDeletion: no DB engine — only storage-layer data deleted")
            return result

        try:
            with self._engine.begin() as conn:
                # Jobs
                r = conn.execute(
                    text("DELETE FROM jobs WHERE tenant_id = :tid AND project_id = :pid"),
                    {"tid": tenant_id, "pid": project_id},
                )
                result.jobs_deleted = r.rowcount

                # API keys — revoke only (preserve key_hash for forensics).
                # RETURNING key_hash so we can invalidate the in-process auth
                # cache below; without that step revoked keys keep working
                # for up to the cache TTL (60 s) — short replay window but
                # observable in UAT.
                r = conn.execute(
                    text(
                        "UPDATE api_keys SET revoked_at = :now "
                        "WHERE tenant_id = :tid AND project_id = :pid AND revoked_at IS NULL "
                        "RETURNING key_hash"
                    ),
                    {"now": now, "tid": tenant_id, "pid": project_id},
                )
                revoked_hashes: list[str] = [row[0] for row in r.fetchall()]
                result.keys_revoked = len(revoked_hashes)

                # Audit log — scrub detail but retain rows
                conn.execute(
                    text("UPDATE audit_log SET detail = NULL WHERE tenant_id = :tid AND project_id = :pid"),
                    {"tid": tenant_id, "pid": project_id},
                )

                # Soft-delete project
                conn.execute(
                    text(
                        "UPDATE projects SET deleted_at = :now "
                        "WHERE id = :pid AND tenant_id = :tid AND deleted_at IS NULL"
                    ),
                    {"now": now, "pid": project_id, "tid": tenant_id},
                )

        except Exception as exc:
            _log.error("ScopedDeletion.delete_project DB phase failed: %s", exc)
            raise

        # Drop revoked keys from the auth cache so 401s land immediately
        # rather than waiting for the 60s TTL. Imported lazily to keep the
        # governance package free of API-layer imports for unit tests.
        if revoked_hashes:
            try:
                from engramia.api.auth import invalidate_key_cache

                for key_hash in revoked_hashes:
                    invalidate_key_cache(key_hash)
            except ImportError:
                # API layer unavailable in this runtime (e.g. CLI use).
                # Cache is in-process; if the API isn't loaded, nothing to invalidate.
                pass

        _log.warning(
            "GDPR deletion: project %s/%s — patterns=%d jobs=%d keys_revoked=%d",
            tenant_id,
            project_id,
            result.patterns_deleted,
            result.jobs_deleted,
            result.keys_revoked,
        )
        return result

    def delete_tenant(
        self,
        storage,
        tenant_id: str,
        *,
        anonymise_users: bool = False,
        deletion_reason: str | None = None,
    ) -> DeletionResult:
        """Delete all data for every project in a tenant.

        Args:
            storage: StorageBackend.
            tenant_id: Tenant to wipe.
            anonymise_users: When True, every ``cloud_users`` row in the tenant
                is soft-deleted: ``deleted_at`` is stamped, ``email`` is replaced
                with ``sha256(email)+"@deleted.engramia.dev"`` (so the unique
                index keeps holding while the original address is no longer
                derivable), ``name`` and ``password_hash`` are nulled. Default
                False preserves the existing admin-deletion behaviour where
                cloud_users rows are kept (admin uses governance API to wipe
                tenant data without dropping the human account).
            deletion_reason: Optional free-text reason from the user, persisted
                onto cloud_users.deletion_reason for analytics. Ignored when
                ``anonymise_users`` is False.

        Returns:
            DeletionResult aggregated across all projects.
        """
        aggregate = DeletionResult(tenant_id=tenant_id, project_id="*")
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        project_ids: list[str] = []
        if self._engine is not None:
            try:
                with self._engine.connect() as conn:
                    rows = conn.execute(
                        text("SELECT id FROM projects WHERE tenant_id = :tid AND deleted_at IS NULL"),
                        {"tid": tenant_id},
                    ).fetchall()
                project_ids = [row.id for row in rows]
            except Exception as exc:
                _log.error("ScopedDeletion.delete_tenant: failed to list projects: %s", exc)
                raise

        for project_id in project_ids:
            r = self.delete_project(storage, tenant_id=tenant_id, project_id=project_id)
            aggregate.patterns_deleted += r.patterns_deleted
            aggregate.jobs_deleted += r.jobs_deleted
            aggregate.keys_revoked += r.keys_revoked
            aggregate.projects_deleted += 1

        if self._engine is not None:
            try:
                with self._engine.begin() as conn:
                    if anonymise_users:
                        # The original email is replaced with
                        # ``deleted-<user_id>@deleted.engramia.dev`` — uniqueness
                        # rides on the existing UUID PK so the (email) UNIQUE
                        # index keeps holding without leaking anything about the
                        # original mailbox (a sha256 hash would be reversible
                        # against a known address dictionary).
                        # password_hash is nulled to prevent any future login
                        # attempt from succeeding even if a stale JWT or session
                        # somehow survives the JTI blocklist.
                        r = conn.execute(
                            text(
                                "UPDATE cloud_users SET "
                                "deleted_at = now(), "
                                "deletion_reason = :reason, "
                                "email = 'deleted-' || id::text || '@deleted.engramia.dev', "
                                "name = NULL, "
                                "password_hash = NULL, "
                                "provider_id = NULL "
                                "WHERE tenant_id = :tid AND deleted_at IS NULL"
                            ),
                            {"tid": tenant_id, "reason": deletion_reason},
                        )
                        aggregate.cloud_users_deleted = r.rowcount

                    conn.execute(
                        text("UPDATE tenants SET deleted_at = :now WHERE id = :tid AND deleted_at IS NULL"),
                        {"now": now, "tid": tenant_id},
                    )
            except Exception as exc:
                _log.error("ScopedDeletion.delete_tenant: failed to soft-delete tenant: %s", exc)
                raise

        _log.warning(
            "GDPR deletion: tenant %s — projects=%d patterns=%d jobs=%d keys_revoked=%d users=%d",
            tenant_id,
            aggregate.projects_deleted,
            aggregate.patterns_deleted,
            aggregate.jobs_deleted,
            aggregate.keys_revoked,
            aggregate.cloud_users_deleted,
        )
        return aggregate
