Migration Notes — Observability → Diagnostics → Memory → Semantic Index → SDLC

Scope & constraints
- Staged implementation following mandated order: Observability → Diagnostics → Memory → Semantic Index → SDLC.
- No code changes without approved designs. Produce planning artifacts and safe, low-risk quick wins (docs, env guidance, CI config suggestions).
- Discovery goals: identify critical files, tests for verification, and risky changes.

Stage 1 — Observability (FOUNDATION)
Objective
- Provide structured, correlated logs, basic metrics scaffold, and a safe path toward exporting Prometheus metrics and traces.

Critical files
- ollamadev_mcp_server/logging_config.py (structured JSON logging, bind_request)
- server.py (configure_logging() invoked on startup)
- ollamadev_mcp_server/middleware.py (ToolCallTracker)
- ollamadev_mcp_server/tools/observability.py (task transcript reader)
- docs/architecture/01-observability-foundation.md
- docs/architecture/05-advanced-observability.md
- tests/test_logging.py, tests/test_observability.py

Quick wins (safe, non-code or low-risk)
1. Document and standardize env vars: LOG_FORMAT=json, LOG_LEVEL=INFO, CONFIG_WATCHER_ENABLED=true (dev/staging). Add sample env snippet to repo docs.
2. Add a CI smoke job (or step) that runs pytest -q tests/test_logging.py tests/test_observability.py and uploads logs as artifacts (no code change; CI-edit only if approved).
3. Add a runbook entry showing how to validate structured logs locally: sample python snippet to exercise bind_request and emit a log (documented in docs).

Tests to run
- pytest -q tests/test_logging.py tests/test_observability.py
- Validate: JSON log entries contain timestamp, request_id, tool_name.

Risky changes & mitigations
- Adding new runtime deps (prometheus_client, opentelemetry) can increase memory/CPU: gate behind feature flags and enable in staging only.
- Changing default log format may break downstream log parsers: document and stage rollout.

Minimal Migration Steps
1. Discovery: audit current logging and tracer usage, run tests above.
2. Design: approved metrics/tracing design (scrape endpoint path, labels, sampling policy).
3. Implement behind feature flags; add tests.
4. Deploy to staging; enable Prometheus scrape; monitor.
5. Gradually enable in production.

Stage 2 — Diagnostics
Objective
- Expand diagnostics endpoints and safe diagnostic tooling (timeouts, config, registered modules).

Critical files
- server.py (_register_health_tools, _register_security_tools)
- ollamadev_mcp_server/health.py
- ollamadev_mcp_server/timeouts.py
- tests/test_health_tools.py, tests/test_health.py

Quick wins
1. Use existing get_server_diagnostics and get_server_health tools for automated smoke checks in CI.
2. Add a scheduled pipeline job that runs the diagnostics tools against a staging instance and fails on regressions.

Tests to run
- pytest -q tests/test_health_tools.py tests/test_health.py

Risks & mitigations
- Diagnostics may expose sensitive config/URLs; ensure sensitive fields are masked in outputs and docs. Prefer per-environment toggles and RBAC if exposing in UIs.

Stage 3 — Memory
Objective
- Harden the agent memory (store/agent_memory.json), add size limits and safe persistence.

Critical files
- ollamadev_mcp_server/tools/memory.py
- ollamadev_mcp_server/constants.py (STORE_DIR)
- ollamadev_mcp_server/persistence.py
- tests/test_memory.py, tests/test_tool_history.py

Quick wins
1. Add documentation for location and backup procedures of store/agent_memory.json.
2. Add CI/unit tests to assert round-trip persistence and file corruption handling (tests already present: tests/test_memory.py).
3. Introduce a pre-change backup step (automated script or CI job) before any migration that touches memory storage.

Tests to run
- pytest -q tests/test_memory.py tests/test_tool_history.py

Risks & mitigations
- JSON file corruption on concurrent writes: mitigate via atomic write (tempfile + rename) and backups; gate behind feature flag.
- Growth in memory file size: implement retention or sharding and enforce max-size limit.

Stage 4 — Semantic Index (DESIGN FIRST)
Objective
- Add optional semantic index (vector store + embeddings) to improve search/recall without affecting primary ops.

Critical files (design focus)
- ollamadev_mcp_server/catalog.py (tool phase integration)
- ollamadev_mcp_server/context_manager.py
- ollamadev_mcp_server/tool_history.py
- docs/architecture/* (phase summaries)

Quick wins (design-only)
1. Select integration approach (external managed vector DB vs embedded FAISS). Prepare a design doc specifying data model, retention, security, and costs.
2. Prototype offline (separate repo or feature branch). Do not merge until design approved.

Tests to run (POC)
- Add tests/test_semantic_index.py to validate index CRUD, search precision, and privacy masking.

Risks & mitigations
- PII leakage and long-term storage of embeddings: enforce PII filters, encryption at rest, and TTLs.
- Cost/operational overhead: start with a small test index and limit ingestion rate.

Stage 5 — SDLC (CI/CD & Release)
Objective
- Integrate quality gates, observability checks, and deployment controls into CI/CD.

Critical files
- .github/workflows/python-ci.yml
- pyproject.toml
- tests/ (all tests)

Quick wins
1. Ensure the existing Python CI already runs pytest and uploads artifacts (it does). Add targeted smoke jobs for observability/diagnostics/memory pipelines.
2. Add mandatory PR checks for tests and linting. Document release checklist.

Risks & mitigations
- CI timeouts and flakiness: isolate slow tests, use selective pipelines, increase job timeout for heavyweight checks.

Discovery Checklist (per stage)
- Observability: logging_config.py, middleware.py, server.py, tests/test_logging.py, docs/architecture/05-advanced-observability.md
- Diagnostics: health.py, timeouts.py, server.py, tests/test_health_tools.py
- Memory: tools/memory.py, persistence.py, constants.py, tests/test_memory.py
- Semantic Index: context_manager.py, tool_history.py, design doc only until approved
- SDLC: .github/workflows/python-ci.yml, pyproject.toml, tests/

Acceptance criteria (high level)
- All existing tests pass locally and in CI.
- Observability: JSON log entries have correlation context; metrics endpoint (when enabled) exposes counters/histograms.
- Diagnostics: get_server_health and get_server_diagnostics return expected fields and are exercised by automated checks.
- Memory: Memory persistence is resilient to file corruption and bounded in size.
- Semantic index: Approved design, POC validated in staging behind feature flag.

Next steps
1. Share these artifacts for design approval.
2. After approval: implement Stage 1 in small, reviewed PRs with feature flags.
3. Run staged rollout to staging then production.


