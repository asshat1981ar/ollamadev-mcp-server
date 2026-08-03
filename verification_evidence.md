Verification Evidence — checklist & commands

Overview
This document lists the commands, expected outputs, and artifact locations to collect verification evidence for each migration stage. Capture logs, CI artifacts, and test reports as proof.

Common commands
- Run test suite (targeted):
  - pytest -q tests/test_logging.py tests/test_observability.py
  - pytest -q tests/test_health_tools.py tests/test_health.py
  - pytest -q tests/test_memory.py tests/test_tool_history.py
  - Full test run: pytest -q
- CI artifacts (GitHub Actions): .github/workflows/python-ci.yml uploads the pytest cache and artifacts under the workflow run UI.

Stage 1 — Observability
- Command: python -c "from ollamadev_mcp_server.logging_config import bind_request, configure_logging, get_logger; configure_logging(fmt='json'); rid=bind_request('smoke1','ping'); get_logger('smoke').info('smoke test', extra={'extra_data':{'k':'v'}})"
- Expected: Single-line JSON log on stdout that parses as JSON and contains keys: timestamp, level, logger, message, request_id, tool_name.
- Evidence to collect:
  - stdout sample log (save as evidence/observability/log_sample.json)
  - pytest output for tests/test_logging.py

Stage 2 — Diagnostics
- Command: Run server tools via test harness (example): pytest -q tests/test_health_tools.py
- Expected: Tests assert get_server_health returns JSON with 'status' and 'uptime_seconds'; get_server_diagnostics includes 'timeouts' and 'log_level'.
- Evidence to collect:
  - pytest report (save as evidence/diagnostics/pytest_report.txt)
  - Sample output of calling get_server_diagnostics through local run (save as evidence/diagnostics/diagnostics.json)

Stage 3 — Memory
- Command: python -c "from ollamadev_mcp_server.tools.memory import _save_memory, _load_memory; _save_memory({'x':'y'}); print(_load_memory())"
- Expected: printout of the persisted dict and presence of file store/agent_memory.json
- Evidence to collect:
  - store/agent_memory.json (copy to evidence/memory/agent_memory.json)
  - pytest results for tests/test_memory.py

Stage 4 — Semantic Index (POC)
- Command (POC): Run prototype tests created in tests/test_semantic_index.py (if implemented).
- Expected: CRUD operations succeed against test index, search returns expected top-K hits.
- Evidence to collect:
  - Test logs and index snapshot (if allowed) in evidence/semantic/

Stage 5 — SDLC
- Commands:
  - Validate CI run: open latest GitHub Actions run for the branch and download artifacts.
  - Run local smoke pipeline: pytest -q
- Evidence to collect:
  - CI run URL and artifacts (attach in change request)
  - Check that required PR checks pass before merge (screenshots or links)

Acceptance criteria (evidence)
- All targeted tests listed per stage pass in CI and locally.
- Observability: sample JSON logs show correlation context and non-empty message.
- Diagnostics: get_server_diagnostics returns expected schema.
- Memory: persisted memory file exists and contains expected entries after store/recall operations; backup files exist.
- Semantic index: design approved and POC tests pass in staging behind a feature flag.
- SDLC: CI shows green for tests and artifacts available for audit.

Storage of evidence
- Create /store/evidence/<stage>/ and upload logs and pytest output there (or attach to the release ticket). Do not store secrets in evidence artifacts.

Notes
- Automated evidence collection can be implemented as part of CI jobs that run the smoke tests and upload structured artifacts to the PR (recommended in the SDLC phase).

