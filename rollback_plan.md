Rollback Plan — Observability → Diagnostics → Memory → Semantic Index → SDLC

Principles
- Prefer configuration-based rollback (feature flags, env vars) for immediate safety.
- Use git-revert for code-level rollbacks with coordinated releases.
- Preserve and restore persisted artifacts (backups) before and after migrations.
- Maintain a single-authority incident commander for decisions during rollback windows.

Quick rollback actions (immediate)
- Disable new feature via env var and restart service (example):
  - export METRICS_ENABLED=false
  - export TRACING_ENABLED=false
  - Restart service (systemctl restart <service> or docker-compose restart).
- If CI introduces failing checks: revert CI workflow changes by checkout/commit revert and push to the PR branch.

Stage-specific rollback steps

Stage 1 — Observability
- Immediate: Set LOG_FORMAT back to previous value (e.g., text) via env var and restart.
- Short-term: Revert PR that added exporter/initialization with `git revert <commit>` and open a hotfix PR.
- Long-term: Remove added dependencies from pyproject.toml and run a minor release.

Example commands
- git revert <commit-sha> -m 1 --no-edit
- git push origin HEAD:refs/for/<branch>  # or normal push followed by PR

Stage 2 — Diagnostics
- Immediate: Toggle DIAGNOSTICS_ENABLED=false (if present) or block access to endpoints via network/ingress rules.
- Short-term: Revert commit(s) exposing sensitive diagnostics.
- Data: If a diagnostic change wrote sensitive files, remove them and restore from secure backup.

Stage 3 — Memory
- Immediate: Stop writers and restore a pre-migration backup of the memory file:
  - cp store/agent_memory.json.bak store/agent_memory.json
- Short-term: Revert code changes that changed persistence semantics.
- Long-term: Apply migration scripts that can be run forward and backward; keep schema version in the file.

Stage 4 — Semantic Index
- Immediate: Disable ingestion via feature flag; block service account/API key used by index.
- Short-term: Delete created index/collection in the vector DB (provider CLI or API) then revoke API keys used for the index.
- Long-term: If external vendor is used, request provider support for deletion and verify data-at-rest erasure.

Stage 5 — SDLC
- Immediate: Revert CI workflow changes or disable the workflow in GitHub Actions UI.
- Short-term: Revert code merges that caused CI failures and re-run baseline tests.

Data backup & restore
- Always create backups before migrations:
  - cp store/agent_memory.json store/agent_memory.json.YYYYMMDD
  - tar czf backups/pre-migration-YYYYMMDD.tgz store/
- To restore:
  - cp backups/pre-migration-YYYYMMDD/store/agent_memory.json store/agent_memory.json

Communication & coordination
- Announce rollback window to stakeholders and on-call SRE.
- Use a single incident channel (Slack/Teams) and log all actions.
- After rollback, run verification steps from verification_evidence.md.

Verification after rollback
- Run the same test suite that was used for validation (pytest -q) and confirm artifacts produced by CI are consistent.
- Validate the service health endpoints return expected "UP" statuses where appropriate.

Post-mortem
- Log root cause, timeline, and corrective actions.
- Update playbooks and adjust tests to catch the regression.

Contact
- Include owner(s) and on-call rotation in the release notes for rapid escalation (not included here).

