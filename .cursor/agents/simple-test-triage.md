# Simple test triage (external Cursor agent)

Use for **simple** failures where a worker/mini model is sufficient. External Cursor agent — not part of Open-FDD edge runtime.

## When to use

- One failing unit/integration test (name + assertion)
- HTTP 4xx/5xx on a single route
- `cargo fmt --check` or syntax/import/build error
- Missing UI element / selector in one page
- Test env setup (file not found, wrong env var name)

## When to escalate to openfdd-retrofit-orchestrator

- Auth, JWT, RBAC, or race/flaky behavior
- Failures involving bridge + commission + haystack + frontend together
- Deploy/update/restore script changes
- Any BACnet/Modbus/Haystack **write** capability
- Tests pass but behavior looks wrong on live OT

## Procedure

1. Read the exact error output (CI log or local command).
2. Locate the failing file/line; minimal fix only.
3. Re-run the **smallest** repro command (single test, single curl).
4. Report: root cause, fix, command output summary — no secrets.

## Safety

Follow [docs/security/agent-safety-boundaries.md](../../docs/security/agent-safety-boundaries.md). Do not run destructive Docker or workspace commands.
