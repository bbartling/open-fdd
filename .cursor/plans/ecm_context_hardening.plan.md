---
name: ECM context hardening
overview: "Audit-first plan to ship a versioned, provenance-honest ECMContext envelope on PyPI (open_fdd.ecm_engineering), with tenant-safe REST/MCP later. Extends existing contracts.py — does not fork calculators. First slice is schema + tests + docs."
todos:
  - id: ecm0-audit
    content: "ECM-0: audit complete — map contracts/provenance/workbook/registry vs envelope requirements"
    status: completed
  - id: ecm1-schema
    content: "ECM-1: versioned ECMContext envelope (JSON schema + dataclasses) + round-trip + missing_evidence tests"
    status: completed
  - id: ecm2-docs
    content: "ECM-2: update agent-context, engineering-calcs, DATA_CONTRACT, openfdd-ecm-engineering SKILL + Pages nav"
    status: completed
  - id: ecm3-interactions
    content: "ECM-3: schedule+fan-reset interaction known-answer (no double count) + readiness states"
    status: completed
  - id: ecm4-api
    content: "ECM-4: read-first REST/MCP context tools (JWT scoped) — after schema green"
    status: pending
  - id: ecm5-stress
    content: "ECM-5: many-equip context generation stress thresholds + tenant isolation negatives"
    status: pending
isProject: false
---

# Generic ECM context and calculation hardening

**Agent brief:** [`.cursor/agents/openfdd-generic-ecm-context-hardening.md`](../agents/openfdd-generic-ecm-context-hardening.md)

**Parent schedule:** [wave_u_post-fq_remainder](wave_u_post-fq_remainder.plan.md) cycle **W4 / ECM-ADAPT** (does not replace V6 FQ tip).

**Stack rule:** Python stays on **PyPI** (`open_fdd.ecm_engineering`). No Python on central/web request path.

## Audit snapshot (evidence)

### Already exists

| Capability | Location |
| --- | --- |
| Stage-1 contracts (scopes, rails, SourceType, AdditiveStatus, InteractionStatus) | [`open_fdd/ecm_engineering/contracts.py`](../../open_fdd/ecm_engineering/contracts.py) |
| Provenance helpers | [`open_fdd/ecm_engineering/provenance.py`](../../open_fdd/ecm_engineering/provenance.py) |
| Calculator registry + `calculate(...)` referee | [`registry.py`](../../open_fdd/ecm_engineering/registry.py), algorithms, finance, changepoint, g14 |
| Workbook fill (inputs only; formulas stay) | [`workbook.py`](../../open_fdd/ecm_engineering/workbook.py), [`stage2_workbook.py`](../../open_fdd/ecm_engineering/stage2_workbook.py) |
| Honesty / FITTED / BALLPARK labels | [`honesty_status.py`](../../open_fdd/ecm_engineering/honesty_status.py), [`honesty_export.py`](../../open_fdd/ecm_engineering/honesty_export.py) |
| Agent docs (high-level) | [`docs/ecm/agent-context.md`](../../docs/ecm/agent-context.md), [`docs/ecm/engineering-calcs.md`](../../docs/ecm/engineering-calcs.md) |
| Skill | [`openfdd_agent_spec/skills/openfdd-ecm-engineering/SKILL.md`](../../openfdd_agent_spec/skills/openfdd-ecm-engineering/SKILL.md) |
| PyPI tip | **`open-fdd==4.4.3` live on PyPI** (close `wu-pypi-publish-4.4.3`) |

### Partial

- Interaction enums exist but **combined schedule + static-reset no-double-count** is not a permanent known-answer gate.
- Provenance / SourceType exist; **equipment-level evidence bags** (fan pair distinct command/power, nameplate vs historian) are not a single versioned envelope.
- Tariff/finance helpers exist; **missing tariff → monetary UNAVAILABLE** is not a structured context response.
- Metering SPA / analytics APIs are product DataFusion — **not** an ECM context export for agents.

### Missing (vs agent brief envelope)

1. Versioned **`ECMContext` / `ecm_context_v1`** JSON with sections: scope, equipment evidence, roles/DQ, baselines, scenario, tariff, calc result, interactions, `missing_evidence` / `assumptions_required` / `blocking_issues` / `recommended_measurements`.
2. Tenant-scoped REST/MCP read tools to assemble that envelope from central evidence.
3. SPARQL/SHACL coupling for ECM applicability (ties to Soft-OPEN DM-09/10 / EQ-VOCAB).
4. Stress thresholds for many-building context generation.

### Soft-OPEN / plan rows this work touches

- `wave-s5-dm-remainder` **ECM-ADAPT** (extend, do not claim DM-09/10 closed from docs alone).
- `wu-pypi-publish-4.4.3` → **CLOSED** (PyPI live).
- Does **not** supersede U-H Nessus, Stage C IdP, or product FDD DataFusion path.

## Implementation slices (ordered)

### ECM-1 — Schema + tests (ship first)

- Add `open_fdd/ecm_engineering/context_envelope.py` (dataclasses) + `schemas/ecm_context_v1.json` (or embed schema).
- Extend / compose existing `contracts.py` types — **no parallel SourceType**.
- Tests (permanent):
  - JSON round-trip + schema validation
  - Missing nameplate / missing tariff → screening-only + structured gaps
  - Supply vs return fan retain distinct point provenance (synthetic fixture)
  - Incompatible unit rejection
- Package version bump only when publishing a new PyPI wheel (not product VERSION).

### ECM-2 — Docs / Pages

- Update `docs/ecm/agent-context.md`, `engineering-calcs.md`, `DATA_CONTRACT.md` ECM section, ECM skill.
- One **synthetic** end-to-end example (no private hosts): retrieve gaps → scenario → workbook inputs → `calculate` referee → readiness.
- Just-the-Docs nav already under PyPI agent tools — refresh links only.

### ECM-3 — Interactions + readiness

- Known-answer: schedule savings then fan-reset on **remaining** runtime (tolerance vs `calculate`).
- Explicit readiness enum: `screening` | `validated` | `submission_ready` (human-only for last).

### ECM-4 — REST/MCP (after ECM-1 green)

- Read-first tools: inventory neighborhood, ECM context for equip+window, scenario validate, export payload.
- JWT tenant scope; foreign building 403; no credentials in payloads.
- Prefer extending `openfdd-mcp` + thin central routes over one opaque endpoint.

### ECM-5 — Stress + isolation

- Synthetic N buildings × M equipment context generation with recorded latency/size caps.
- Tenant A cannot fetch Tenant B context (permanent negative).

## Anti-cheating

- Do not mark COMPLETE from docs alone.
- Do not claim submission-ready without human review flag.
- Do not invent tariffs or Building 100 hard-codes.
- Record commands, exit codes, artifact paths in BUG_REPORT Soft-OPEN / patched tables.

## Exit for “agent can run ECM honestly”

A fresh external agent, from repo docs alone, can: select generic building/equip → get provenance-aware context → see structured gaps → fill workbook input cells → reconcile to Python referee → state screening vs validated without double-counting interactions — and deny foreign tenant data.
