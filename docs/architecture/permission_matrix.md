# Permission Matrix: OllamaDev MCP Server

**Document Version:** 1.0  
**Created:** 2026-08-02  
**Author:** Lead Refactoring Architect  
**Status:** PROPOSED

---

## 1. Overview

This document defines a permission framework for the OllamaDev MCP server, categorizing all 47 tools into three risk levels based on their potential impact on system security, data integrity, and operational continuity.

### 1.1 Risk Level Definitions

```python
from enum import Enum

class RiskLevel(Enum):
    """Risk classification for MCP tools."""
    
    SAFE = "safe"
    """
    Read-only operations with no side effects.
    - No file modifications
    - No command execution
    - No state changes
    - Information disclosure only (low risk)
    
    Examples: File reads, status queries, log viewing
    """
    
    MODERATE = "moderate"
    """
    Operations that modify state but are reversible or limited in scope.
    - File writes (limited scope)
    - Configuration changes
    - Git operations (read-only or limited writes)
    - Command execution (restricted, audited)
    
    Examples: File writes, dependency updates, test execution
    """
    
    DESTRUCTIVE = "destructive"
    """
    Operations that can cause significant, potentially irreversible damage.
    - File deletion
    - Arbitrary command execution
    - Git history modification
    - System-level operations
    - Supply chain modifications
    
    Examples: File deletion, shell commands, git commits
    """
```

---

## 2. Permission Framework

### 2.1 Access Control Model

```python
@dataclass
class ToolPermission:
    """Permission configuration for a tool."""
    risk_level: RiskLevel
    requires_approval: bool
    requires_auth: bool
    audit_required: bool
    rate_limit: int | None  # requests per minute
    timeout_seconds: int
    allowed_roles: list[str]  # empty = all roles
    
# Default permissions by risk level
DEFAULT_PERMISSIONS = {
    RiskLevel.SAFE: ToolPermission(
        risk_level=RiskLevel.SAFE,
        requires_approval=False,
        requires_auth=False,
        audit_required=False,
        rate_limit=1000,
        timeout_seconds=30,
        allowed_roles=[],
    ),
    RiskLevel.MODERATE: ToolPermission(
        risk_level=RiskLevel.MODERATE,
        requires_approval=False,
        requires_auth=True,
        audit_required=True,
        rate_limit=100,
        timeout_seconds=300,
        allowed_roles=["developer", "agent"],
    ),
    RiskLevel.DESTRUCTIVE: ToolPermission(
        risk_level=RiskLevel.DESTRUCTIVE,
        requires_approval=True,
        requires_auth=True,
        audit_required=True,
        rate_limit=10,
        timeout_seconds=600,
        allowed_roles=["admin"],
    ),
}
```

### 2.2 Approval Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                    Tool Call Request                         │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │  Check Risk Level   │
              └──────────┬──────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
   ┌─────────┐     ┌──────────┐     ┌─────────────┐
   │  SAFE   │     │ MODERATE │     │ DESTRUCTIVE │
   └────┬────┘     └────┬─────┘     └──────┬──────┘
        │               │                  │
        │               ▼                  ▼
        │      ┌────────────────┐  ┌──────────────┐
        │      │ Check Auth     │  │ Require      │
        │      │ + Audit Log    │  │ Approval     │
        │      └────────┬───────┘  └──────┬───────┘
        │               │                 │
        │               ▼                 ▼
        │      ┌────────────────┐  ┌──────────────┐
        │      │ Execute Tool   │  │ Wait for     │
        │      └────────┬───────┘  │ Approval     │
        │               │         └──────┬───────┘
        │               │                │
        │               │                ▼
        │               │       ┌────────────────┐
        │               │       │ Execute Tool   │
        │               │       └────────┬───────┘
        │               │                │
        └───────────────┴────────────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │  Return Result      │
              └─────────────────────┘
```

---

## 3. Tool Classification

### 3.1 Filesystem Tools

| Tool | Risk Level | Rationale | Current Mitigations | Required Enhancements |
|------|-----------|-----------|---------------------|----------------------|
| `list_workspace_files` | 🟢 SAFE | Read-only, no side effects | `_safe_path()` | Add audit logging |
| `read_workspace_file` | 🟢 SAFE | Read-only, no side effects | `_safe_path()` | Add audit logging |
| `write_workspace_file` | 🟡 MODERATE | Modifies files, but reversible | `_safe_path()`, audit log | Add size limits, file type restrictions |
| `delete_workspace_file` | 🔴 DESTRUCTIVE | Irreversible data loss | `_safe_path()`, audit log, blocked in autonomous mode | Add soft-delete, confirmation mechanism |
| `move_workspace_file` | 🟡 MODERATE | Modifies file locations, reversible | `_safe_path()`, audit log | Add overwrite protection |

### 3.2 Git Tools

| Tool | Risk Level | Rationale | Current Mitigations | Required Enhancements |
|------|-----------|-----------|---------------------|----------------------|
| `git_status_diff` | 🟢 SAFE | Read-only git operations | None | Add audit logging |
| `git_commit_checkpoint` | 🔴 DESTRUCTIVE | Modifies git history, irreversible | Blocked in autonomous mode | Remove `git add -A`, validate message, add pre-commit hooks |
| `git_log` | 🟢 SAFE | Read-only git operations | None | Add audit logging |

### 3.3 Patch Tools

| Tool | Risk Level | Rationale | Current Mitigations | Required Enhancements |
|------|-----------|-----------|---------------------|----------------------|
| `apply_file_patch` | 🟡 MODERATE | Modifies files, but reversible via git | `_safe_path()`, audit log | Remove system `patch` usage, validate patch format |

### 3.4 Dependency Tools

| Tool | Risk Level | Rationale | Current Mitigations | Required Enhancements |
|------|-----------|-----------|---------------------|----------------------|
| `add_gradle_dependency` | 🟡 MODERATE | Modifies build configuration | `_safe_path()`, audit log | Validate Maven coordinates, whitelist repositories |

### 3.5 Sandbox/Execution Tools

| Tool | Risk Level | Rationale | Current Mitigations | Required Enhancements |
|------|-----------|-----------|---------------------|----------------------|
| `run_pytest` | 🟡 MODERATE | Executes commands, but restricted to pytest | `destructiveHint: False` | Sanitize parameters, add resource limits |
| `run_gradle_test_command` | 🟡 MODERATE | Executes Gradle, but restricted | `destructiveHint: False` | Sanitize parameters, add resource limits |
| `run_shell_command` | 🔴 DESTRUCTIVE | Arbitrary command execution | `destructiveHint: True`, audit log | Implement command whitelist, add sandbox isolation |
| `get_sandbox_status` | 🟢 SAFE | Read-only status query | None | Add audit logging |

### 3.6 Build Tools

| Tool | Risk Level | Rationale | Current Mitigations | Required Enhancements |
|------|-----------|-----------|---------------------|----------------------|
| `run_gradle_tests` | 🟡 MODERATE | Executes Gradle, but restricted | `destructiveHint: False` | Sanitize parameters, add resource limits |
| `run_gradle_build` | 🟡 MODERATE | Executes Gradle, but restricted | `destructiveHint: False` | Sanitize parameters, add resource limits |
| `run_lint` | 🟡 MODERATE | Executes linter, but restricted | `destructiveHint: False` | Sanitize parameters, add resource limits |
| `run_detekt` | 🟡 MODERATE | Executes detekt, but restricted | `destructiveHint: False` | Sanitize parameters, add resource limits |
| `run_ktlint` | 🟡 MODERATE | Executes ktlint, but restricted | `destructiveHint: False` | Sanitize parameters, add resource limits |
| `run_instrumented_tests` | 🟡 MODERATE | Executes Gradle + adb, but restricted | `destructiveHint: False` | Sanitize parameters, add resource limits |
| `run_screenshot_tests` | 🟡 MODERATE | Executes Gradle, but restricted | `destructiveHint: False` | Sanitize parameters, add resource limits |
| `parse_test_results` | 🟢 SAFE | Read-only XML parsing | None | Use defusedxml, add size limits |
| `parse_test_results_xml` | 🟢 SAFE | Read-only XML parsing | None | Use defusedxml, add size limits |
| `parse_coverage_xml` | 🟢 SAFE | Read-only XML parsing | None | Use defusedxml, add size limits |
| `get_build_config` | 🟢 SAFE | Read-only file reads | None | Add audit logging |

### 3.7 Sprint Tools

| Tool | Risk Level | Rationale | Current Mitigations | Required Enhancements |
|------|-----------|-----------|---------------------|----------------------|
| `create_sprint_task` | 🟡 MODERATE | Appends to backlog file | Validates tier/priority, audit log | Add size limits, sanitize content |
| `list_phase_artifacts` | 🟢 SAFE | Read-only file listing | None | Add audit logging |
| `read_phase_artifact` | 🟢 SAFE | Read-only file read | None | Add audit logging |
| `update_phase_artifact` | 🟡 MODERATE | Overwrites artifact files | Validates phase/cycle_id, audit log | Add size limits, sanitize content |
| `evaluate_sprint_outcome` | 🟢 SAFE | Read-only analysis | None | Add audit logging |
| `run_autonomous_sprint` | 🔴 DESTRUCTIVE | Orchestrates multiple tools, can cause widespread changes | Blocks destructive tools, audit log | Add approval workflow, implement dry-run mode |

---

## 4. Complete Permission Matrix

### 4.1 SAFE Tools (13 tools)

| # | Tool | Module | Auth Required | Approval Required | Audit Required | Rate Limit | Timeout |
|---|------|--------|---------------|-------------------|----------------|------------|---------|
| 1 | `list_workspace_files` | filesystem | ❌ | ❌ | ❌ | 1000/min | 30s |
| 2 | `read_workspace_file` | filesystem | ❌ | ❌ | ❌ | 1000/min | 30s |
| 3 | `git_status_diff` | git_tools | ❌ | ❌ | ❌ | 1000/min | 30s |
| 4 | `git_log` | git_tools | ❌ | ❌ | ❌ | 1000/min | 30s |
| 5 | `get_sandbox_status` | sandbox | ❌ | ❌ | ❌ | 1000/min | 30s |
| 6 | `parse_test_results` | build | ❌ | ❌ | ❌ | 1000/min | 30s |
| 7 | `parse_test_results_xml` | build | ❌ | ❌ | ❌ | 1000/min | 30s |
| 8 | `parse_coverage_xml` | build | ❌ | ❌ | ❌ | 1000/min | 30s |
| 9 | `get_build_config` | build | ❌ | ❌ | ❌ | 1000/min | 30s |
| 10 | `list_phase_artifacts` | sprint | ❌ | ❌ | ❌ | 1000/min | 30s |
| 11 | `read_phase_artifact` | sprint | ❌ | ❌ | ❌ | 1000/min | 30s |
| 12 | `evaluate_sprint_outcome` | sprint | ❌ | ❌ | ❌ | 1000/min | 30s |
| 13 | `ping` | meta | ❌ | ❌ | ❌ | 1000/min | 30s |

**Total: 13 tools (28%)**

---

### 4.2 MODERATE Tools (26 tools)

| # | Tool | Module | Auth Required | Approval Required | Audit Required | Rate Limit | Timeout |
|---|------|--------|---------------|-------------------|----------------|------------|---------|
| 1 | `write_workspace_file` | filesystem | ✅ | ❌ | ✅ | 100/min | 300s |
| 2 | `move_workspace_file` | filesystem | ✅ | ❌ | ✅ | 100/min | 300s |
| 3 | `apply_file_patch` | patch | ✅ | ❌ | ✅ | 100/min | 300s |
| 4 | `add_gradle_dependency` | dependencies | ✅ | ❌ | ✅ | 100/min | 300s |
| 5 | `run_pytest` | sandbox | ✅ | ❌ | ✅ | 100/min | 300s |
| 6 | `run_gradle_test_command` | sandbox | ✅ | ❌ | ✅ | 100/min | 600s |
| 7 | `run_gradle_tests` | build | ✅ | ❌ | ✅ | 100/min | 600s |
| 8 | `run_gradle_build` | build | ✅ | ❌ | ✅ | 100/min | 600s |
| 9 | `run_lint` | build | ✅ | ❌ | ✅ | 100/min | 300s |
| 10 | `run_detekt` | build | ✅ | ❌ | ✅ | 100/min | 300s |
| 11 | `run_ktlint` | build | ✅ | ❌ | ✅ | 100/min | 300s |
| 12 | `run_instrumented_tests` | build | ✅ | ❌ | ✅ | 50/min | 900s |
| 13 | `run_screenshot_tests` | build | ✅ | ❌ | ✅ | 50/min | 900s |
| 14 | `create_sprint_task` | sprint | ✅ | ❌ | ✅ | 100/min | 300s |
| 15 | `update_phase_artifact` | sprint | ✅ | ❌ | ✅ | 100/min | 300s |
| 16 | `describe_tools` | meta | ✅ | ❌ | ❌ | 100/min | 30s |
| 17 | `suggest_next_action` | meta | ✅ | ❌ | ✅ | 10/min | 120s |
| 18 | `store_memory` | memory | ✅ | ❌ | ✅ | 100/min | 30s |
| 19 | `recall_memory` | memory | ✅ | ❌ | ❌ | 100/min | 30s |
| 20 | `list_memories` | memory | ✅ | ❌ | ❌ | 100/min | 30s |
| 21 | `clear_memory` | memory | ✅ | ❌ | ✅ | 100/min | 30s |
| 22 | `get_server_settings` | settings | ✅ | ❌ | ❌ | 100/min | 30s |
| 23 | `update_server_settings` | settings | ✅ | ❌ | ✅ | 10/min | 30s |
| 24 | `get_task_transcript` | observability | ✅ | ❌ | ❌ | 100/min | 30s |
| 25 | `search_workspace` | code | ✅ | ❌ | ❌ | 100/min | 30s |
| 26 | `get_file_outline` | code | ✅ | ❌ | ❌ | 100/min | 30s |

**Total: 26 tools (55%)**

---

### 4.3 DESTRUCTIVE Tools (8 tools)

| # | Tool | Module | Auth Required | Approval Required | Audit Required | Rate Limit | Timeout |
|---|------|--------|---------------|-------------------|----------------|------------|---------|
| 1 | `delete_workspace_file` | filesystem | ✅ | ✅ | ✅ | 10/min | 300s |
| 2 | `git_commit_checkpoint` | git_tools | ✅ | ✅ | ✅ | 10/min | 600s |
| 3 | `run_shell_command` | sandbox | ✅ | ✅ | ✅ | 5/min | 600s |
| 4 | `run_autonomous_sprint` | sprint | ✅ | ✅ | ✅ | 1/min | 3600s |
| 5 | `reset_server_settings` | settings | ✅ | ✅ | ✅ | 1/min | 30s |
| 6 | `find_symbol` | code | ✅ | ❌ | ❌ | 100/min | 30s |
| 7 | `get_todos` | code | ✅ | ❌ | ❌ | 100/min | 30s |
| 8 | `get_server_health` | server | ✅ | ❌ | ❌ | 100/min | 30s |

**Note:** Tools 6-8 are currently classified as DESTRUCTIVE due to potential information disclosure, but could be reclassified as MODERATE with proper access controls.

**Total: 8 tools (17%)**

---

## 5. Implementation Plan

### 5.1 Phase 1: Permission Framework (Week 1)

**Deliverables:**
1. Implement `RiskLevel` enum and `ToolPermission` dataclass
2. Create permission registry mapping tools to permissions
3. Implement permission checking middleware
4. Add approval workflow for DESTRUCTIVE tools

**Files to Create:**
- `ollamadev_mcp_server/permissions.py` (permission framework)
- `ollamadev_mcp_server/approval.py` (approval workflow)

**Files to Modify:**
- `server.py` (integrate permission middleware)
- All tool modules (add permission annotations)

---

### 5.2 Phase 2: Enhanced Audit Logging (Week 2)

**Deliverables:**
1. Enable audit logging for all MODERATE and DESTRUCTIVE tools
2. Implement structured audit log format
3. Add audit log query tool
4. Implement audit log rotation

**Files to Create:**
- `ollamadev_mcp_server/audit_enhanced.py` (enhanced audit system)

**Files to Modify:**
- All tool modules (add audit logging)

---

### 5.3 Phase 3: Access Control (Week 3)

**Deliverables:**
1. Implement role-based access control (RBAC)
2. Add user authentication integration
3. Implement permission overrides
4. Add access control audit logging

**Files to Create:**
- `ollamadev_mcp_server/access_control.py` (RBAC system)
- `ollamadev_mcp_server/roles.py` (role definitions)

**Files to Modify:**
- `server.py` (integrate access control)
- All tool modules (add role checks)

---

### 5.4 Phase 4: Resource Limits (Week 4)

**Deliverables:**
1. Implement per-tool rate limiting
2. Add resource quotas (CPU, memory, disk)
3. Implement timeout enforcement
4. Add resource usage monitoring

**Files to Create:**
- `ollamadev_mcp_server/resource_limits.py` (resource management)
- `ollamadev_mcp_server/quotas.py` (quota enforcement)

**Files to Modify:**
- All execution tools (add resource checks)

---

## 6. Migration Guide

### 6.1 For Tool Developers

**Before:**
```python
@mcp.tool()
def my_tool(param: str) -> str:
    # Tool implementation
    return "result"
```

**After:**
```python
@mcp.tool(
    annotations={
        "riskLevel": "moderate",
        "requiresAuth": True,
        "requiresApproval": False,
        "auditRequired": True,
        "rateLimit": 100,
        "timeout": 300,
    }
)
def my_tool(param: str) -> str:
    # Tool implementation
    return "result"
```

### 6.2 For Administrators

**Configuring Permissions:**

```json
{
  "permissions": {
    "run_shell_command": {
      "risk_level": "destructive",
      "requires_approval": true,
      "allowed_roles": ["admin"],
      "rate_limit": 5,
      "timeout": 600
    },
    "write_workspace_file": {
      "risk_level": "moderate",
      "requires_approval": false,
      "allowed_roles": ["developer", "agent"],
      "rate_limit": 100,
      "timeout": 300
    }
  }
}
```

---

## 7. Testing Strategy

### 7.1 Unit Tests

- Test permission checking logic
- Test approval workflow
- Test rate limiting
- Test access control

### 7.2 Integration Tests

- Test tool execution with different permission levels
- Test approval workflow end-to-end
- Test rate limiting under load
- Test access control with different roles

### 7.3 Security Tests

- Test permission bypass attempts
- Test approval workflow bypass
- Test rate limit bypass
- Test access control bypass

---

## 8. Monitoring and Alerting

### 8.1 Metrics

- Tool call counts by risk level
- Approval request counts
- Rate limit violations
- Access control violations
- Resource usage by tool

### 8.2 Alerts

- High rate of DESTRUCTIVE tool calls
- Unusual approval patterns
- Rate limit violations
- Access control violations
- Resource quota exceeded

---

## 9. Compliance and Audit

### 9.1 Audit Trail

All MODERATE and DESTRUCTIVE tool calls must be logged with:
- Timestamp
- User/agent ID
- Tool name
- Parameters (sanitized)
- Result (sanitized)
- Approval status
- Duration

### 9.2 Retention Policy

- Audit logs: 90 days
- Approval records: 1 year
- Access control logs: 1 year

---

## 10. Conclusion

This permission framework provides a comprehensive approach to securing the OllamaDev MCP server by:

1. **Classifying tools** by risk level (SAFE, MODERATE, DESTRUCTIVE)
2. **Implementing access controls** based on risk level
3. **Requiring approval** for high-risk operations
4. **Enabling audit logging** for all state-changing operations
5. **Implementing rate limiting** to prevent abuse
6. **Adding resource limits** to prevent DoS

**Next Steps:**
1. Review and approve this permission matrix
2. Implement Phase 1 (Permission Framework)
3. Conduct security testing
4. Deploy to staging environment
5. Conduct user acceptance testing
6. Deploy to production

---

**Document Status:** PROPOSED  
**Review Date:** 2026-08-09  
**Author:** Lead Refactoring Architect  
**Approvers:** [Pending]
