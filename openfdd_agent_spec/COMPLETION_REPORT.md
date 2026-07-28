# Milestone A Completion Report

Filled at A closeout (2026-07-28). Residual items are intentional — see
[`docs/migration/MILESTONE_A_CLOSEOUT.md`](../docs/migration/MILESTONE_A_CLOSEOUT.md).

---

## Executive result

Milestone A **closed with residuals**. PyPI oracle/ECM libraries, dual cookbooks,
consumer shims, agent OS, and GHCR nightly channel are verified. Deferred:
`open_fdd.contracts`, generated version manifest, remaining vibe20 ECM keepers,
playground GHCR retirement.

## Merged PRs (selected)

| PR | Repo | Purpose |
| --- | --- | --- |
| #578 | open-fdd | PyPI 4.1.0 oracle rules/analytics/reporting |
| #579 | open-fdd | UI consume oracle |
| #580 | open-fdd | UI runner/analytics shims + Streamlit docs |
| #582 | open-fdd | openfdd_agent_spec |
| #55–#59 | playground | charts, ECM adapter, twins, vibe19 consume |

## Architecture enforcement

`openfdd_agent_spec` + `ownership.yaml` + `architecture_ownership_check.py`.

## Packaging and versioning

`open-fdd` 4.1.1; extras `oracle` / `reporting` / `vibe19`. Module name remains
`open_fdd.rules` (not `open_fdd.oracle`).

## Shared contracts / Rule manifest

**Not shipped** — residual.

## Pandas / SQL cookbooks

Both present under `docs/rules/cookbook/`; cookbook-parity CI green path.

## Vibe 19 / Vibe 20 migration

Thin consumers; 8 ECM twins delegated; keepers documented.

## GHCR

Test on `:nightly` / `sha-*` per `CONTAINER_AGENT.md`.

## Remaining intentional exceptions

See closeout residuals + `BUILD_CHECKPOINTS.md`.

## Milestone B handoff

Jobs UI filesystem store exists (`job_store.py`). Milestone B: central `/api/jobs`,
provenance, runs, stale, findings, WattLab Job handoffs.
