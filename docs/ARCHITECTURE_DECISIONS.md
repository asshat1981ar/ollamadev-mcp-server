# Architecture Decisions Log

Date: 2026-08-03
Author: Program Manager (synthesized from 00-master-architecture.md)

This file captures the key architecture decisions extracted from the Master Architecture document and related phase documents. Use this as the canonical decisions index; detailed rationale and alternatives are in 00-master-architecture.md.

Decisions
---------
- DD1: Use Python `logging` + `structlog`
  - Rationale: Standard library + proven structured output; enables structured logs with minimal maintenance.
  - Alternatives: Custom JSON logger (rejected due to maintenance overhead).

- DD2: Use simple internal auth (not OAuth) for tool access
  - Rationale: Simpler to integrate for single-service deployments and aligns with OllamaDev patterns.
  - Alternatives: OAuth2 — considered overkill for single-user deployments; may be revisited if multi-tenant.

- DD3: Use Pydantic v2 for validation
  - Rationale: Already a transitive dependency; provides strong validation and typing benefits.
  - Alternatives: marshmallow, attrs.

- DD4: Use Prometheus metrics format + Grafana for dashboards
  - Rationale: Industry standard and wide compatibility.
  - Alternatives: OpenMetrics or custom metrics.

- DD5: Use OpenTelemetry for distributed tracing
  - Rationale: Vendor-neutral and Python SDK maturity.
  - Alternatives: Jaeger client or Zipkin (less flexibility).

- DD6: Pin MCP SDK v2 beta for current work, postpone stable upgrade
  - Rationale: Stability for current migration; upgrade later after validation.
  - Alternatives: Immediate upgrade to stable (may introduce breaking changes).

- DD7: Use feature flags per-phase for safe rollout
  - Rationale: Safe incremental rollout and easy rollback.
  - Alternatives: Big-bang release (rejected as too risky).

How to propose new decisions
---------------------------
1. Open an ADR-style brief (1-2 pages) and place it under /docs/architecture/decisions/ (create directory if needed).
2. Submit PR with the ADR and reference the relevant phase documents.
3. Program Manager will update this index and the PROJECT_STATUS.md after review and approval.

Change log
----------
- 2026-08-03 — Initial decisions log created by Program Manager (synthesized from 00-master-architecture.md).
