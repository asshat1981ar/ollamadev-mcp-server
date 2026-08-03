# OllamaDev MCP Server — Master Architecture Document

> **Author:** Lead Refactoring Architect  
> **Date:** 2026-08-02  
> **Status:** PROPOSAL  
> **Version:** 1.0  

---

## 1. Executive Summary

This document is the master architecture plan for the OllamaDev MCP Server refactoring initiative. It consolidates findings from a comprehensive codebase audit and defines a 5-phase improvement roadmap targeting **reliability, security, maintainability, observability, and autonomous agent effectiveness** — without breaking existing functionality.

### 1.1 Scope

| Aspect | Current | Target |
|--------|---------|--------|
| Tools | 46 across 12 modules | 46+ (additive) |
| Source LOC | 2,661 | ~4,500 (estimated) |
| Test LOC | 1,556 | ~3,000 (estimated) |
| Test count | 105 passing | 200+ (estimated) |
| Observability | Uvicorn access logs only | Structured JSON + metrics + tracing |
| Security | Path traversal guard only | Auth + rate limit + audit + CORS |
| Agent effectiveness | Stateless LLM calls | Context-aware with retry + circuit breaker |

### 1.2 Guiding Principles

1. **Never break existing tool contracts** — all changes are additive or internal
2. **Evidence-based decisions** — every recommendation references specific code
3. **Incremental delivery** — each phase is independently deployable
4. **Backward compatibility** — existing deployments work without changes
5. **Test-first** — no code merges without test coverage

---

## 2. Current State Analysis

### 2.1 Codebase Topology

```
ollamadev-mcp-server/
├── pyproject.toml                    # mcp[cli]==2.0.0rc1, requests>=2.32.0
├── server.py                         # Thin bootstrap, 35 lines
├── ollamadev_mcp_server/
│   ├── __init__.py                   # 1 line
│   ├── constants.py                  # 56 lines — global config, import-time resolution
│   ├── persistence.py                # 58 lines — atomic JSON settings I/O
│   └── tools/
│       ├── filesystem.py             # 115 lines — 5 tools, path traversal guard
│       ├── code.py                   # 157 lines — 4 tools, grep-based search
│       ├── build.py                  # 538 lines — 12 tools, Gradle/lint/test parsing
│       ├── sprint.py                 # 448 lines — 8 tools, autonomous sprint loop
│       ├── memory.py                 # 98 lines  — 4 tools, JSON KV store
│       ├── meta.py                   # 541 lines — 4 tools, hardcoded catalog + LLM
│       ├── patch.py                  # 152 lines — 1 tool, unified diff parser
│       ├── git_tools.py              # 104 lines — 3 tools, git CLI wrapper
│       ├── dependencies.py           # 121 lines — 1 tool, Gradle catalog editor
│       ├── observability.py          # 74 lines  — 1 tool, transcript reader
│       ├── sandbox.py                # 165 lines — 4 tools, pytest/gradle/shell runner
│       └── settings.py              # 147 lines — 3 tools, persisted config
└── tests/                            # 1,556 lines, 105 tests
```

### 2.2 Dependency Graph

```
server.py
  └── tools/* (12 modules)
        ├── constants.py (global config)
        │     └── persistence.py (settings file I/O)
        ├── filesystem.py (_safe_path, _is_ignored)
        │     ↑ imported by: code.py, observability.py, git_tools.py,
        │       dependencies.py, patch.py, sprint.py
        └── External: requests (HTTP), subprocess (shell), pathlib (FS)
```

### 2.3 Evidence-Based Findings

| Finding | Evidence | Severity |
|---------|----------|----------|
| No structured logging | `grep -r "import logging" ollamadev_mcp_server/` → 0 results | 🔴 HIGH |
| No authentication | `server.py:31` — `mcp.run()` with no auth middleware | 🔴 HIGH |
| No rate limiting | No middleware stack at all | 🔴 HIGH |
| Hardcoded tool catalog | `meta.py:29-200` — 200+ lines of static `_TOOL_CATALOG` | 🟡 MEDIUM |
| Import-time config resolution | `constants.py:17` — `_PERSISTED = load_persisted_settings()` at module level | 🟡 MEDIUM |
| No retry on LLM calls | `meta.py:470` — `requests.post(..., timeout=120)` with no retry | 🟡 MEDIUM |
| No circuit breaker | `meta.py:478-512` — direct HTTP calls to Anthropic, no fallback | 🟡 MEDIUM |
| No request correlation | No trace/request ID propagation | 🟡 MEDIUM |
| No error tracking | Exceptions raised directly, no centralized handler | 🟡 MEDIUM |
| No health endpoint | Only `ping` tool, no `/health` HTTP endpoint | 🟡 MEDIUM |
| Shell injection surface | `sandbox.py:140` — `/bin/sh -c command` (mitigated by destructiveHint) | 🟡 MEDIUM |
| No input size limits | `write_workspace_file` accepts unlimited content | 🟡 MEDIUM |
| Memory file has no size cap | `memory.py` — unbounded JSON growth | 🟢 LOW |
| No graceful shutdown | No signal handling in `server.py` | 🟢 LOW |
| Test temp cleanup warnings | 154 pytest warnings about `.git` directory removal | 🟢 LOW |

---

## 3. Risk Register

### 3.1 Security Risks

| ID | Risk | Likelihood | Impact | Mitigation Phase |
|----|------|-----------|--------|-----------------|
| S1 | Unauthenticated access to destructive tools | HIGH | CRITICAL | Phase 2 |
| S2 | Shell injection via `run_shell_command` | MEDIUM | CRITICAL | Phase 2 |
| S3 | Path traversal (existing guard is string-based) | LOW | HIGH | Phase 2 (audit) |
| S4 | Denial of service via large payloads | MEDIUM | HIGH | Phase 2 |
| S5 | API key leakage in logs/errors | MEDIUM | HIGH | Phase 1 |

### 3.2 Reliability Risks

| ID | Risk | Likelihood | Impact | Mitigation Phase |
|----|------|-----------|--------|-----------------|
| R1 | LLM provider outage cascades | HIGH | HIGH | Phase 4 |
| R2 | Autonomous sprint hangs indefinitely | MEDIUM | HIGH | Phase 4 |
| R3 | Settings file corruption | LOW | MEDIUM | Phase 3 |
| R4 | Memory file grows unbounded | LOW | MEDIUM | Phase 3 |
| R5 | No visibility into failures | HIGH | HIGH | Phase 1 |

### 3.3 Maintainability Risks

| ID | Risk | Likelihood | Impact | Mitigation Phase |
|----|------|-----------|--------|-----------------|
| M1 | Tool catalog drift from actual tools | HIGH | MEDIUM | Phase 3 |
| M2 | Global constants make testing fragile | MEDIUM | MEDIUM | Phase 3 |
| M3 | No type validation on tool inputs | MEDIUM | LOW | Phase 3 |
| M4 | Tight coupling between modules | LOW | MEDIUM | Phase 3 |

---

## 4. Improvement Roadmap

### Phase Overview

```
Phase 1: Foundation (Observability + Reliability)     ← START HERE
  ├── Structured logging with correlation IDs
  ├── Health check endpoint
  ├── Request validation
  ├── Error tracking
  └── Timeout enforcement

Phase 2: Security Hardening
  ├── Authentication layer
  ├── Rate limiting
  ├── Input sanitization
  ├── Audit logging
  └── CORS configuration

Phase 3: Maintainability
  ├── Dynamic tool catalog
  ├── Dependency injection
  ├── Configuration hot-reload
  ├── Type-safe tool definitions
  └── Modular tool registration

Phase 4: Agent Effectiveness
  ├── Context window management
  ├── Tool call history
  ├── Retry logic with backoff
  ├── Circuit breaker
  └── Autonomous sprint improvements

Phase 5: Advanced Observability
  ├── Metrics collection (Prometheus)
  ├── Distributed tracing (OpenTelemetry)
  ├── Performance profiling
  ├── Usage analytics
  └── Dashboard
```

### Phase Dependencies

```
Phase 1 ──→ Phase 2 ──→ Phase 3
   │                        │
   └────────────────────────→ Phase 4 ──→ Phase 5
```

- Phase 1 is foundational — logging enables debugging all subsequent phases
- Phase 2 depends on Phase 1 for audit logging
- Phase 3 depends on Phase 1 for error tracking patterns
- Phase 4 depends on Phase 1 (logging) and Phase 2 (auth for agent identity)
- Phase 5 depends on Phase 1 (structured logs feed metrics)

### Effort Estimates

| Phase | Effort | Risk | Value | Priority |
|-------|--------|------|-------|----------|
| 1. Foundation | 2-3 days | LOW | HIGH | P0 |
| 2. Security | 2-3 days | MEDIUM | CRITICAL | P0 |
| 3. Maintainability | 3-4 days | LOW | MEDIUM | P1 |
| 4. Agent Effectiveness | 3-4 days | MEDIUM | HIGH | P1 |
| 5. Advanced Observability | 4-5 days | LOW | MEDIUM | P2 |
| **Total** | **14-19 days** | | | |

---

## 5. Design Decisions Log

| ID | Decision | Rationale | Alternatives Considered |
|----|----------|-----------|------------------------|
| DD1 | Use Python `logging` + `structlog` | Standard library + proven structured output | Custom JSON logger (more maintenance) |
| DD2 | Bearer token auth (not OAuth) | Simple, matches OllamaDev app pattern | OAuth2 (overkill for single-user) |
| DD3 | Pydantic v2 for validation | Already transitive dep via MCP SDK | marshmallow, attrs |
| DD4 | Prometheus metrics format | Industry standard, Grafana compatible | OpenMetrics, custom |
| DD5 | OpenTelemetry for tracing | Vendor-neutral, Python SDK mature | Jaeger client, Zipkin |
| DD6 | Keep MCP SDK v2 beta pin | Stable for current use, migration later | Upgrade to stable (breaking changes) |
| DD7 | Feature flags per phase | Safe rollout, easy rollback | Big bang release (risky) |

---

## 6. Success Criteria

### 6.1 Quantitative

| Metric | Current | Phase 1 Target | Phase 5 Target |
|--------|---------|---------------|---------------|
| Test count | 105 | 130+ | 200+ |
| Test pass rate | 100% | 100% | 100% |
| Pytest warnings | 154 | <10 | 0 |
| Mean tool latency | Unknown | <500ms (measured) | <200ms |
| Error visibility | 0% | 100% (logged) | 100% (traced) |
| Security coverage | 1 guard | 5 layers | 7 layers |

### 6.2 Qualitative

- [ ] Can debug any agent workflow from structured logs
- [ ] Can detect and alert on LLM provider failures
- [ ] Can identify slow tools from metrics
- [ ] Can trace a request end-to-end across tools
- [ ] Can audit all destructive operations
- [ ] Can onboard new tools without catalog drift

---

## 7. References

- [MCP Python SDK v2 Migration Guide](https://py.sdk.modelcontextprotocol.io/v2/migration/)
- [OWASP API Security Top 10](https://owasp.org/API-Security/editions/2023/en/0x11-t00/)
- [Twelve-Factor App](https://12factor.net/)
- [Circuit Breaker Pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker)
- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/)

---

## 8. Appendix: Phase Documents

| Document | Phase | Status |
|----------|-------|--------|
| [01-observability-foundation.md](./01-observability-foundation.md) | Foundation | DESIGN |
| [02-security-hardening.md](./02-security-hardening.md) | Security | DESIGN |
| [03-maintainability.md](./03-maintainability.md) | Maintainability | DESIGN |
| [04-agent-effectiveness.md](./04-agent-effectiveness.md) | Agent Effectiveness | DESIGN |
| [05-advanced-observability.md](./05-advanced-observability.md) | Advanced Observability | DESIGN |
