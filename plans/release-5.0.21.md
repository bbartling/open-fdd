# Release 5.0.21 cycle ledger

Internal; excluded from the Pages site (`docs/_config.yml` excludes `plans/**`). Procedure:
`C:\Users\ben\Documents\prompts\2026-11-17-openfdd-issue-validation-and-closure.md`.

States: `OPEN -> OWNED -> PR READY -> INDEPENDENTLY VERIFIED -> INTEGRATED -> RELEASED -> CLOSED`.
Issues stay open after integration (READY FOR RELEASE); Grok posts closure receipts after the default-branch merge.

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
