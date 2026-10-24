---
name: openfdd-rcx-fdd-plot-poll
description: >-
  From blank RCx or FDD plots, deduce missing historian roles on the CSV
  package or Normal Framework portal inventory. Triggers on empty RCx preset,
  empty FDD series, missing roles, unmapped columns.
---

# RCx / FDD plot → poll checklist

Blank plots are almost never a Plotly bug. They mean **missing SQL roles**
on the CSV package or the Normal Framework portal inventory.
`architecture_epoch: portal-timescale-v1`. This skill turns an empty chart
into a role and binding checklist. It does not add a fieldbus poll.

## When to use

- RCx preset returns `points=0` / empty envelope / “unavailable (unmapped …)”
- FDD Plots series soft-empty after a successful rule run
- Diffing Data Model gaps vs `REQUIRED_RCX_PRESET_IDS` + cookbook roles

## Sources of truth (read in this order)

1. [`frontend/web/src/nav/rcxCatalog.ts`](../../../frontend/web/src/nav/rcxCatalog.ts) — `REQUIRED_RCX_PRESET_IDS`
2. [`services/central/src/analytics/rcx_presets.rs`](../../../services/central/src/analytics/rcx_presets.rs) — preset → `role_col` / overlays
3. [`docs/agent/PACKAGE_AUTHORING.md`](../../../docs/agent/PACKAGE_AUTHORING.md) — Haystack → SQL roles by family
4. [`docs/migration/vibe19/ROLE_MAPPING_PARITY.md`](../../../docs/migration/vibe19/ROLE_MAPPING_PARITY.md) — alias table
5. `sql/fdd/registry.yaml` — FDD `required_roles` ∪ `optional_roles` per rule
6. Live site Data Model / inventory (`GET` mapping) — mapped vs unmapped columns

Companion: [`openfdd-package-mapping`](../openfdd-package-mapping/SKILL.md) for zip maps.
[`openfdd-bacnet-ot-debug`](../openfdd-bacnet-ot-debug/SKILL.md) is historical/non-executable and is not the fix for a blank plot.

## Workflow

### 1. Name the blank surface

| Surface | What empty means |
|---------|------------------|
| RCx preset | Missing `role_col` (and overlay) on matching `eq_kinds` |
| FDD series | Missing required∪optional roles on that equipment |
| Health matrix `?/3` | Missing proof roles **or** no FDD results yet |
| Inspect | Column present in history but not selected / unmapped |

Do **not** patch central SQL to paper over a missing portal or package point.

### 2. Expand roles → Haystack → binding

For each blank preset / rule:

1. List cookbook SQL roles needed (process vars first; setpoints are additive).
2. Map each role to Haystack names via ROLE_MAPPING_PARITY / PACKAGE_AUTHORING.
3. Emit a row: `role | equip family | haystack | present in package or portal inventory? | present in Data Model?`.

Never invent ZN-T / CFM / setpoints. A missing point is a gap in the package or portal model, not a fieldbus object to poll.

### 3. Diff vs live inventory

- Inventory / Data Model: blank role = unmapped; the column may still exist.
- Prefer status/cmd before amps; never use valve % as compressor proof.
- Fieldbus poll catalogs are historical/non-executable ([`docs/archive/ai-agent/historical-3.5-ot-ops.md`](../../../docs/archive/ai-agent/historical-3.5-ot-ops.md)).

### 4. Roles that light a chart

**Include when the portal or package actually has the point:**

| Family | Roles that light RCx / FDD |
|--------|----------------------------|
| VAV | `zone_t`, `zone_flow` (actual CFM), `damper_pct`, reheat valve, leave/DAT, airflow SP (SP as setpoint role only) |
| RTU / AHU | fan VFD %, duct static + SP, DAT/SAT, cool/compressor status+cmd, OA damper, BAS `oa_t` |
| Boiler / HW | HW supply/return, pump ΔP + SP, pump speed(s) — whitelist controller only |
| Weather | site BAS `oa_t` + `{building}/weather/` `web_oa_t` |

**Do not invent points** to fill a chart. Do not map a gateway dump as the boiler. Do not stamp a controller as a VAV because the folder name looks like one.

### 5. Checklist template (copy into PR / BUG_REPORT)

```text
Site: <building_id>
Blank: RCx <preset_id> | FDD <rule_id>
Roles needed: …
Haystack: …
Package or portal inventory: present / missing
Data Model: mapped / unmapped / absent column
Action: map the role | fix the portal binding | wait for history
```

## Quick RCx role cheat sheet (`REQUIRED_RCX_PRESET_IDS`)

| Preset | Primary role(s) |
|--------|-----------------|
| `zone_comfort_rank` / `zone_temps` / `vav_health_matrix` | `zone_t` (+ damper for rogue box) |
| `vav_flows` | `zone_flow` |
| `ahu_dats` / `ahu_sat_reset_scatter` | `sat` (+ web OAT for scatter) |
| `ahu_mats` / `ahu_rats` / `ahu_dampers` | `mat` / `rat` / `oa_damper_pct` |
| `fan_speeds` | fan speed / cmd |
| `duct_static_*` | duct static |
| `hw_reset_scatter` | HW temp + web OAT |
| `chw_*` / `cw_*` | CHW/CW temps + web OAT |
| `meter_*` | utility / meter roles |
| `bas_vs_web_oat` (additive) | `oa_t` + `web_oa_t` |

## Anti-patterns

- Inventing points that are not in the package or portal inventory
- Patching RCx SQL filters instead of stamping `equipType: vav` / mapping roles
- Starting fieldbus or MQTT to fill a blank plot
- Treating empty Plotly as a frontend-only bug when envelope `rows`/`points` are empty
- Authoring a second copy under `.cursor/skills/` or `~/.cursor/skills/` (sync with `scripts/openfdd_install_agent_skills.sh`)

## Done when

- The checklist names every blank preset or rule role as mapped or explicitly missing
- Data Model shows the mapped columns; RCx/FDD envelopes are non-empty after the next portal or CSV ingest

## Skill home

`openfdd_agent_spec/skills/` is the only authoring tree. Do not create a parallel copy under `.cursor/skills/`, `.claude/skills/`, `.agents/skills/`, or a home directory. Sync with [`scripts/openfdd_install_agent_skills.sh`](../../../scripts/openfdd_install_agent_skills.sh) (`--sync`, optional `--user`). Orientation: [`openfdd_agent_spec/AGENTS.md`](../../AGENTS.md) and the repo [`AGENTS.md`](../../../AGENTS.md).

## Related skills

- [`openfdd-package-mapping`](../openfdd-package-mapping/SKILL.md) — Haystack roles and `equipType`
- [`data-modeling`](../data-modeling/SKILL.md) — package layout
- [`openfdd-typst-rcx-report`](../openfdd-typst-rcx-report/SKILL.md) — single-system PDF from those roles
- [`openfdd-sql-fdd`](../openfdd-sql-fdd/SKILL.md) — Timescale rule SQL
- [`openfdd-react-spa`](../openfdd-react-spa/SKILL.md) — product chart contract
- [`openfdd-pypi-oracle`](../openfdd-pypi-oracle/SKILL.md) — PyPI helpers the PDF calls
