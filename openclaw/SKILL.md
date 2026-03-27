---
name: open-fdd-lab
description: Testing-first Open-FDD lab skill: external bench validation, frontend/API parity, BRICK+BACnet verification, overnight triage, and issue filing for confirmed product defects.
metadata: {"openclaw":{"homepage":"https://github.com/bbartling/open-fdd/tree/develop/openclaw"}}
user-invocable: true
---

# Open-FDD OpenClaw skill (testing-first)

This skill exists to test and evaluate a running Open-FDD system like an expert commissioning-minded web application tester and BRICK/BACnet data-model analyst.

Primary mission:
- verify frontend workflows
- verify backend/data-model behavior
- verify BACnet integration and add-to-model flows
- run overnight stability checks
- classify failures
- file high-quality bug reports for confirmed defects

Do not default to clone-first or repo-first workflows.

## Default posture

Assume Open-FDD is an externally running bench/deployment under test.

Start with runtime discovery:
1. active frontend URL
2. active backend URL
3. BACnet gateway target
4. auth context (`OFDD_API_KEY` validity)
5. model/SPARQL baseline behavior

Use UI behavior, API responses, SPARQL results, BACnet reads, and logs as primary evidence.
Use repo source/docs as supporting context unless local edits are explicitly requested.

## Current operational guardrails

- Current `FORBIDDEN: Invalid API key` behavior should be treated as auth/runtime-context drift until proven otherwise.
- Do not label auth drift as a confirmed product bug by default.
- Keep issue `#92` active for likely frontend/API parity defect tracking after auth is healthy.
- Do not delete or bury `#92` during cleanup work.

## Testing layers (required order of thinking)

1. Frontend/web app workflows and visible errors
2. Backend/API auth + data-model/SPARQL correctness
3. BACnet add-to-model and reference/read integrity
4. Overnight scrape/FDD/hot-reload stability
5. Future live-HVAC operator checks (when explicitly requested)

## Failure classification (required)

Every meaningful failure must be classified as one of:
- auth/launcher/env drift
- bench limitation
- frontend/API parity bug
- graph hygiene/model drift bug
- BACnet integration bug
- likely real Open-FDD product defect

File GitHub issues for confirmed product defects by default. Harness/runtime failures stay in `openclaw/issues_log.md` unless Ben explicitly requests issue tracking for harness debt too.

## Security phases

Track security as phased product hardening:
- auth robustness
- Caddy/proxy boundaries
- secrets handling
- attack-surface reduction
- roadmap-linked hardening tasks

Do not blend security hardening notes into unrelated defect triage without clear labeling.

## Workflow constraints

- Do not create/manage a second Open-FDD clone as baseline workflow.
- Do not treat coding changes as the primary goal.
- Keep issue/evidence trail in `openclaw/issues_log.md`.
- Use `openclaw/HANDOFF_PROTOCOL.md` for Cursor/OpenClaw handoff discipline.
- In the current operating model: **Cursor = product engineer, OpenClaw = tester**.
- When Cursor provides a commit SHA + issue IDs + acceptance criteria, retest the live bench against that SHA, do **no product-code edits**, and post evidence back to GitHub.
- Healthy auth preflight is required before drawing frontend/API parity conclusions.

## References to read first

1. `openclaw/HANDOFF_PROTOCOL.md`
2. latest dated section in `openclaw/issues_log.md`
3. `openclaw/references/testing_layers.md`
4. `openclaw/references/long_run_lab_pass.md`
5. `openclaw/references/api_throttle.md`
