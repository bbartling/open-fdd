# Wave L L5 — Per-tenant budgets (lab notes)

**Status:** shipped in **3.5.4** · **disabled** on production while `OPENFDD_MULTI_TENANT` is OFF.  
**Purpose:** noisy-neighbor guardrails for shared-hub FDD runs and job creates once multi-tenant mode is lab-enabled.

## Defaults (fail soft for single-hub)

| Knob | Default | Effect |
|------|---------|--------|
| `OPENFDD_MULTI_TENANT` | OFF | Budgets **cannot** enable |
| `OPENFDD_TENANT_BUDGETS` | OFF | No counters; `/api/fdd/run` + `POST /api/jobs` unrestricted |
| `OPENFDD_TENANT_FDD_RUNS_PER_MIN` | `30` | Rolling 60s window per tenant when enabled |
| `OPENFDD_TENANT_JOBS_PER_HOUR` | `60` | Rolling 3600s window per tenant when enabled |

`GET /api/tenants/budgets` always echoes the effective policy (`enabled=false` on LIVE ops pin).

## Lab enable checklist (not production)

1. Tip pin with 3.5.4+ images; backup first.
2. Set `OPENFDD_MULTI_TENANT=1` **only in a lab env**.
3. Set `OPENFDD_TENANT_BUDGETS=1`.
4. Optionally lower `OPENFDD_TENANT_FDD_RUNS_PER_MIN` / `OPENFDD_TENANT_JOBS_PER_HOUR`.
5. Flood tenant A FDD runs ? expect `budget_exceeded` / HTTP 429 on jobs; tenant B remains independent.
6. Revert flag OFF ? single-hub unlimited again.

## Out of scope for L5

- Cross-node Redis/shared counters (process-local only)
- MCP / analytics query budgets (follow-on)
- Dedicated SKU escape hatch (Stage C)

## Evidence

- Unit tests in `services/central/src/tenant_budget.rs`
- Mid-wave gate **15** (`scripts/nightly-ot-bench/26_wave_l_tenant_budgets.sh`) asserts `enabled=false` while mode OFF
