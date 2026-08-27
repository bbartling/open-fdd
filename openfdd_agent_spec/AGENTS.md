# Open-FDD agent workspace — orientation

Plain Markdown on disk is the source of truth for **Cursor**, **Codex CLI**, and
similar agents. Product code lives in `services/`, `sql_rules/`, `frontend/`,
`mcp/`, `edge/`, `os/`. PyPI libraries live in `open_fdd/`. Orchestration lives in
**`openfdd_agent_spec/`**.

**Primary agent prompt (paste into new sessions):** [`../AGENTS.md`](../AGENTS.md)

**Software-engineering mission:** [`MILESTONE_A.md`](MILESTONE_A.md)

**Ops / edge soak prompts:** [`../docs/agent/`](../docs/agent/) — GHCR bench, nightly
retest. Do not confuse those with this engineering OS.

---

## Product vs libraries

| Layer | Owns |
| --- | --- |
| `services/` + `sql_rules/` + `frontend/web` | **Product:** central DataFusion SQL FDD + analytics, React SPA (`openfdd-web`), fieldbus, mqtt |
| `open_fdd/` | **PyPI libraries** for third-party tooling: ECM + pandas oracle (`rules` / `analytics` / `reporting`) — not the product runtime |
| `mcp/` | Optional read-first MCP → central |
| `edge/`, `os/` | Future concepts — **never delete** |
| `docs/rules/cookbook/` | Dual expression cookbooks (SQL + pandas) + parity matrix |
| `tools/open-fdd-vibe21-production/` | Active recovery + Vibe 21 twin program |
| `docs/migration/react-rust/capabilities.yaml` | Machine-readable capability ledger |
| `openfdd_agent_spec/` | Agent law, Milestone A, skills, session log |
| Playground vibe19/20 | External demos; consumers of PyPI |

**Package / timestamp contract (product + PyPI):** `timestamp_utc` is RFC3339 UTC (`Z` or `+00:00`). Rust ingest skips bad rows (no epoch 0 / now). Pandas oracle uses `open_fdd.timestamps.to_utc_datetime`. String `"equip"` on a Haystack sidecar is metadata. **Package authoring (any BAS job):** [`../docs/agent/PACKAGE_AUTHORING.md`](../docs/agent/PACKAGE_AUTHORING.md). Modeling (compact map vs SCAFFOLD, HP buildings, readiness): [`../docs/modeling/`](../docs/modeling/). Aliases: [`../docs/migration/vibe19/ROLE_MAPPING_PARITY.md`](../docs/migration/vibe19/ROLE_MAPPING_PARITY.md).

**Naming (code truth):**

| Concept | Module / extra |
| --- | --- |
| Pandas oracle (PyPI) | `open_fdd.rules` (+ `open_fdd.analytics`) |
| Pip extras | `oracle`, `analytics`, `reporting` (`vibe19` deprecated alias through 4.3) |
| ECM math | `open_fdd.ecm_engineering` |
| Shared contracts | `open_fdd.contracts` — Phase 2 target (not shipped) |

---

## AI agent quick rules (read first)

1. Product FDD + Overview analytics = **DataFusion SQL** on GHCR. Never silent pandas fallback in central.
2. Pandas oracle stays forever on **PyPI** + cookbooks + vibe19 — never delete the pandas cookbook because production uses SQL.
3. Never delete the SQL cookbook because pandas remains the oracle.
4. **Product UI:** React SPA (`frontend/web` → `openfdd-web`, `compose.react.yml`) only. Overview = central `/api/analytics/*` (DataFusion) **tables + health matrices**. Plotly motor/mech/econ/BAS figures live on RCx (additive presets). Inspect radio hosts the CSV overlay. Browser → central Rust `/api` only — **no Python in the product request path**.
5. **Internet-facing auth/UI hygiene:** Never put bench/dev secrets, credential file paths, default passwords, or JWT dumps on login or other product surfaces. Generic login errors only.
6. Test containers on **`OPENFDD_IMAGE_TAG=nightly`**, but **pin/run `sha-*`** per [`CONTAINER_AGENT.md`](CONTAINER_AGENT.md).
6b. **Rust lint hygiene:** eliminate `#[allow]` / `#![allow]` — see [`docs/RUST_LINT_HYGIENE.md`](docs/RUST_LINT_HYGIENE.md). Prefer fix / `_` / `?` / smallest-scope `#[expect]` + comment; never crate-wide `#![allow]`.
7. Playground images: `ghcr.io/bbartling/vibe19:develop`, `vibe20:develop` (external).
8. `edge/` and `os/` are future concepts — never delete.
9. Bounded PRs only — see [`PR_PROTOCOL.md`](PR_PROTOCOL.md).
10. Prefer exact wheel install tests over editable-only validation for packaging PRs.
11. Never trust a moving GHCR tag alone — resolve/pull immutable `sha-*`, recreate containers, then record the digest.
12. Append [`SESSION_LOG.md`](SESSION_LOG.md) after non-trivial work.
13. Update [`BUILD_CHECKPOINTS.md`](BUILD_CHECKPOINTS.md) when Milestone A or product capability status changes.
14. CodeRabbit: fix actionable defects; reject suggestions that violate architecture.
15. vibe21 = separate plan — not Milestone A.
16. When blocked (secrets, permissions), finish non-blocked work and record the exact error.
17. Bound each PR to its declared scope.
18. **Active program:** [`tools/open-fdd-vibe21-production/`](../tools/open-fdd-vibe21-production/README.md) Master Loop. Keep [`capabilities.yaml`](../docs/migration/react-rust/capabilities.yaml) honest.
19. For `frontend/web` work: follow [`openfdd-react-spa`](skills/openfdd-react-spa/SKILL.md).
20. Central product image is **debian + Rust binaries only** — no Python. WattLab AFDD zip export is optional offline tooling (`OPENFDD_WATTLAB_PYTHON_EXPORT=1`).
21. **Site lock:** Overview + sidebar Active site are the only editors of `?site=`. `SectionTabs` (and sidebar App pages) must `navigate` with `hrefWithSession` so `site` + `eq` survive. FDD / RCx / Results / WattLab show a locked `zip:BUILDING_*` caption — no Building `<Select>`.
22. **FDD Plots = vibe19 `rule_result_chart`:** auto-load series; last y-axis title is `fault`; `confirmed_fault` is the last trace on the bottom domain (`domain[0] < 0.4`). A successful rule run with an empty overlay is a bug (fail the test), not a soft banner.
23. **RCx catalog freeze:** every `REQUIRED_RCX_PRESET_IDS` id must stay listed. Family picker order is `RCX_FAMILY_ORDER` (Zones first) plus empty Heat pump / Weather placeholders. Auto-run the selected preset when site+preset are set.
24. **Actions housekeeping:** default `GET /api/actions?limit=10`; `DELETE /api/actions/:id` and `DELETE /api/actions`; JSONL prune cap 50.
25. **Section radios:** left, horizontal, **after** hero + Equipment on Overview (never inside `.oracle-hero`, never centered in the logo column). Other pages: same left radio row at the top of the page body.
26. **Overview is tables + health matrices** — no Plotly on Overview. Motor / mech / econ / BAS figures are additive RCx presets (`ahu_motor_weekly`, `economizer_*`, `boiler_motor_weekly`, `chiller_motor_weekly`, `mech_cooling_oat_bins`, `bas_vs_web_oat`). CSV overlay is the **Inspect** radio (`/inspect`). Do not drop `REQUIRED_RCX_PRESET_IDS`.
27. **FDD Plots series overlay** honors Lab/`session_config` `confirm_min` (and typed rule params); source may be `sql_detail_session`. After Update-this-rule, listen for `RULES_UPDATED` and refetch results + series.
28. **SCHED-1 portable occupancy:** numeric/boolean falsey (`0`, `0.0`, `false`) **and** string `unoccupied` (plus related tokens) — keep SQL (`sched1_unoccupied_runtime.sql`) and pandas `sched1` aligned.
29. **Low-RAM / bensbench:** never local stack `docker build`; prune old images before pull; wait for GHCR publish then pull `sha-*` / `nightly`. Synthetic-59 soaks: `scripts/synthetic_59_*.py` (OpenFDD-only). GHCR poll: `scripts/ghcr_watch_central.py`. E+ dump/clustering: `scripts/eplus_dump_clustering_export.py`, `scripts/agent_eplus_dump.sh`. Vibe19 B100 dump-parity **retired** → `scripts/retired/vibe19-parity/`. Never edit goldens to hide misses.
30. **Plot PNG downloads:** `PlotlyHost` must pass `toImageButtonOptions.filename` (Overview/Reports). Default Plotly `newplot.png` is a regression.
31. **Full-width UI:** `.app-content` / `.overview-populated` stretch (`max-width: none`) like Streamlit — do not reintroduce a rem content cap on Overview plots.
32. **Rule Lab menu:** `RuleTuningPanel` sorts visible rules A–Z by `rule_id` (registry YAML order is engine priority only).
33. **FDD Plots series roles:** `series_response` SELECT = `required_roles ∪ optional_roles` (SV-*/PID-HUNT keep required empty). Soft-empty when none present on equipment.
34. **Mech cooling OAT bins:** status/cmd proof **before** amps (never OR amps when status exists); prefer web/`dry_bulb_f`/weather OAT over site-averaged AHU BAS `oa_t`. Version `mechanical-cooling-oat-bins-v2`.
35. **Synthetic analytics soak:** `scripts/synthetic_59_overview_analytics_soak.py` asserts runtime + mech bin envelopes (separate from FDD pair scores).
36. **Metric CSVs:** store as-uploaded; convert temperature roles C→F at run-rules/historian query. Do not duplicate 59 SQL files. Sliders display user units.
37. **Package append:** `POST /api/csv/import/package/append` is the IoT hourly path (JWT + confirm). **AFDD routine sim:** `scripts/csv_flood_afdd_routine_sim.py` + `scripts/fixtures/b50_afdd_routine.json` on `raw_BUILDING_50_openfdd.zip` (append → session-config patch → `/api/fdd/run`). Doc: [`docs/agent/CSV_FLOOD_AFDD_ROUTINE.md`](../docs/agent/CSV_FLOOD_AFDD_ROUTINE.md). Vendor pullers stay out-of-repo.
38. **E+ dump / clustering:** prefer `reports/eplus-dump/` (`EPLUS_DUMP_ROOT`); `scripts/eplus_dump_clustering_export.py` emits sklearn-ready features. Online: `scripts/agent_eplus_dump.sh`. Rust API routes still `/wattlab/dumps` until rename. Doc: [`docs/agent/EPLUS_DUMP_CLUSTERING.md`](../docs/agent/EPLUS_DUMP_CLUSTERING.md).

---

## Authority order

1. Root [`AGENTS.md`](../AGENTS.md)
2. Machine manifests: [`ownership.yaml`](ownership.yaml), [`capabilities.yaml`](../docs/migration/react-rust/capabilities.yaml)
3. Current phase docs under [`tools/open-fdd-vibe21-production/`](../tools/open-fdd-vibe21-production/)
4. Generated OpenAPI / MCP / rule catalogs
5. Workflow guides and examples

Nested instructions may specialize but never contradict a higher authority.

## Bootstrap reading order

1. [`../AGENTS.md`](../AGENTS.md)
2. This file
3. [`../docs/agent/PACKAGE_AUTHORING.md`](../docs/agent/PACKAGE_AUTHORING.md)
4. [`../docs/modeling/`](../docs/modeling/) when packaging / HP / readiness context matters
5. [`ARCHITECTURE.md`](ARCHITECTURE.md) + [`ownership.yaml`](ownership.yaml)
6. [`BUILD_CHECKPOINTS.md`](BUILD_CHECKPOINTS.md)
7. [`tools/open-fdd-vibe21-production/prompts/MASTER_PRODUCTION_LOOP.md`](../tools/open-fdd-vibe21-production/prompts/MASTER_PRODUCTION_LOOP.md)
8. [`MILESTONE_A.md`](MILESTONE_A.md) if executing Milestone A
9. [`PR_PROTOCOL.md`](PR_PROTOCOL.md) before opening a PR
10. Matching skill
11. Cookbooks under `docs/rules/cookbook/`

---

## Skills

| Skill | Use when |
| --- | --- |
| [`openfdd-architecture`](skills/openfdd-architecture/SKILL.md) | Ownership / engine boundaries |
| [`openfdd-react-spa`](skills/openfdd-react-spa/SKILL.md) | Product SPA (`frontend/web`) |
| [`openfdd-package-mapping`](skills/openfdd-package-mapping/SKILL.md) | Zip / `equipType` / Haystack→SQL / empty charts |
| [`openfdd-sql-fdd`](skills/openfdd-sql-fdd/SKILL.md) | DataFusion SQL rules |
| [`openfdd-pypi-oracle`](skills/openfdd-pypi-oracle/SKILL.md) | PyPI pandas oracle packaging |
| [`openfdd-cookbook-parity`](skills/openfdd-cookbook-parity/SKILL.md) | Dual cookbook honesty |
| [`openfdd-stack-ghcr`](skills/openfdd-stack-ghcr/SKILL.md) | GHCR pull / recreate |
| [`openfdd-ecm-engineering`](skills/openfdd-ecm-engineering/SKILL.md) | ECM math library |
| [`openfdd-milestone-a-pr`](skills/openfdd-milestone-a-pr/SKILL.md) | Milestone A PR loop |

### Equipment typing contract

Package `equipType` / `equipment_type` stamps are persisted and preferred over id heuristics. Opaque ids are valid (`AC_1` + `equipType: ahu`). Never solve a site-specific naming problem by hard-coding a vendor, campus, or building into product code.
