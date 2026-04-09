# Engramia Documentation

**Reusable execution memory and evaluation infrastructure for AI agent frameworks.**

Engramia gives any agent framework the ability to learn from every run — remember
what works, forget what does not, reuse proven solutions, and improve over time.

---

## Quick Start

- [Getting Started](getting-started.md) — install, configure, and run your first learn/recall cycle
- [Concepts & Architecture](concepts.md) — how memory, evaluation, and composition work together
- [Pricing](pricing.md) — plans for personal, cloud, and enterprise use

## Using Engramia

- [User Guide](user-guide.md) — complete usage guide (learn, recall, compose, feedback, aging)
- [CLI Reference](cli.md) — `engramia init / serve / status / recall / aging`
- [Providers](providers.md) — configure LLM, embedding, and storage providers
- [ROI Calibration](roi-calibration.md) — interpret and improve your composite ROI score

## API Reference

- [Python API](api-reference.md) — `Memory`, `learn()`, `recall()`, `compose()`, `evolve()`
- [REST API](rest-api.md) — FastAPI endpoints with Swagger UI
- [API Stability](api-stability.md) — stability guarantees and deprecation policy
- [API Versioning](api-versioning.md) — versioning strategy

## Integrations

Connect Engramia to your agent framework:

- [LangChain](integrations/langchain.md) — callback-based auto-learn and auto-recall
- [CrewAI](integrations/crewai.md)
- [Anthropic Agents](integrations/anthropic-agents.md)
- [OpenAI Agents](integrations/openai-agents.md)
- [AutoGen](integrations/autogen.md)
- [PydanticAI](integrations/pydantic-ai.md)
- [MCP Server](integrations/mcp.md) — Claude Desktop, Cursor, Windsurf
- [Webhook SDK](integrations/webhook.md) — lightweight HTTP client (no dependencies)
- [Examples](integrations/examples.md) — end-to-end integration examples

## Administration

- [Admin Guide](admin-guide.md) — dashboard, tenant management, RBAC
- [Environment Variables](environment-variables.md) — full reference of all `ENGRAMIA_*` vars
- [Monitoring](monitoring.md) — Prometheus metrics, Grafana dashboards, alerting

## Deployment & Operations

- [Deployment Guide](deployment.md) — Docker Compose, Hetzner, production setup
- [Production Hardening](production-hardening.md) — TLS, rate limiting, secrets management
- [Backup & Restore](backup-restore.md) — backup strategy, RTO/RPO targets, restore procedures
- [Disaster Recovery](disaster-recovery.md) — DR plan and recovery procedures
- [Data Handling](data-handling.md) — how Engramia processes and stores data
- [Embedding Reindex](embedding-reindex.md) — reindex embeddings after model change
- [HNSW Maintenance](hnsw-maintenance.md) — pgvector index maintenance

## Security

- [Security Overview](security.md) — summary of measures and links to detailed docs
- [Security Architecture](security-architecture.md) — threat model and defense layers
- [SOC 2 Controls](soc2-controls.md) — SOC 2 Type II control mapping
- [Incident Response Plan](incident-response-plan.md) — detection, response, GDPR breach process

For the full security policy, vulnerability reporting, and production checklist,
see [SECURITY.md](https://github.com/engramia/engramia/blob/main/SECURITY.md)
in the repository root.

## Architecture

- [Admin Dashboard](architecture/admin-dashboard.md) — Next.js dashboard architecture

## Runbooks

Operational playbooks for common incidents and maintenance tasks:

- [Runbooks Overview](runbooks/README.md)
- [Deploy Checklist](runbooks/deploy-checklist.md) | [Deploy Rollback](runbooks/deploy-rollback.md)
- [API Key Rotation](runbooks/api-key-rotation.md) | [Certificate Renewal](runbooks/certificate-renewal.md)
- [Database Recovery](runbooks/database-recovery.md) | [Disk Full](runbooks/disk-full.md)
- [High Error Rates](runbooks/high-error-rates.md) | [High Latency](runbooks/high-latency.md)
- [Job Queue Issues](runbooks/job-queue-issues.md) | [LLM Provider Outage](runbooks/llm-provider-outage.md)
- [Maintenance Mode](runbooks/maintenance-mode.md) | [Rate Limit Tuning](runbooks/rate-limit-tuning.md)

## Legal

- [Terms of Service](legal/TERMS_OF_SERVICE.md)
- [Acceptable Use Policy](legal/ACCEPTABLE_USE_POLICY.md)
- [Privacy Policy](legal/PRIVACY_POLICY.md)
- [Cookie Policy](legal/COOKIE_POLICY.md)
- [DPA Template](legal/DPA_TEMPLATE.md)
- [Commercial License](legal/COMMERCIAL_LICENSE_TEMPLATE.md)
- [Sub-processors](legal/SUBPROCESSORS.md)
- [Dependency Licenses](legal/DEPENDENCY_LICENSES.md)
- [Processing Activities (ROPA)](legal/ROPA.md)

---

## License

[Business Source License 1.1](https://github.com/engramia/engramia/blob/main/LICENSE.txt) —
source code is publicly readable. Commercial use requires a
[commercial license](legal/COMMERCIAL_LICENSE_TEMPLATE.md).
After 2030, the code converts to Apache 2.0.

Contact: support@engramia.dev
