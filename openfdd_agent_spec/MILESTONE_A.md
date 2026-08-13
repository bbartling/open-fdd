# Milestone A: Reproducible and Unified Libraries

Agent mission for Cursor/Codex operating in Ben’s WSL environment.

**Adapted 2026-07-28** to code truth: pandas oracle = `open_fdd.rules` (+
`analytics`); pip extra `oracle` / `vibe19`; ECM = `open_fdd.ecm_engineering`;
`open_fdd.contracts` is a Phase 2 target (not shipped). Do not rename modules
unless product explicitly decides.

Progress snapshot: [`BUILD_CHECKPOINTS.md`](BUILD_CHECKPOINTS.md).
PR loop: [`PR_PROTOCOL.md`](PR_PROTOCOL.md).
Containers: [`CONTAINER_AGENT.md`](CONTAINER_AGENT.md).

**Active product recovery / twin program:** follow
[`tools/open-fdd-vibe21-production/`](../tools/open-fdd-vibe21-production/README.md)
Master Loop. Milestone A below remains the library unification mission; it is
**not** a substitute for Vibe 21 P1-G0 (capability ledger + honest qualification).

Do not stop after plans or scaffolding. For each **bounded PR**, implement,
test, push, review, correct, and merge what that PR declared — then refresh
GHCR/dependents **only when the PR’s packaging or image scope requires it**.
Continue across PRs until Milestone A exit criteria or a genuine external
blocker.

---

## Local repositories

```bash
~/open-fdd                         # bbartling/open-fdd → master
~/py-bacnet-stacks-playground      # bbartling/py-bacnet-stacks-playground → develop
  vibe_code_apps_19/
  vibe_code_apps_20/
```

(Adjust clone roots; Ben’s WSL often uses `/home/ben/...`.)

---

## 1. Non-negotiable architecture

### Vibe 19

Educational pandas rule/analytics oracle; React demo; CSV/mapping/weather/
reports/custom rules test bed; standalone GHCR demo. May keep pandas
intentionally. Must not remain the canonical home of duplicated Open-FDD rule,
analytics, reporting, schema, or generic engineering implementations once
migrated.

### Vibe 20

EnergyPlus digital-twin / calibration / ECM cross-check; owns EnergyPlus-
specific behavior. Must not retain duplicate **generic** HVAC formulas once
parity-proven in Open-FDD.

### Open-FDD PyPI

Reusable libraries:

```text
open_fdd.ecm_engineering     # default install
open_fdd.rules               # pandas cookbook oracle (not open_fdd.oracle module)
open_fdd.analytics           # oracle/reference analytics
open_fdd.reporting
open_fdd.contracts           # Phase 2 target
```

Optional pandas extras for notebooks, vibe19, tests, oracle comparisons.
PyPI is **not** the production DataFusion FDD runtime.

### Open-FDD production

Rust services; Arrow/Feather/Parquet historian; DataFusion SQL; canonical SQL
registry; JWT APIs; GHCR stack; React SPA (`openfdd-web`). Must not silently fall
back from SQL to pandas. Must not require Python in the product request path.

---

## 2. Preserve both expression rule cookbooks

SQL and pandas cookbooks remain documented, readable, tested, discoverable,
synchronized in identity/metadata, honest about parity gaps.

Never replace cookbooks with generated API docs alone.
Never delete pandas cookbook because production uses SQL.
Never delete SQL cookbook because pandas remains the oracle.

Protect:

```text
DataFusion SQL expression cookbook
Pandas expression cookbook
Rule parity matrix
Rule metadata / manifest (Phase 2)
Required-role / parameter / gate / applicability docs
```

CI should detect missing headings, duplicate IDs, missing SQL/pandas entries,
undocumented production-only SQL, bad aliases, metadata drift, accidental
shrinkage, broken links, non-importable examples.

**Execution SoT:** SQL registry.
**Identity/metadata SoT (target):** shared rule manifest.
**Oracle SoT:** pandas cookbook + `open_fdd.rules`.

---

## 3. Autonomous engineering loop

Follow [`PR_PROTOCOL.md`](PR_PROTOCOL.md) for every PR (sync → read → inspect →
bound → branch → test-first → validate → commit → draft PR → Actions →
CodeRabbit → merge → refresh dependents/containers).

Migration pattern:

```text
inventory → characterization test → shared implementation → parity proof
→ caller cutover → duplicate deletion → regression → documentation
```

Do not copy into Open-FDD and call migration complete while both
implementations remain active.

---

## 4. Phase sequence

Modify subdivision only when current state proves a task done or needs a split.
See [`BUILD_CHECKPOINTS.md`](BUILD_CHECKPOINTS.md) for done/partial marks.

### Phase 0 — Architecture freeze and enforcement

**Objective:** Turn architecture into testable repository policy.

- Keep [`ARCHITECTURE.md`](ARCHITECTURE.md) + [`ownership.yaml`](ownership.yaml) current.
- Add CI: ownership schema validation; forbidden imports (central must not
  import pandas for FDD; production UI must not bypass SQL for production FDD
  computation); required cookbook paths; terminology consistency; no silent
  pandas fallback; duplicate canonical-module detection.
- Ban production computation paths that bypass DataFusion — not plotting/display.

**Exit:** Boundaries in human + machine form; CI fails on prohibited deps;
both cookbooks protected.

### Phase 1 — Packaging, release, container reproducibility

**Objective:** Deterministic, inspectable builds.

- Document version axes ([`docs/VERSIONING.md`](docs/VERSIONING.md)): platform,
  PyPI package, SQL registry hash, pandas cookbook/oracle, WattLab schema,
  contracts schema, container git SHA.
- Prefer generated version manifest from canonical files.
- Truthful lower bounds for vibe19/vibe20 (do not claim 4.0.0 if APIs need 4.1.1+).
- Image labels / env / endpoint expose versions; pin/constraints so rebuilds do
  not silently float newer PyPI.
- Wheel integrity: build once → test that wheel → publish that wheel.

**Already done (do not redo):** PyPI 4.1.0/4.1.1; consumer pins `>=4.1.1,<5`;
nightly GHCR channel.

**Exit:** No ambiguous root version claim; pinned/constraints images; workflows green.

### Phase 2 — Shared contracts and canonical rule manifest

**Objective:** Eliminate duplicated identity/schema/units/metadata.

- Implement `open_fdd.contracts` (base install without pandas).
- Models for rule ID/alias/category/status/parity/applicability/parameters/
  roles/gates/equipment/findings/jobs/runs/provenance/units/WattLab/ECM results.
- Machine-readable rule manifest supporting both cookbooks (no formula bodies
  in the manifest — expressions stay in cookbooks).
- Tests: unique IDs, alias resolve, roles/units, defaults match, SQL/pandas
  presence, cookbook headings, registry agreement, no accidental shrink.

**Exit:** Consumers share contracts; cookbooks remain readable and CI-protected;
`import open_fdd.contracts` works without pandas.

### Phase 3 — Vibe 19 thin-oracle cutover

**Objective:** Vibe 19 consumes Open-FDD oracle/reporting — not a duplicate repo.

**Already done:** Most rules shims; `runner.py` + `analytics.py` package rebinds
(playground #59, open-fdd UI #580).

**Still required:**

- Full KEEP/SHIM/MOVE/DELETE matrix for significant modules.
- Keep: React UX, custom `CUSTOM-*` loading, demos, prototype-only utils.
- Characterization + parity before any further deletes.
- GHCR smoke after cutovers (sidebar version, package upload, rules, WattLab export).

**Exit:** No active canonical twins of migrated modules; clean-install tests;
GHCR runs; cookbook examples valid against installed package.

### Phase 4 — Vibe 20 generic ECM migration

**Objective:** Generic math in `open_fdd.ecm_engineering`; EnergyPlus stays in vibe20.

**Already done:** Eight twins delegated (fan affinity, schedule reduction,
outside-air sensible, kW/ton, boiler efficiency, scheduling fan/cooling/heating
bins). Keepers listed in playground `vibe_code_apps_20/docs/OPENFDD_ECM_TWINS.md`.

**Still required:**

- Inventory remaining generic formulas (finance, pumps, enthalpy helpers, etc.).
- Richer result contracts so adapters do not recompute.
- Parity → cutover → delete → remove parity bridges that import deleted code.
- Mutation spot-checks on critical formulas (record in PR; need not commit harness).
- Document Docker-socket E+ runner as trusted local-dev — not hardened production;
  follow-on for restricted runner.

**Exit:** No duplicate generic ECM formulas; adapters translate only; E+ code
remains; tests + GHCR green.

---

## 5. Cross-repository tests

Contract compatibility matrix covering package × vibe19 × vibe20 × rule-manifest
× WattLab dump versions. Fixtures: small synthetics in default CI; Building 100
optional/local. Explicit numeric tolerances by output type; categorical IDs exact.

Required classes: unit, schema, contract, parity, regression, package, docs,
cookbook, container, browser smoke, cross-repo compatibility.

---

## 6. GitHub Actions

Discover actual workflow names ([`docs/WORKFLOWS.md`](docs/WORKFLOWS.md)).
For every PR: `gh pr checks --watch`; inspect all checks. After merge, confirm
default-branch GHCR publication for the **merged** commit.

---

## 7. Container refresh

Per [`CONTAINER_AGENT.md`](CONTAINER_AGENT.md): immutable `sha-*` → inspect →
temp smoke → then refresh moving `:nightly` / `:develop` local containers.
Record digests in the completion report.

---

## 8. Milestone documentation

Durable progress: this file + [`BUILD_CHECKPOINTS.md`](BUILD_CHECKPOINTS.md) +
[`docs/MIGRATION_MATRIX.md`](docs/MIGRATION_MATRIX.md) +
`docs/migration/VIBE19_VIBE20_OPENFDD_AUDIT.md` (update, do not fork truth).

Suggested execution log path for long runs:
`docs/migration/MILESTONE_A_EXECUTION.md` (create when Phase 0 coding starts).

---

## 9. Final qualification

Clean sync of both default branches. Run full open-fdd Rust/Python/ECM/oracle/
reporting/cookbook/docs/package/container gates practical on the agent host.
Run vibe19 + vibe20 suites + clean-install + container smokes. Prove:

```text
vibe19 → pandas oracle → findings → WattLab v3 → vibe20 load
→ open_fdd.ecm_engineering → EnergyPlus path still available

open-fdd base install → no pandas
open-fdd[oracle] → pandas rules available
production container → SQL/DataFusion FDD path
```

GitHub gate: all Milestone A PRs merged; no actionable CodeRabbit left; GHCR
green; digests tested; branches clean; no undocumentated migration shims.

---

## 10. Stop conditions

Do **not** stop merely because a plan, matrix, copy, local-only green, or
moving tag exists. Stop when exit criteria met **or** genuine blocker
(credentials, permissions, missing secrets, optional private dataset, dirty
unrelated work, unsafe product decision). Then: finish non-blocked work; record
exact command/error; leave repos recoverable.

---

## 11. Final agent report

Fill [`COMPLETION_REPORT.md`](COMPLETION_REPORT.md) with verified facts only.
