# Engramia Documentation

**Reusable execution memory and evaluation infrastructure for AI agent frameworks.**

Engramia gives any agent framework the ability to learn from every run — remember
what works, forget what does not, reuse proven solutions, and improve over time.

---

## Start here

| | |
|:--|:--|
| :material-rocket-launch:{ .lg } **[Quickstart](getting-started.md)** | Install Engramia and run your first learn/recall cycle in under 5 minutes. |
| :material-book-open-variant:{ .lg } **[Concepts](concepts.md)** | Understand how memory, evaluation, scopes, and composition work together. |
| :material-api:{ .lg } **[API Reference](api-reference.md)** | Python SDK, REST endpoints, stability guarantees, and versioning. |
| :material-puzzle:{ .lg } **[Integrations](integrations/examples.md)** | Connect to LangChain, CrewAI, Anthropic Agents, OpenAI Agents, MCP, and more. |
| :material-currency-usd:{ .lg } **[Pricing](pricing.md)** | Sandbox (free), Pro, Team, Enterprise plans. |
| :material-cog:{ .lg } **[CLI](cli.md)** | `engramia init / serve / status / recall / aging` |

---

## By role

### I'm building an agent

1. [Getting Started](getting-started.md) — install, configure, first learn/recall
2. [User Guide](user-guide.md) — learn, recall, compose, feedback, aging
3. [Integrations](integrations/examples.md) — plug into your framework
4. [CLI Reference](cli.md) — `engramia init / serve / status / recall / aging`
5. [Providers](providers.md) — configure LLM, embedding, and storage backends

### I'm evaluating Engramia

1. [Concepts & Architecture](concepts.md) — how it works
2. [Pricing](pricing.md) — Sandbox (free), Pro, Team, Enterprise
3. [REST API](rest-api.md) — full endpoint reference
4. [API Stability](api-stability.md) — stability guarantees and deprecation policy

### I'm running Engramia in production

1. [Deployment Guide](deployment.md) — Docker Compose, Hetzner, production setup
2. [Production Hardening](production-hardening.md) — TLS, rate limiting, secrets
3. [Environment Variables](environment-variables.md) — all `ENGRAMIA_*` vars
4. [Admin Guide](admin-guide.md) — dashboard, tenant management, RBAC
5. [Monitoring](monitoring.md) — Prometheus metrics, Grafana, alerting
6. [Backup & Restore](backup-restore.md) — backup strategy, RTO/RPO, restore
7. [ROI Calibration](roi-calibration.md) — interpret and improve your ROI score

---

## API Reference

| | |
|---|---|
| [Python API](api-reference.md) | `Memory`, `learn()`, `recall()`, `compose()`, `evolve()` |
| [REST API](rest-api.md) | FastAPI endpoints — learn, recall, evaluate, keys, jobs, governance |
| [API Stability](api-stability.md) | Stability tiers and deprecation policy |
| [API Versioning](api-versioning.md) | Versioning strategy |

## Integrations

| Framework | Link |
|---|---|
| LangChain | [Callback-based auto-learn and recall](integrations/langchain.md) |
| CrewAI | [CrewAI integration](integrations/crewai.md) |
| Anthropic Agents | [Claude agent memory](integrations/anthropic-agents.md) |
| OpenAI Agents | [OpenAI agent memory](integrations/openai-agents.md) |
| AutoGen | [AutoGen integration](integrations/autogen.md) |
| PydanticAI | [PydanticAI integration](integrations/pydantic-ai.md) |
| MCP Server | [Claude Desktop, Cursor, Windsurf](integrations/mcp.md) |
| Webhook SDK | [Lightweight HTTP client](integrations/webhook.md) |

## Security

- [Security Overview](security.md) — summary of measures
- [Security Architecture](security-architecture.md) — threat model and defense layers
- [SOC 2 Controls](soc2-controls.md) — SOC 2 Type II control mapping
- [Incident Response Plan](incident-response-plan.md) — detection, response, GDPR breach

## Operations

- [Disaster Recovery](disaster-recovery.md) — DR plan and recovery procedures
- [Data Handling](data-handling.md) — how Engramia processes and stores data
- [Embedding Reindex](embedding-reindex.md) — reindex after model change
- [HNSW Maintenance](hnsw-maintenance.md) — pgvector index maintenance

## Runbooks

Operational playbooks for common incidents and maintenance:

- [Runbooks Overview](runbooks/README.md)
- [Deploy Checklist](runbooks/deploy-checklist.md) · [Rollback](runbooks/deploy-rollback.md)
- [API Key Rotation](runbooks/api-key-rotation.md) · [Certificate Renewal](runbooks/certificate-renewal.md)
- [Database Recovery](runbooks/database-recovery.md) · [Disk Full](runbooks/disk-full.md)
- [High Error Rates](runbooks/high-error-rates.md) · [High Latency](runbooks/high-latency.md)
- [Job Queue Issues](runbooks/job-queue-issues.md) · [LLM Provider Outage](runbooks/llm-provider-outage.md)
- [Maintenance Mode](runbooks/maintenance-mode.md) · [Rate Limit Tuning](runbooks/rate-limit-tuning.md)

## Legal

- [Terms of Service](legal/TERMS_OF_SERVICE.md) · [Privacy Policy](legal/PRIVACY_POLICY.md) · [Cookie Policy](legal/COOKIE_POLICY.md)
- [DPA Template](legal/DPA_TEMPLATE.md) · [Commercial License](legal/COMMERCIAL_LICENSE_TEMPLATE.md)
- [Acceptable Use Policy](legal/ACCEPTABLE_USE_POLICY.md) · [Sub-processors](legal/SUBPROCESSORS.md)
- [Dependency Licenses](legal/DEPENDENCY_LICENSES.md) · [Processing Activities (ROPA)](legal/ROPA.md)

---

**License:** [Business Source License 1.1](https://github.com/engramia/engramia/blob/main/LICENSE.txt) —
source code is publicly readable. Commercial use requires a
[commercial license](legal/COMMERCIAL_LICENSE_TEMPLATE.md).

Contact: [support@engramia.dev](mailto:support@engramia.dev)
