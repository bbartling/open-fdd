# Release 5.0.21 cycle ledger

Internal; excluded from the Pages site (`docs/_config.yml` excludes `plans/**`). Procedure:
`C:\Users\ben\Documents\prompts\2026-11-17-openfdd-issue-validation-and-closure.md`.

States: `OPEN -> OWNED -> PR READY -> INDEPENDENTLY VERIFIED -> INTEGRATED -> RELEASED -> CLOSED`.
Issues stay open after integration (READY FOR RELEASE); Grok posts closure receipts after the default-branch merge.

## Final state (2026-11-19, Claude)

`release/5.0.21` is 51 squash commits ahead of `master`. Every PR below was accepted by the other agent at its exact head, merged with `--match-head-commit`, and patch-checked (stacked PRs verified by applying their diff to the pre-merge release). No topic PR into the release is open; this ledger merges last, then `release/5.0.21` → `master`.

### Merged into release/5.0.21

| PR | Squash | Subject |
|---|---|---|
| # | `3b1a1d3b` | chore: bump app to 5.0.21 for next patch cycle |
| # | `34fbd794` | chore: VERSION 5.0.21 |
| # | `7642f407` | tutorials: DuckDB browser AFDD walkthrough (fake AHU data, SQL fault rule) |
| #1674 | `fc140966` | chore: 5.0.21 cycle ledger; run validation CI on release/** without publishing Pages |
| #1675 | `b42f2f83` | docs: link the beginner DuckDB browser tutorial from the SQL borrowing pages |
| #1676 | `125afb6a` | SV sweeps: accept the canonical percent_0_100 relative-humidity unit (#1669) |
| #1677 | `9aacecfd` | ml: ModeGated refit replaces the whole baseline; failed fit is unusable; per-row assessment (#1666) |
| #1678 | `f4378cac` | ml detect: require an explicit training source; label train/evaluation phases; evaluation-only counts (#1665) |
| #1679 | `ce325135` | ml metrics: window eligibility from elapsed time at the cadence; window_coverage; benchmark excluded coverage (#1666) |
| #1683 | `90fdf54b` | rules: explicit equipment context for run_all/run_rule, summarize() explains skips (#1661) |
| #1692 | `a1fc4a2f` | sparql client frames: carry the hook's resolved run proof (#1635, client half) |
| #1693 | `d5fe686b` | ml: assessed vs unassessed rows for PCA and gray-box (#1666) |
| #1690 | `23c4a093` | open-fdd-nf export-folder: one equipment's SI history as a device folder (#1653) |
| #1697 | `9c8075fd` | ontology audit: --extensions completeness check for Open-FDD extension terms (#1569) |
| #1699 | `85d2bd21` | SCHED-247: unknown proof is not OFF; durations and completeness (#1670) |
| #1703 | `dbdb7e8e` | nf_app_sync: refuse --dry-run outside install before any login (#1634) |
| #1705 | `be62de7c` | doctor: errored runs show as failed; scheduled hooks need a success within two intervals (#1638) |
| #1664 | `6bf8baf2` | docs: remove two stale prompt notes |
| #1706 | `a5e219e6` | FDD hook: synthesized occ_mode follows the saved occupancy calendar on every engine (#1636) |
| #1711 | `9f78d949` | sparql-data hook: answer the resolved run proof per equipment (#1635, hook half) |
| #1713 | `9df54ae6` | ci: docs-pages builds of different PRs no longer cancel each other |
| #1680 | `691956f1` | plans: Grok 5.0.21 checkpoint |
| #1715 | `03bb72bf` | Timelines: a gated rule with no proof has no timeline rows, like its summary (#1631) |
| #1717 | `edbff81a` | runner: the fallback run proof gets the rule's startup delay (#1631) |
| #1687 | `351d68cd` | ml detect: roles used, per-row flag explanations, explicit zero-alarm plot (#1660) |
| #1694 | `2e21de6d` | open-fdd-ml detect help: --method summary, --train-until zone wording (#1662) |
| #1704 | `b44cd02f` | nf_app_sync: push preflights the Timescale schema (#1633) |
| #1682 | `415a5e44` | ml: per-method role requirements, open-fdd-ml methods, single-zone gray-box (#1659) |
| #1718 | `1a0ff3a1` | Run proof: refuse only analog commands with no unit, inside the resolver (#1631) |
| #1712 | `178f90ca` | Parity: weather as-of join and pandas mechanical-cooling proof close ECON-3 / ECON-7 / MECH-OAT-1 gaps (#1642) |
| #1691 | `73a719b3` | ml: review a saved SQL fault episode against ML evidence (#1667, first slice) |
| #1714 | `acb3ddc0` | GL36 rules keep their own fan gate when "Require motor status" is off (#1631) |
| #1710 | `1317fe40` | TRIM-3/4, CW-FAN-1, CW-OPT-1: an unbound legacy plant proof is unknown, not OFF (#1631) |
| #1700 | `c75fcf98` | SV sweeps: SV-STALE is missing data; gaps scored once; stale tuner migration (#1673) |
| #1681 | `e5912628` | anomaly/ml: one activity policy for screen and ml detect (#1656) |
| #1716 | `1a45039d` | FC4: count operating-state entries over proven samples only (#1631) |
| #1686 | `fed1f2f3` | ml: open-fdd-ml make-folder and the device-folder format (#1652) |
| #1728 | `362ba780` | ci: cancel superseded runs, skip feature-branch push doubles, defer ZAP off release PRs |
| #1695 | `0c235473` | ml: labeled held-out evaluation of the episode review policy (#1667 acceptance 5) |
| #1698 | `f3341bd9` | ml detect: publish assessed vs unassessed rows in flags.csv and summary.json (#1666) |
| #1724 | `530575be` | COIL-PERF: generic coil performance rule, heating and cooling (#1641, first slice) |
| #1684 | `3396602b` | anomaly screen: defaults run on what is installed; iforest opt-in (#1654, #1658) |
| #1702 | `3734b72f` | SV sweeps: bounded as-of run proof; unknown proof cannot fault (#1631) |
| #1719 | `51f1a9c4` | Gated rules report active_hours; fault_pct = fault / active_hours (#1631) |
| #1708 | `75149814` | FDD tuners: one user-facing timer per rule; fixed internal safeguards (#1671) |
| #1696 | `dc973d8a` | ml: synthetic end-to-end review demo runnable from the wheel (#1667 acceptance 6) |
| #1685 | `a5f8af2b` | anomaly screen: summary.json, --json, --no-plots, --tz (#1655) |
| #1688 | `0bee54d0` | anomaly MAD: resolution floor + near_constant skip (#1657) |
| #1689 | `da8c64af` | PyPI docs/help: absolute README links, wheel examples, no-NF note (#1662) |
| #1729 | `347fded2` | COIL-PERF reports active_hours; fault_pct = fault / active_hours (#1631, #1641) |
| #1709 | `215333f1` | FDD Tuners: grouped sliders, motor-status checkbox, step snapping, ordered pairs (#1672) |

### Issues closed in this cycle

- #1631 Run-proof gate: SQL/pack coverage semantics and runner denominator follow-ups
- #1633 Deploy: nf_app_sync push should preflight the Timescale schema version before writing hooks
- #1634 nf_app_sync: --dry-run is silently ignored by push (it writes and restarts the app)
- #1635 SPARQL client frames: carry the resolved run proof so client-side rules gate like the hook
- #1636 FDD hook: synthesized occ_mode ignores the saved weekly occupancy calendar
- #1638 Health reporting: surface errored hook runs (no end time, queue failed=0) as failures
- #1652 PyPI tools: document the device-folder format and add a command to build one from a CSV or the LBNL files
- #1654 open-fdd-anomaly screen: default methods fail on an [ml]-only install and --help does not name the extra
- #1655 open-fdd-anomaly screen: machine-readable summary, --no-plots and local time zone for scheduled runs
- #1656 open-fdd-anomaly screen ignores whether the unit is running; ml detect requires it
- #1657 Anomaly MAD flags quantization noise on near-constant signals
- #1659 ML detectors: per-equipment role sets and clear role requirements (furnace / RTU / heat pump)
- #1660 open-fdd-ml detect: report the roles actually used, and add per-role contributions to flags.csv
- #1662 PyPI docs and help text: broken relative links, repo-only examples, internal names, missing details
- #1666 ML scoring and benchmark: preserve unassessed rows and enforce elapsed-time coverage
- #1669 fdd.unit_declares_quantity omits the percent_0_100 alias on relative humidity
- #1670 SCHED-247 cannot distinguish missing proof from proven OFF
- #1671 One user-facing delay timer per rule in tuning_catalog.json and SQL templates
- #1672 Per-rule tuning sliders in the Open-FDD UI
- #1673 SV sweep: SV-STALE duplicates SV-FLATLINE; make stale a data-missing/gap rule and dedupe gap scoring

### Moved to 5.0.22

- #1567 Install paths: support and test NF-native app install methods (git URL, console upload, single-hook deploy), stop depending on nf_app_sync.py + SSH/VPN, document non-SSH and IT-department setup
- #1614 Deploy tooling: safe prune for orphan app points (removed app ids) and long-stale FDD result points
- #1615 doctor: host health (memory, disk, restarts) via the NF API, no SSH (Lite hosts)
- #1616 README: Grok Bot and agent skills section, one canonical skills tree, badge/link drift checks
- #1624 CI: verify Full hook and run-result authorization on disposable Normal Framework
- #1639 Expanded parity stress testing beyond the three-way SI tiers
- #1640 Port DataFusion back as a fourth SI parity engine (pandas == DataFusion == SQL)
- #1641 Generic coil performance rule (heating and cooling) for any coil-bearing equipment
- #1642 Tighten SQL-vs-pandas parity pins: a downstream SQL port beats them on 4x3/8x7
- #1643 NF plugin UI: Overview is laggy again — default to plant + zone temps, move heavy plots onto their own routes
- #1644 Refactor nf-app/hooks/fdd.js (~1,444 lines) into small, progressive, easy-to-follow modules
- #1645 Lite edition: replace SQLite-WASM / PGlite with a warm in-memory DuckDB engine + Parquet history (Full stays on Timescale)
- #1646 Rule tuners and RCx analytics missing vs latest reference
- #1649 Restore SQL-driven analytics (incl. z-score anomaly detection) with pandas == SQL parity across Postgres/Timescale, DuckDB, SQLite
- #1668 Mock NF and test fakes diverge from real NF 3.10.x: two installer bugs hidden + contract gaps
- #1707 Statistic/metric rules (AVG-ZONE-TEMP, ZONE-COMFORT-PCT, FAN-RUNTIME-HOURS) are written to fdd.rule_result as INCONCLUSIVE every run
- #1721 5.0.22: labeled-fault evaluation (LBNL data), ML fault probability calibration, SQL-vs-ML agent tool
- #1723 fault_pct denominator: align SQL active_hours with the pandas operational gate per rule family
- #1725 FC8: eps_sat and supply_tol alias render differently in JS and Python when both are saved
- #1726 Tuner step grid: 66 shipped defaults are off the snap grid (the default cannot be re-entered after a change)
- #1727 Docs: CMMS work-order triage page, and a short write-your-own-rule guide (pandas + SQL)
- #1730 Parity test: SPARQL-client vs oracle frames fail on pandas 3 (datetime index resolution us vs ms)

### Open, not labelled 5.0.22 (owner to confirm)

- #1569 Data modeling: formal ontology extension policy (own namespace, subclass existing Brick/223P/Haystack concepts, queryable + validated extensions)
- #1653 open-fdd-nf: export one equipment's history as a device folder (units and roles from the model)
- #1658 Anomaly Isolation Forest always flags about 1% of rows; make it opt-in and say so
- #1661 open_fdd.rules.run_all: accept equipment_type and explain an all-skipped run
- #1663 Tracking: open-fdd 4.5.12 PyPI agent-tool fixes from the 4.5.11 field test
- #1665 ML detect: require an explicit healthy training source and distinguish training from evaluation
- #1667 Agent review: join SQL fault episodes with ML evidence and validate alert reduction
- #1720 5.0.21 (proposed): portable SQL rule scorecard + offline privacy-preserving review bundle (open-fdd-scorecard)

## Writer slot

| Field | Value |
|---|---|
| Current writer | Claude |
| Checkout | `C:\Users\ben\Documents\open-fdd` |
| Branch in checkout | see the latest checkpoint below |
| Claimed paths | `.github/workflows/**`, `plans/**`, `sql/fdd/**`, `open_fdd/rules/sensor_sweep_catalog.py`, `nf-app/hooks/lib/engines.js`, `tests/parity/**`, `open_fdd/data/units.json` |
| Handoff | Grok may triage read-only; ask in this file before taking the slot |

## Baseline (pickup 2026-11-17)

- `release/5.0.21` = `7642f407` (tracks origin). App `VERSION` and `nf-app/package.json` = 5.0.21. PyPI package = 4.5.11.
- Default branch `master` = `95266656`. Ruleset "Protect master" (default branch only): squash merges,
  required checks `Gitleaks`, `npm audit (nf-app)`, `pandas == SQL parity / pandas oracle vs SQL pack`,
  `pandas == SQL parity / pandas == SQL == SPARQL-client`, strict. `release/5.0.21` has no protection: topic PRs
  into it must show the same checks green on their head before merge (discipline, not enforcement).
- 42 open issues (list below), 1 open PR (#1664).
- Dirty files at pickup (`docs/rules/borrowing-sql.md`, `tutorials/duckdb_sql_parity/README.md`, beginner-tutorial
  links) were stashed as `tutorial-links (preserve)` and are carried on topic branch `docs/tutorial-links`.
- Pre-existing TEMP worktrees (not created by this cycle; owner's to retire): `%TEMP%\ofdd-1608`
  (`feat/run-proof-gate`, upstream gone), `%TEMP%\ofdd-1608-base`, `%TEMP%\open-fdd-ip-oracle-worktree`.
  Leave them until their branches are confirmed merged/superseded.

## CI routing (audited 2026-11-17)

| Workflow | Trigger before | Change in this cycle |
|---|---|---|
| `security.yml` (calls `parity.yml`; ZAP, npm audit, gitleaks) | every push/PR | none needed |
| `nf-app-ci.yml` | every push/PR on paths | none needed |
| `python-matrix.yml` | push master; PR any | push adds `release/**` |
| `duckdb-tutorial.yml` | push master; PR any | push adds `release/**` |
| `docs-pages.yml` | push/PR master,main | push/PR add `release/**`; deploy job now also requires `github.ref == refs/heads/master` |
| `parity-stress.yml` | schedule (master) + dispatch with `ref` input | none; dispatch with `--ref release/5.0.21 -f ref=release/5.0.21` and verify checkout SHA |
| `nf-app-release.yml`, `publish-open-fdd.yml` | tags / dispatch | none; publishing stays on final tags; use `dry_run=true` for validation |

## Issue table

Owner C = Claude, G = Grok. "Next" is the next concrete action.

| # | Owner | Scope | State | Branch / PR | Next |
|---|---|---|---|---|---|
| 1669 | C | `percent_0_100` RH alias in all helper copies + units metadata; long-form sweep vector | INTEGRATED (READY FOR RELEASE) | #1676 -> `125afb6a` | Grok acceptance PASS on `723d90d3`; close after release |
| 1670 | C | SCHED-247 OFF/unknown/completeness, honest observed duration | PR READY | #1699 (`fix/1670-sched247-proof`) | Grok acceptance; completeness policy 0.9 x max(window, 24 h) is an owner-visible semantic |
| 1673 | C | SV-STALE = gap/missing; SV-FLATLINE = stuck values; dedupe silence; expected series; stale tuner migration | PR READY | #1700 (`fix/1673-stale-vs-flatline`) | Grok acceptance; then #1671 one-timer cleanup for FLATLINE/RANGE/SPIKE |
| 1631 | C | Run-proof coverage/denominator follow-ups | PR READY (item 1) | #1702 (`fix/1631-sweep-proof-asof`, stacked on #1700) | sweep as-of proof join done (23.9 h repro -> 0); remaining items: ECON-7/DMP-1/VLV-1 coverage, FC4 order, TRIM-3/4, CW-FAN/OPT, FC13 placeholder, runner denominator + startup delay, command-unit check, AHU/pump proof fixtures, IRI identity |
| 1635 | C (+G client) | Resolved proof into SPARQL client frames | PR READY | client #1692 merged; hook #1711 | alignment (exact vs as-of) after #1702 |
| 1636 | C | Occupancy calendar synthesis | PR READY | #1706 (`fix/1636-occupancy-calendar`) | Grok acceptance; Timescale UPDATE verified only by the CI Timescale job / disposable instance |
| 1639 | C | Expanded SI stress, seeds, replay | OPEN | | |
| 1640 | C | DataFusion parity adapter | OPEN | | |
| 1641 | C | Generic coil performance rule | OPEN | | |
| 1642 | C | Divergences + implementation-aware pins | PR READY | #1712 (`fix/1642-parity-pins`) | VAV-6 waits on the #1631 gate-off decision; ask 3 (downstream bands) open |
| 1646 | C | Tuners, motor-status wording, RCx coverage | OPEN | | after #1671/#1672 |
| 1671 | C | One visible timer per rule; tuner migration | PR DRAFT | #1708 (`fix/1671-one-timer`, stacked on #1700) | internal_constants; byte-identical SQL; Node 790/790, Python 540/7 |
| 1672 | C | Sliders/booleans, SI validation, scoped persistence | PR DRAFT | #1709 (`fix/1672-tuner-sliders`, stacked on #1708) | grouped sliders, Require motor status, step snap, ordered pairs; no live screenshot |
| 1649 | C | SQL analytics restoration + pandas parity | OPEN | | phase 2 |
| 1643 | C | Fast Overview, lazy heavy views | OPEN | | phase 3 |
| 1644 | C | Split `hooks/fdd.js` into modules | OPEN | | phase 3 |
| 1645 | C | Native DuckDB Standard, Parquet, notebook, Lite migration | OPEN | | phase 3; needs real NF targets |
| 1567 | C | NF-native install paths, non-SSH docs | OPEN | | A/C/D live-NF checklist preserved on the issue (comment 6967806025) |
| 1614 | C | Safe prune planning | OPEN | | phase 3 |
| 1615 | C | Host health via NF API | OPEN | | phase 3 |
| 1616 | C | Canonical skills, README/badges, link drift | OPEN | | phase 3 |
| 1624 | C | Disposable real-NF CI | OPEN | | needs disposable NF |
| 1633 | C | Timescale preflight before app writes | PR READY | #1704 (`fix/1633-push-schema-preflight`) | Grok acceptance; release-notes line per SCHEMA_VERSION bump goes in the final release PR |
| 1634 | C | True `--dry-run` | PR READY | #1703 (`fix/1634-dry-run-guard`) | refuses --dry-run outside install; Grok acceptance |
| 1638 | C | Errored/unfinished run health | PR READY | #1705 (`fix/1638-errored-run-health`) | Grok acceptance; live check with a failing hook on disposable NF (#1624) |
| 1668 | C | NF mock/fakes contract + installer fixes | OPEN | | phase 3 |
| 1569 | C (+G tool) | Ontology extension namespace/SHACL/doctor | PARTIAL | #1697 merged 9c8075fd (Python `--extensions` audit) | RDF half (namespace, TTL labels/definitions, SHACL) open; phase 4 |
| 1652-1662, 1665-1667 | G | Python/PyPI/ML tooling | OPEN | Grok PRs | Claude reviews |
| 1663 | G | 4.5.12 tracker | OPEN | | after children + release |

## PRs

| PR | Author | Purpose | State | Next |
|---|---|---|---|---|
| #1664 | owner | delete two stale `docs/prompts` notes (+ checklist moved to #1567) | Grok OK; doc fix `c80c3478` = Grok option (a); CI backlog | merge when green |
| #1674 | Claude | ledger + CI routing | merged `fc140966` | done |
| #1675 | Claude | tutorial links | merged `b42f2f83` | done |
| #1676 | Claude | #1669 | merged `125afb6a` | done |
| #1699 | Claude | #1670 SCHED-247 | ready | Grok acceptance, CI |
| #1701 | Claude | this ledger | open | merge any time (plans only) |
| #1702 | Claude | #1631 sweep as-of proof | draft, stacked on #1700; head 36a0a66b | merge after #1700 |
| #1708 | Claude | #1671 one timer per rule | draft, stacked on #1700 | merge after #1700 |
| #1709 | Claude | #1672 tuner sliders | draft, stacked on #1708 | merge after #1708 |
| #1710 | Claude | #1631 TRIM-3/4 plant proof | ready (base release) | Grok acceptance, CI |
| #1711 | Claude | #1635 hook half: run_proof in sparql-data | ready (base release) | Grok acceptance, CI |
| #1712 | Claude | #1642 ECON-3/7, MECH-OAT-1 parity gaps | ready (base release) | Grok acceptance, CI |
| #1713 | Claude | CI: docs-pages concurrency per PR | ready | Grok acceptance |
| #1714 | Claude | #1631 gate-off keeps GL36 fan gate (Ben call 2) | ready | Grok acceptance, CI |
| #1715 | Claude | #1631 timeline empty when no proof | ready | Grok acceptance, CI |
| #1716 | Claude | #1631 FC4 entries over proven samples | ready | Grok acceptance, CI |
| #1717 | Claude | #1631 fallback proof startup delay | ready | Grok acceptance, CI |
| #1718 | Claude | #1631 command proof needs a unit | ready | Grok acceptance, CI |
| #1703 | Claude | #1634 dry-run guard | ready | Grok acceptance, CI |
| #1704 | Claude | #1633 push schema gate | ready | Grok acceptance, CI |
| #1705 | Claude | #1638 doctor run health | ready | Grok acceptance, CI |
| #1706 | Claude | #1636 occupancy calendar | ready | Grok acceptance, CI |
| #1700 | Claude | #1673 SV-STALE split | ready; head 47478f87 (Timescale parity harness fixes) | Grok acceptance, CI |
| #1677 #1678 #1679 #1683 #1690 #1692 #1693 | Grok | ML/tooling | merged (Claude review ACCEPT, CI green) | done |
| #1680 #1684 #1685 #1686 #1689 #1697 | Grok | tooling | Claude ACCEPT (nits posted) | merge when CI green / stack base lands |
| #1687 #1694 #1698 | Grok | ml detect | Claude ACCEPT; conflicts after the squash merges | Grok merges release into branch |
| #1681 #1682 #1688 #1691 #1695 #1696 | Grok | ML | Claude CHANGES REQUESTED (verified blocking findings) | Grok fixes; #1684/#1685/#1688/#1689 wait on #1681, #1686 on #1682 |

## Checkpoints

### 2026-11-17 (Claude, session 1)

- Branch `chore/5.0.21-ledger-ci` from `7642f407`: this ledger + CI routing.
- Next: open the ledger/CI PR, the tutorial-links PR, then `fix/1669-rh-percent-alias`.

### 2026-11-18 ~02:00 local (Claude, resumed after the weekly reset)

- Writer slot: Claude. Checkout on `chore/5.0.21-ledger-update`, then `fix/1631-sweep-proof-asof`.
- Review finding routed to the SQL lane: the sweep proof join is fail-open (`COALESCE(energized, 1)` on an exact
  timestamp join) while the SPARQL client is fail-closed (exact join). Decision: bounded as-of join, proof held for at
  most MAX_GAP_HOURS, older or absent = unknown (cannot fault); the client follows (#1631 / #1635).
- pandas runner quality-nulled out-of-range sweep values (fixed in #1700).
- Known local-only failures: `test_client_frames_are_the_oracle_frames` (pandas 3.0.6 index unit); CI passes.

### 2026-11-18 ~03:30 local (Claude)

- Opened #1702 (#1631 item 1), #1703 (#1634), #1704 (#1633), #1705 (#1638). #1700 (#1673) ready after its suite.
- GitHub Actions backlog: new PRs sit with 20+ pending checks; merges wait for green on the exact head.
- Next code items (priority order): #1671 tuner contract -> #1672 sliders; #1631 remaining items; #1636; #1641; #1642;
  #1635 hook half (sparql-data emits run_proof/run_proof_series); then #1649 analytics.

### 2026-11-18 ~00:30 local (Claude): checkpoint 2

- 5-hour window at 78%: checkpointed instead of starting #1671. Session-only merge sweep scheduled 04:47 local.
- Opened #1706 (#1636): saved calendar > NF schedule > default on every engine; pandas overnight-shift mask fixed.
- Resume prompt: `C:\Users\ben\Documents\prompts\2026-11-18-openfdd-5.0.21-resume-checkpoint-2.md`.

### 2026-11-18 ~04:50 local (Claude): merge sweep 1

- Merged #1697 (Grok, #1569 Python half) as 9c8075fd; the squash patch-id equals the reviewed head `d313eca5`.
- Nothing else qualified: Grok has been offline since ~20:50, so no Claude PR has acceptance yet. #1664 has a
  conditional OK on an older head. The Grok stacks are blocked on changes requested (#1681, #1682, #1688, #1691,
  #1695, #1696) or conflicts (#1687, #1694, #1698).
- CI fixes:
  - #1700: the Timescale parity test now passes `sweep_series` to pglite (both engines were correct for their inputs);
  - #1702: an f-string that only parsed on Python 3.12+.
- Next: #1671 tuner contract.
- ~06:30: #1700 head 47478f87 (the Python Timescale parity harness drops the sweep_series declaration, like the pandas oracle); #1702 merged it in.
  Opened #1708 (#1671) as a draft stacked on #1700. Next: #1672 sliders.
- ~07:20: opened #1709 (#1672) as a draft on #1708. Next: #1631 remaining items, #1641, #1642, #1639.
- ~08:00: opened #1710 (#1631 TRIM-3/4). Posted the #1631 triage: the denominator (`active_hours`) and the gate-off fan gate on the FC rules need Ben's call; FC4, CW-FAN/OPT, fallback startup delay, command-unit check and the SQLite timeline remain.
- ~09:15: opened #1711 (#1635 hook half). The SPARQL parity leg now uses the hook's run_proof (no harness stamp).
- ~11:30: #1702 window as-of (150b5862) after the 365 s Timescale run. Opened #1712 (#1642): ECON-3 / MECH-OAT-1 exact on basic tiers, ECON-7 0.25 h; baselines 52/19 and 49/22.
- ~15:30: Ben approved both #1631 design calls ("Yes, as proposed"). #1714 fan gate; active_hours built (PR after the full suite). #1710 gained CW-FAN/OPT. #1713-#1718 opened; Grok tasked on #1701 (review, own PR fixes, Linux tests).

### 2026-11-18 resume after the 5-hour reset (Claude)

- Merged (Grok-accepted exact heads, squash patch identical, issues READY FOR RELEASE): #1699 (#1670), #1703 (#1634),
  #1705 (#1638), #1664, #1706 (#1636), #1711 (#1635 hook half).
- Grok accepted, waiting on CI: #1704 (re-review after the push-schema fix), #1712, #1713, #1714, #1715, #1716, #1702.
- Grok's changes requested, addressed and awaiting re-review:
  - #1710: CW-APR-1 had the same legacy ELSE 0;
  - #1718: start/stop commands stay usable; the refusal moved inside the resolver loop;
  - #1719: the fault_pct denominator is reported in the parity verdict and documented; aligning the gates is a follow-up.
- Claude re-reviewed Grok's release merges into #1687, #1694 and #1698: every reviewed line is unchanged or now in
  release; accepted at daecdb0c / 8595c6b7 / 07338a4f.
- #1700 merged release (fdd.js: declaredSweep + #1636 occupancy); #1702, #1708 and #1709 brought up to date. Timescale suite
  45/45 locally against a disposable container.
- A recurring session merge sweep runs at :17 and :52.

