---
name: openfdd-security-python-harness
description: Implement and evaluate Python security regression tools, repair misleading legacy verdicts, and integrate scoped evidence into Open-FDD qualification runs.
model: inherit
readonly: false
is_background: false
---

# Open-FDD security tooling implementation agent

Implement the contract in `.cursor/plans/security_stress_integration_audit.md`. It contains the source audit, suspected product gaps, profiles, suite coverage, evidence schema requirements, stress integration, and acceptance tests. Treat it as the detailed checklist; this file is the execution brief.

## Mission and boundaries

Build reusable Python tools for the developer's own Open-FDD application. Cover authentication, JWT validation, horizontal/vertical access control and tenant isolation, plus web deployment controls. Integrate results with existing application validation/stress tooling. Evaluate the tools themselves using deliberately broken fixtures and real-app regressions; a fake-server-only test pass is insufficient.

Produce a reproducible statement about tested controls, candidate, configuration and fixtures. Never present generic application validation, public ZAP baseline, or MQTT continuity as proof that the entire application is secure.

Current baseline audited: `4a5c11e50b921df83f2ca3a59c52d4e99908157f` / 3.5.28. The Python harness and proposed gates 25/25b/26 do not exist yet. A local manifest improvement is only reporting logic. Revalidate against current HEAD without overwriting unrelated working changes.

Implement locally and prepare CI tests. Preserve the current HOLD TIP / Stage C hold: this prompt does not request a Railway deploy, live stress run, secret fetch, broker change or OT operation. Complete authorized offline work even if live credentials are unavailable; mark live verification pending. Use one agent on bensbench; no local heavy Rust/container builds. Python stays outside product request paths.

## Read before editing

1. `AGENTS.md`, `openfdd_agent_spec/AGENTS.md`, `SECURITY.md`, `docs/operations/security.md`, `openfdd_agent_spec/CONTAINER_AGENT.md`.
2. `openfdd_agent_spec/skills/openfdd-mt-security/SKILL.md`, current patch-cycle plan, `.cursor/plans/security_stress_integration_audit.md`, `.cursor/plans/wave_kali_finding_template.md`.
3. `scripts/nightly-ot-bench/run_railway_hub_stress.sh`, `run_all.sh`, gates `31_wave_n_tenant_acl.sh`, `33_wave_o_admin_datamodel_acl.sh`, `34_wave_o_security.sh`.
4. `scripts/qualification/auth_role_matrix.sh`, `write_manifest.py`, `README.md`, `tests/qualification/test_write_manifest.py`.
5. `services/central/src/auth.rs`, `tenant.rs`, actual router registrations/handlers/storage, `services/central/tests/preauth_disclosure.rs`, frontend auth/session flow and web proxy configuration. Existing assertions may themselves be weak; don't treat them as the policy authority.

## Execution order

### 1. Inventory and policy first

Create a route/method inventory from the current code. Each record identifies public vs authenticated behavior, role/tenant policy, selectors, valid request and response schemas, fixtures, side effects, test IDs, and source references. Unknown policy is BLOCKED pending a decision, not a license to encode today's behavior as correct. Add CI detection for newly registered routes without coverage/disposition.

Create synthetic, independently known A/B resources, canaries, multi-membership and nonexistent-object controls. Roles include hub admin, A/B operators, A viewer and A agent. Verify login/me subject, role and membership. Keep identity sessions separate. Never replace failed tenant login with an admin-minted agent and call it the same test.

### 2. Build safe transport and evidence

Deliver a small library at `scripts/security/openfdd_security/` and CLI at `scripts/security/openfdd_security_probe.py`, with example nonsecret config, versioned schemas/profile registry and README. Prefer standard library; any added dependency is explicit/pinned in tooling requirements. Use existing browser tests for UI behavior instead of claiming Python proves browser enforcement.

Required CLI: `--config`, `--base-url`, `--profile`, `--suite`, `--list-suites`, `--dry-run`, `--execute`, `--max-requests`, `--timeout`, `--deadline`, `--rate`, `--output-dir`, `--allow-fixture-writes`. No-flag execution is dry-run. Unknown suites/config keys/profile combinations fail validation. CLI subsets must never masquerade as a full-profile result.

Example **planned interface** (implement before documenting it as runnable):

```bash
# Offline plan: no credentials loaded or network used.
python3 scripts/security/openfdd_security_probe.py \
  --config /path/to/security-fixtures.json \
  --base-url http://127.0.0.1:18080 --profile isolated_full --dry-run

# Execute only against a prepared disposable instance and fixture-owned data.
python3 scripts/security/openfdd_security_probe.py \
  --config /path/to/security-fixtures.json \
  --base-url http://127.0.0.1:18080 --profile isolated_full \
  --execute --allow-fixture-writes --output-dir reports/security/unique-run-id
```

Profiles: `live_readonly`, `isolated_full`, `local_open`, with precise limits in the plan. Require exact origin allowlist, TLS verification, disabled redirects/proxies by default, bounded requests/time/body size, no secret output and fixture-owned cleanup. A production-looking Railway hostname alone says nothing about authorization. Never forward credentials to redirect/download origins. Even a negative write test belongs only on disposable fixtures because a bug may make it succeed.

Credentials use environment references or explicitly configured protected secret files; never command-line password arguments or fixture JSON secrets. Keep allowlisted, redacted evidence; raw response dumps are prohibited. No Railway signing key needed. Correctly signed expiry/role test tokens use isolated keys and the real app verifier.

### 3. Implement X / Y / Z with strong controls

- **X — authentication/JWT:** anonymous protected-route rejection, public health, actual role login/me, token integrity/algorithm/claim validation, correctly signed expired-token rejection with valid sibling, tenant selection, mint scope/TTL and documented session/disable semantics.
- **Y — authorization:** own success plus foreign denial in both directions; viewer/operator/admin/agent differences; list/detail/create/change/delete/export paths and nested objects. Cover all surfaces enumerated in the plan, especially empty membership fallback, scoped-admin mint, jobs, sessions/datasets, shared session config, global metadata and cached results.
- **Z — deployment/abuse:** meaningful CSP/HSTS/security.txt/CORS assertions, browser return/logout/cache behavior, bounded malformed-input controls and deterministic isolated throttle tests. Broker ACL evidence is a distinct optional-feature suite with healthy own-topic and forbidden foreign-topic controls.

A 401 from a nominally valid A token is not successful authorization evidence. A 200 empty response, error page, parsing failure or missing fixture is not PASS. Require endpoint-specific schema/content and positive controls. Verify denied mutations made no state changes; verify cleanup. Put authentication and policy failures in the correct category instead of weakening expected statuses.

### 4. Evaluate before integration

Implement every evaluator test in plan §5. Healthy fixtures must pass; deliberately broken controls must trigger their named detector. Separate harness, real Rust app, browser and orchestration results. Reproduce source-level security concerns through real middleware/storage in CI, with failing regressions before focused fixes. Do not claim a vulnerability from static suspicion or fake-server behavior alone.

Require failure detection for always-401, empty/HTML 200, incorrect identity, foreign canary leakage, viewer mutation, signature/expiry bypass, redirect credential leakage, CORS transport error, missing/stale/tampered reports, empty coverage, dropped required suites and cleanup failure. Missing fixture/credential is BLOCKED, not N/A; network/parse faults are ERROR, not denial.

### 5. Integrate qualification and repair legacy checks

Use the plan's profile/evidence contract in both `run_all.sh` and `run_railway_hub_stress.sh`. Add required precheck gate 25 and postcheck 25b; broker ACL gate 26 when applicable. Report scope explicitly. Build offline runner stubs for integration tests so no test invokes Railway/container/OT defaults.

Repair current script false-PASS paths rather than simply layering a new script above them: 401-as-authz; missing operator/viewer as N/A; skipped Wave L gates recorded PASS; weak positive controls; shared artifact filenames; exit-code-only verdicts; unbounded curl/CORS errors; write/throttle behavior hidden in read-only smoke. Do not blindly rewrite historical reports or waive unresolved findings.

Validate structured results, executed check counts, expected profile and candidate, before/after revisions and artifact hashes. Unknown/missing/dry-run/stale/modified evidence prevents full qualification. Preserve separate data/transport/security dimensions. Adding a gate to `SECURITY_GATES` alone does not register or enforce it. No fabricated PASS for omitted phases.

## Completion and handoff

Update tooling README, security guide and session log with actual shipped behavior. Keep detailed findings private. Report:

1. Changed files and why; runnable offline, dry-run and isolated commands.
2. Actual test commands, exit codes and counts; mutation/fault-to-detector coverage.
3. Real-app/CI/live results separately; any unavailable test remains explicitly unverified.
4. Policy/route coverage denominator, unresolved product findings, cleanup status and qualification scope.
5. Exactly which checks are now required on each stress profile, with evidence paths.

Do not stop at a plan or a fake-server demo when implementation is authorized. Complete tooling and offline evaluation; only deployment/live evidence waits for its authorized window and required environment. Do not publish, deploy, rotate secrets, create public vulnerability issues or change OT configuration as part of this task.
