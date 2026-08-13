---
title: Milestone A closeout
parent: Migration
nav_order: 20
---

# Milestone A closeout

**Audit date:** 2026-07-28  
**Open-FDD tip:** `master` after [#582](https://github.com/bbartling/open-fdd/pull/582) (`openfdd_agent_spec`)  
**Playground tip:** `develop` after vibe19/20 twin cutovers (#55–#59)

Trust tested code over historical stage notes. Agent OS:
[`openfdd_agent_spec/MILESTONE_A.md`](../../openfdd_agent_spec/MILESTONE_A.md).

## Summary

Milestone A is **closed with intentional residuals**. Libraries, dual cookbooks,
consumer shims, and GHCR channels are in place. Remaining work (full
`open_fdd.contracts`, generated version manifest, remaining ECM keepers) is
documented below and does **not** block Milestone B Jobs.

## Closeout table

| Area | Expected | Observed | Evidence | Tests | Status | Required action |
|------|----------|----------|----------|-------|--------|-----------------|
| Architecture docs | Human + machine ownership | `ARCHITECTURE.md` + `ownership.yaml` | openfdd_agent_spec | `scripts/architecture_ownership_check.py` | **Closed** | Keep CI green |
| Architecture CI | Ownership + cookbook path gates | Script + cookbook parity | this PR / cookbook-parity | ownership check + `cookbook_parity_check.py --all` | **Closed (light)** | Harden later if needed |
| PyPI package | ECM + oracle extras | `open-fdd` 4.1.1; modules `ecm_engineering`, `rules`, `analytics`, `reporting` | PyPI / `pyproject.toml` | python-package / ecm-python | **Closed** | Residual: generated version manifest |
| Vibe 19 consume oracle | Thin consumer | runner/analytics shims; pin `>=4.1.1,<5` | playground #59 | vibe19 pytest (known transient_threshold fail) | **Closed** | Full KEEP/SHIM matrix residual |
| UI consume oracle | Thin shims | #579/#580 | open-fdd PRs | React SPA checks | **Closed** | — |
| Vibe 20 ECM | Generic math from package | 8 twins delegated; keepers listed | `OPENFDD_ECM_TWINS.md` | ECM parity tests | **Partial** | Delete remaining generic twins after parity (A residual / parallel) |
| Dual cookbooks | Both preserved + CI | SQL + pandas + parity matrix | `docs/rules/cookbook/` | cookbook-parity.yml | **Closed** | Continue honesty on parity labels |
| Rule manifest / contracts | `open_fdd.contracts` | **Not shipped** | — | — | **Deferred** | Milestone A residual / Milestone C |
| Container pinning | Nightly + sha tags | `:nightly` retargets on master | `ghcr-openfdd-stack.yml` | GHCR success post-#580 | **Closed (channel)** | Constraints lock for PyPI float = residual |
| Docs honesty | React not Caddy/Vite | scrubbed in #580 + agent_spec | ops docs | Docs Pages | **Closed** | — |
| GH tidy | No stale PRs/branches | 0 open PRs; default branches only | `gh pr list` | — | **Closed** | Maintain after every merge |

## Intentional residuals (not Milestone B blockers)

1. **`open_fdd.contracts` + canonical rule manifest** — Phase 2 incomplete.
2. **Generated version manifest JSON** — documented in `openfdd_agent_spec/docs/VERSIONING.md` only.
3. **~18 vibe20 ECM keepers** — remain until Open-FDD twins + parity.
4. **Full vibe19 module KEEP/SHIM/MOVE/DELETE matrix** — shims cover runner/analytics/rules core.
5. **Playground GHCR retirement** — needs capability parity matrix (explicitly out of A).
6. **Pre-existing vibe19 fail** `test_supply_air_startup_uses_transient_threshold` — do not weaken tests.

## Pandas / production FDD honesty

See [`docs/architecture/PANDAS_USAGE_INVENTORY.md`](../architecture/PANDAS_USAGE_INVENTORY.md).
Production FDD remains DataFusion SQL via central. UI pandas usage is oracle,
display, I/O, or reporting — not a silent production FDD fallback.

## Handoff to Milestone B

Jobs persistence exists as UI filesystem PR1 (`frontend/web/app/job_store.py`).
Milestone B moves SoT to central `/api/jobs`, adds provenance, runs, stale
detection, findings, and Job-attached WattLab handoffs.
