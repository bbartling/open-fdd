---
title: "Role: operator-activate"
parent: MCP role packs
nav_order: 4
---

# Role pack: `operator-activate` — operator

Status: **SCAFFOLD** (spec normative; tools not yet in `mcp/` crate).

## Mission

Take an already-produced `runtime_bundle.json` (pinned twin_version +
model_release + unity_build + optional mapping revision), import and
**activate** it on central, then prove the stack: health, models, golden
predict, SPA twin page. The operator changes *which digests are live* — never
the artifacts themselves, and **never the BAS**.

**Hard law:** `BAS_WRITE_AUTHORITY=no`. This role pack contains **zero**
BACnet write tools; an operator request to command equipment is refused and
escalated to a human process outside MCP.

## Scope

**In:** runtime_bundle import/activate/revoke (gated), read-only health and
model inspection, golden predict smoke, SPA twin availability check.

**Out:** creating/editing model releases, Unity ZIPs, mappings; training;
BACnet reads/writes; deleting artifacts or volumes (see
[agent-safety.md](../agent-safety.html) "Never" table).

## MCP tools

REST alignment: planned `/api/v1/health`, `/api/v1/models`,
`/api/v1/twin/manifest`, `/api/v1/predict/demand_hourly`, and Unity serving
under `/twins/{twin}/builds/{build}/`.

| Tool | Class | Status | Inputs | Outputs | Side effects |
|---|---|---|---|---|---|
| `runtime_bundle_activate_plan` | plan | SCAFFOLD | job_id, `runtime_bundle.json` ref | plan token; diff current→proposed digests (twin/model/unity/mapping); card status warnings (e.g. model CANDIDATE) | plan record |
| `runtime_bundle_activate_execute` | write | SCAFFOLD | plan token, `confirm:true`, idempotency key | new active bundle ID + pinned digests | active pointers switched atomically |
| `runtime_bundle_revoke` | write | SCAFFOLD | active bundle ID, plan token, `confirm:true`, reason | previous-known-good bundle restored | active pointers reverted |
| `runtime_health_get` | read | SCAFFOLD | none | `/api/v1/health` payload: central status, active bundle digests, capability list | none |
| `models_get` | read | SCAFFOLD | none | `/api/v1/models`: active champion name, card metrics, card `status`, release ID + SHA | none |
| `predict_golden_smoke` | read | SCAFFOLD | golden fixture set ID (from `conformance.jsonl`) | per-case `POST /api/v1/predict/demand_hourly` result vs expected, tolerance verdicts | none (predictions are stateless) |
| `spa_twin_check` | read | SCAFFOLD | twin_id | SPA `/twin` reachability, served `index.html` + loader 200s, active `unity_build_id` echo | none |

## Confirmation gates

Activate and revoke are the highest-impact operations in this pack:

1. **Plan first** — the plan shows the exact digest diff and any honesty
   warnings (CANDIDATE model card, pilot farm provenance, missing mapping).
2. **Explicit human confirmation** — `confirm:true` with the unexpired plan
   token. Enthusiastic conversation is not confirmation
   (per `AGENTIC_AI_AND_MCP_SPEC.md`).
3. **Second approval** where configured for activation/revoke.
4. **Post-activate proof is mandatory** — an activation the agent cannot
   verify (`runtime_health_get` + `predict_golden_smoke` + `spa_twin_check`)
   must be reported as unverified, with revoke offered.

## Workflow

1. `runtime_health_get` — baseline before touching anything.
2. `runtime_bundle_activate_plan` — review digest diff; surface all warnings
   verbatim, including model card `status`.
3. Human confirms → `runtime_bundle_activate_execute`.
4. `runtime_health_get` → active digests match the plan.
5. `models_get` → champion + card status reported to the user honestly.
6. `predict_golden_smoke` → all golden cases within tolerance.
7. `spa_twin_check` → twin page serves the active Unity build.
8. On any post-activate failure: report, then offer `runtime_bundle_revoke`
   to the previous known-good bundle (its own plan + confirm gate).

## Errors and recovery

| Error | Recovery |
|---|---|
| Digest in bundle not present on central | Abort plan; request the owning role import the missing artifact. Never substitute a different digest. |
| Golden predict out of tolerance after activate | Report failure honestly; offer revoke; do not "re-run until green". |
| Health degraded post-activate | Revoke to previous bundle (gated); attach both health payloads to the report. |
| Plan token expired | Re-plan; the diff may have changed. |
| Request to write BACnet | Refuse. `BAS_WRITE_AUTHORITY=no`; no tool exists for it in this pack. |

## Acceptance checklist

- [ ] Activation went through plan → explicit confirm → execute with idempotency key.
- [ ] Post-activate: health, `models_get`, golden predict, SPA twin check all ran and results reported (pass or fail — no silent skips).
- [ ] Model card `status` (e.g. CANDIDATE) surfaced to the user at activation.
- [ ] Active digests reported and match `runtime_bundle.json`.
- [ ] Revoke path known-good bundle identified before activation began.
- [ ] Zero BACnet interactions; zero artifact mutations in the session trace.
