# Operational Runbooks — Engramia

Generic troubleshooting guides for self-hosted Engramia deployments.

> **Operator-specific runbooks** (with SSH commands, deploy paths, and infrastructure details)
> are maintained in the private [engramia-ops](https://github.com/engramia/engramia-ops) repository.

## Runbooks

| Runbook | When to use |
|---------|-------------|
| [deploy-checklist.md](deploy-checklist.md) | Standard deploy procedure, health checks, rollback |
| [database-recovery.md](database-recovery.md) | PostgreSQL unhealthy, data loss suspected |
| [high-error-rates.md](high-error-rates.md) | Elevated 5xx responses, error classification |
| [job-queue-issues.md](job-queue-issues.md) | Jobs stuck in pending/running, backlog growing |
| [llm-provider-outage.md](llm-provider-outage.md) | LLM-dependent endpoints returning 503 |
