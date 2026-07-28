# Milestone A — build checkpoints

Track durable progress. Update whenever Milestone A status changes (merge,
blocker, or intentional exception). Detail lives in
[`MILESTONE_A.md`](MILESTONE_A.md) and [`docs/MIGRATION_MATRIX.md`](docs/MIGRATION_MATRIX.md).

Legend: `[x]` done · `[~]` partial · `[ ]` remaining

---

## Phase 0 — Architecture freeze

- [x] Human architecture locks in this agent spec ([`ARCHITECTURE.md`](ARCHITECTURE.md))
- [x] Machine-readable seed ([`ownership.yaml`](ownership.yaml))
- [ ] CI: ownership schema validation
- [ ] CI: forbidden import / no silent pandas fallback tests
- [ ] CI: required cookbook path + terminology consistency tests

## Phase 1 — Packaging / release / containers

- [x] PyPI `open-fdd` 4.1.0 rules+analytics+reporting; 4.1.1 topology enrich
- [x] vibe19 / UI pins `>=4.1.1,<5`
- [~] Version policy documented ([`docs/VERSIONING.md`](docs/VERSIONING.md)) — generated manifest not yet shipped
- [ ] Constraints/lock so rebuilds do not silently float newer PyPI mid-tag
- [~] Image metadata / nightly channel works; deepen labels + in-container asserts
- [x] Stack + MCP GHCR green on master tip (post UI twin retirement)

## Phase 2 — Shared contracts + rule manifest

- [ ] `open_fdd.contracts` package (pandas-free base)
- [ ] Canonical machine-readable rule manifest
- [ ] Manifest ↔ SQL registry ↔ pandas cookbook CI agreement
- [ ] Derived doc tables from manifest (keep hand-written expressions)

## Phase 3 — Vibe 19 thin-oracle cutover

- [x] Thin shims for most `app/rules/*` → PyPI
- [x] `app/rules/runner.py` + `app/analytics.py` → package shims (playground #59, open-fdd #580)
- [~] Remaining local keepers: custom_registry / custom_rules / Streamlit UX (intentional)
- [ ] Full migration matrix with KEEP/SHIM/MOVE/DELETE for every significant module
- [ ] Clean-install + container smoke checklist recorded per release

## Phase 4 — Vibe 20 generic ECM migration

- [x] Open-FDD ECM package + 8 delegated twins (fan affinity, schedule reduction, OA sensible, kW/ton, boiler eff, scheduling fan/cool/heat bins)
- [~] ~18 esco/algorithm keepers remain (documented in playground `OPENFDD_ECM_TWINS.md`)
- [ ] Richer calculator result contracts (bins detail / provenance)
- [ ] Delete remaining generic twins after parity
- [ ] Docker-socket runner hardening = follow-on (document only in Milestone A)

## Cross-cutting

- [x] Dual cookbooks present and documented
- [~] Cookbook parity CI exists (`cookbook-parity.yml`) — harden vs mission checklist
- [ ] Final Milestone A qualification + [`COMPLETION_REPORT.md`](COMPLETION_REPORT.md) filled
- [ ] Playground GHCR retirement — **explicitly out of Milestone A** (needs parity matrix)

---

## Known intentional exceptions

| Exception | Why |
| --- | --- |
| vibe19 keeps custom rule loading | Product extension surface |
| vibe20 EnergyPlus code stays local | Not generic math |
| `open_fdd.rules` not renamed to `.oracle` | Code truth; pip extra is `oracle` |
| Pre-existing vibe19 test fail `test_supply_air_startup_uses_transient_threshold` | Fails with local twins on develop too — do not weaken tests to hide |
