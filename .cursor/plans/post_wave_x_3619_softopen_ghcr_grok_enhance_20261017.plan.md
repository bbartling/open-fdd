---
name: Wave-X 3.6.18 Soft-OPEN — GHCR roll + enhanced Grok (3619)
overview: "Supersedes 3618. Merge #1286 + all Soft-OPEN branches (no stale open PRs). Bump 3.6.18 → wait GHCR refresh → Grok re-pins Railway+ACME → validates missing Timescale data on hub → enhanced Soft-OPEN (lessons 01/03/05, softopen suite, API endpoint data+errors). All agent work in Linux /tmp. No backups. Delete Rust target/ + leftover binaries after local compiles. Soft-OPEN ≠ FQ. No screenshot/browser Soft-OPEN. ZAP later."
todos:
  - id: t0-carry
    content: T0 — Carry baseline from 3618 (sha-52e1045 ART; lessons 03/05 local PASS on tip)
    status: completed
  - id: t1-1286-green
    content: T1 — #1286 CI fully green (fdd-sql-pack + Rust + protocol; no stale pending)
    status: completed
  - id: t2-merge-all
    content: T2 — Merged #1286 (27d9c742); #1287 is 3.6.18 bump — merge when green; delete stale Soft-OPEN branches
    status: in_progress
  - id: t3-bump-3618
    content: T3 — #1287 bumps VERSION/Cargo 3.6.17 → 3.6.18 + Soft-OPEN contract pins
    status: in_progress
  - id: t4-wait-ghcr
    content: T4 — Wait GHCR Publish stack green (refresh); resolve newest-by-created for central/web/mqtt (not :nightly sort)
    status: pending
  - id: t5-tip-refresh
    content: T5 — Refresh GROK_SOFTOPEN tip + plan pins to 3.6.18 / sha-<newest>
    status: pending
  - id: t6-enhance-grok
    content: T6 — Enhance Grok Soft-OPEN bar (API endpoint data+errors only — no screenshots)
    status: completed
  - id: t7-kick-grok
    content: T7 — Kick Grok after GHCR tip — Grok owns Railway hub + ACME re-pin, then API Soft-OPEN validate (no screenshots)
    status: pending
  - id: t8-db-missing
    content: T8 — Grok/DB gate — mapped roles with 0 Timescale samples on Railway = FAIL (BUILDING_100 / SYNTH re-seed as needed, owner OK)
    status: pending
  - id: t9-1282-pool
    content: T9 — #1282 import pool timeout / half-import (capacity / ART KEEP)
    status: pending
  - id: t10-1284-metric
    content: T10 — #1284 metric-c-v2 pack (capacity / ART KEEP)
    status: pending
  - id: t11-haystack
    content: T11 — Haystack Soft-OPEN ≠ FQ (capacity / ART KEEP)
    status: pending
  - id: t12-fc1-roles
    content: T12 — Lesson 03 FC1 roles fixed on #1287 (local PASS)
    status: completed
  - id: t13-overlay-series
    content: T13 — P0-3 residual — per-sample fault series overlay (capacity / ART KEEP)
    status: pending
  - id: t14-hygiene-tmp
    content: T14 — Linux /tmp only for worktrees/compiles; rm -rf target/ + leftover rustc/test binaries; no Desktop crates
    status: pending
  - id: t15-grok-art
    content: T15 — Absorb Grok ART — per-issue CLOSE/KEEP/OPEN-NEW; softopen + DB evidence; never overwrite prior ART
    status: pending
  - id: t16-exit
    content: T16 — Soft-OPEN ≠ FQ exit; no stale Soft-OPEN branches; morning STATUS; ZAP deferred
    status: pending
isProject: true
---

# Wave-X 3.6.18 Soft-OPEN — GHCR roll + enhanced Grok — 2026-10-17 (3619)

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

**Status: SHIPPING** — [#1286](https://github.com/bbartling/open-fdd/pull/1286) **merged**. [#1287](https://github.com/bbartling/open-fdd/pull/1287) **3.6.18 bump + lesson 03 FC1** in flight. Supersedes [3618](post_wave_x_3618_softopen_api_parity_grok_20261017.plan.md).

**Ship path:** [#1286](https://github.com/bbartling/open-fdd/pull/1286) green → **merge all Soft-OPEN branches** (no stale open PRs/branches when done) → bump **3.6.18** → **wait GHCR refresh** → Grok **re-pins Railway + ACME** → Grok **validates missing Timescale data** on the hub → enhanced Soft-OPEN (lessons 01/03/05, softopen suite, **JWT API data + errors**). Soft-OPEN ≠ FQ. **No backups.** **No screenshot / headed-browser Soft-OPEN.** ZAP later.

## Global constraints (every task)

| Rule | Detail |
| --- | --- |
| **Linux `/tmp` only** | Worktrees, patches, local compiles, ART scratch under `/tmp/openfdd-softopen/` (or `/tmp/open-fdd-wt-*`). **Never** compile Rust on Desktop. |
| **No backups** | No site / DB / volume Soft-OPEN backups. No `compose down -v` / volume prune. |
| **No leftover Rust binaries** | After any local `cargo` / clippy / test: `rm -rf target/` and any orphaned test/binary artifacts in that worktree. |
| **GHCR refresh** | After merge + bump, wait Publish stack green; pin by OCI `created` (`./scripts/ghcr_newest_by_created.py`), never `:nightly` sort. |
| **No stale branches** | When ship is done: Soft-OPEN feature PRs merged or closed; remote branches deleted; no orphan Soft-OPEN worktrees left claiming tip. |
| **Grok owns pin** | Grok updates **Railway hub** (central/web/mqtt) **and ACME** (fieldbus → hub MQTTS) to the new tip, then validates. |
| **DB missing-data gate** | On Railway Timescale: package-mapped roles with **0 samples** = Soft-OPEN **FAIL** (not PASS). Re-seed BUILDING_100 / import SYNTH when owner OK. |
| Soft-OPEN ≠ FQ | Timescale only. No Parquet co-canonical. No BACnet writes without human approval. |

## Why 3619

3618 landed P0s + Soft-OPEN suite + SYNTH_03 + lessons 03/05 on the PR. Local tip proof (`sha-52e1045`): lesson 03 SPARQL→pandas→`open_fdd.rules` **PASS**; lesson 05 semantic-meta mutate **PASS**. Remaining work is the **ship gate** + **Grok pin + DB gap Soft-OPEN** + residuals.

## Inherited (done on #1286 / tip)

| Item | Evidence |
| --- | --- |
| P0 SPARQL Content-Type, FDD results types, RCx `ahu`→`air` | #1286 |
| #1278 column≠role history candidates | #1286 `e7c888b` |
| #1277 hub assert + fieldbus scope | #1286 |
| `scripts/softopen/` + plot-bool gates | #1286 |
| SYNTH_03 fixture (#1281) | `scripts/fixtures/softopen/` |
| Lessons 03 + 05 | local PASS on tip 3.6.17+52e1045 |

## Ported unfinished (from 3618 → here)

| Was | Now | Notes |
| --- | --- | --- |
| T2 hygiene / #1286 green | T1–T2 | finish CI; **merge all Soft-OPEN branches** |
| T11–T14 ship + Grok | T3–T7 + T15 | **no Grok before GHCR tip** |
| P0-1 B100 / mapped-0 | **T8** | Grok validates **missing DB data on Railway** |
| T7 #1282 / T9 #1284 / T10 Haystack / overlay | T9–T11 / T13 | capacity |
| — | **T6 + T12 + T14** | enhance Grok; FC1 roles; `/tmp` + rust hygiene |
| T15 exit | **T16** | + **no stale Soft-OPEN branches** |

## Soft-OPEN bar (after GHCR tip on Railway + ACME)

1. **Grok re-pin** Railway central/web/mqtt + ACME full tip stack (fieldbus on-prem → hub MQTTS; Timescale only). **No backups.**
2. **`assert_hub_env_after_repin.sh`** PASS — live MQTT proxy ≠ stale Soft-OPEN port; edges≥1; ingest climbs ≥2 publishes. No Soft-OPEN UI PASS while edges=0.
3. **Database (Railway Timescale) — missing data** — for each Soft-OPEN site under test (BUILDING_100 / SYNTH_* / unique Soft-OPEN id): every **mapped** role must resolve history with **sample count > 0**. Mapped-but-0 = **FAIL**. Record equipment/role gaps in ART; re-seed only with owner OK.
4. **Each open GH issue** — tip evidence → CLOSE / KEEP / OPEN-NEW (owner closes).
5. **`scripts/lessons/` on Railway** — unique Soft-OPEN `building_id` **or** proven `SYNTH_03`:
   - **01** sites/equipment SPARQL
   - **03** SPARQL → point-resolve → **pandas DF** → **`open_fdd.rules` FC1** — status must **not** be `SKIPPED_MISSING_ROLES` / empty-NaN (T12 if needed)
   - **05** semantic-meta GET → dry_run → CAS PUT → GET prove → restore
6. **`scripts/softopen/run_softopen_railway.py`** — stress 01/03/08/09/10; pandas==SQL fail-closed (#1253).
7. **Product Soft-OPEN = API endpoints only** — JWT GET/POST for health, AFDD, Overview analytics envelopes, FDD plot/series, RCx presets. Pass = **2xx + expected non-empty JSON** (or documented N/A). Fail = **4xx/5xx**, empty applicable payload, or error body. **No screenshots, no Playwright/Selenium Soft-OPEN, no SPA click Soft-OPEN.**
8. **Branch hygiene** — Soft-OPEN PRs merged/closed; stale remote branches deleted; `/tmp` worktrees cleaned.
9. **ZAP** — deferred until this functionality Soft-OPEN is green.

## Order (do not skip)

1. **T1** — Wait #1286 fully green (no fails).
2. **T2** — Merge #1286 **and** any other open Soft-OPEN PRs into `master`; delete merged remote branches; no stale Soft-OPEN PR left open claiming tip.
3. **T3** — Bump **3.6.18** (`VERSION` + Cargo workspace patch) in `/tmp` worktree; after compile tests **`rm -rf target/`**.
4. **T4** — **Wait GHCR refresh** (Publish stack green); `./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web openfdd-mqtt`.
5. **T5–T6** — Refresh tip docs + enhanced Grok Soft-OPEN text.
6. **T7** — Kick Grok — Grok **updates Railway + ACME** to tip, then Soft-OPEN.
7. **T8** — Grok/DB missing-data Soft-OPEN on Railway (FAIL-closed).
8. **T9–T13** — residuals as capacity (ART KEEP if deferred).
9. **T14** — Confirm `/tmp`-only + no leftover Rust binaries.
10. **T15–T16** — absorb ART; exit Soft-OPEN ≠ FQ; **no stale Soft-OPEN branches**.

## Forbidden

- Soft-OPEN **backups** (site / DB / volume).
- Desktop Rust compiles / leaving `target/` or test binaries behind.
- Soft-OPEN product PASS while edges=0 or while mapped roles have **0** Timescale samples on Railway.
- FQ claim. BACnet writes without human approval.
- **Screenshot Soft-OPEN**, headed browser Soft-OPEN, Playwright/Selenium Soft-OPEN galleries, or PNG ART as Soft-OPEN proof (API JSON + HTTP status only).
- Private campus names in committed scripts. Using `:nightly` as “newest”.
- Leaving Soft-OPEN feature branches / PRs open after the ship when they are already on tip.
- ZAP as a 3.6.18 Soft-OPEN blocker.

## Agent kickoff

```text
Plan: .cursor/plans/post_wave_x_3619_softopen_ghcr_grok_enhance_20261017.plan.md
Work ONLY under Linux /tmp (openfdd-softopen worktrees). No backups. rm -rf target/ after any cargo.
Finish #1286 green → merge ALL Soft-OPEN open PRs → delete stale branches → bump 3.6.18 →
wait GHCR refresh (newest-by-created) → refresh tip → kick Grok.
Grok: re-pin Railway + ACME, assert_hub_env, validate MISSING Timescale data (mapped≠0 samples),
lessons 01/03/05, softopen suite, JWT API data+errors (NO screenshots/browser Soft-OPEN), per-issue ART.
Soft-OPEN ≠ FQ. No backups. ZAP later.
```

## Grok Soft-OPEN — only after **3.6.18** GHCR refresh (enhanced)

```text
0) From /tmp tip checkout only:
   ./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web openfdd-mqtt
   Expect VERSION 3.6.18 + matching sha-*. OCI created, not tag sort.
1) Grok UPDATES Railway hub (central → mqtt → web) AND ACME (fieldbus → hub MQTTS; Timescale only).
   NO backups. No BACnet writes. No 3.5.x. No Parquet co-canonical. No compose down -v.
2) ./scripts/ops/assert_hub_env_after_repin.sh sha-<tip>  → PASS
   Healthy containers; live MQTT proxy ≠ stale Soft-OPEN port; edges≥1; ingest_ok climbs ≥2 publishes.
3) DATABASE missing-data Soft-OPEN (Railway Timescale):
   For BUILDING_100 / SYNTH_* / Soft-OPEN unique site — every mapped role → point-resolve / historian
   sample count > 0. Mapped-but-0 = FAIL. List gaps in ART (equip, role, building_id). Re-seed only if owner OK.
4) Unique Soft-OPEN building SOFTOPEN_<date>_<shortsha> OR import committed SYNTH_03 fixture.
5) From /tmp tip checkout against Railway host:
   A) python scripts/lessons/lesson_01_sites_and_equipment.py --host <hub> --building-id <id>
   B) python scripts/lessons/lesson_03_fc1_dataframe.py ...  → PASS with FC1 ≠ SKIPPED_MISSING_ROLES
   C) python scripts/lessons/lesson_05_rdf_semantic_meta_put.py ... → PASS (mutate+restore)
   D) python scripts/softopen/run_softopen_railway.py --host <hub> --building-id <id>
      - stress 01/03/08/09/10 (pandas==SQL fail-closed)
      - DB missing-data gate (above)
      - API Soft-OPEN: SPARQL/RDF → applicable AHU rules → FDD/RCx JSON point_count>0;
        Overview/AFDD endpoints 2xx + data or recorded error — NO screenshots / NO browser Soft-OPEN
6) ISSUE_TRIAGE: every open issue → CLOSE/KEEP/OPEN-NEW with tip evidence.
7) ACTIONS_TRIAGE_<sha>.md. Green skip ≠ pass.
8) ART: ~/Documents/openfdd-softopen-art/3.6.18/ — append new files, never overwrite prior.
9) Confirm no leftover Soft-OPEN remote branches claiming unmerged tip work (report any leftovers).
ZAP/security Soft-OPEN OUT OF SCOPE tonight unless owner asks.
```

## Morning STATUS template

- Tip pin: `3.6.18+<sha>` / newest-by-created digest (GHCR refresh complete)
- Railway + ACME re-pin by Grok: PASS|FAIL
- Hub assert / edges / ingest: PASS|FAIL
- **DB missing-data (Railway):** PASS|FAIL — list mapped-but-0 if any
- Lessons 01/03/05: PASS|FAIL (FC1 status for 03)
- Softopen suite + API endpoint Soft-OPEN (data/errors): PASS|FAIL
- Soft-OPEN branches: none stale | leftovers listed
- `/tmp` + Rust `target/` cleaned: yes|no
- Issue triage: CLOSE/KEEP/OPEN-NEW recommended
- Residuals open: #1282 / #1284 / Haystack / overlay series
- Soft-OPEN ≠ FQ · No backups
