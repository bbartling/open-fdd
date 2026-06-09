---
title: Grade-A FDD gap audit
parent: Developer Guide
nav_exclude: true
---

# Grade-A FDD gap audit (Open-FDD 3.0.16 → 3.0.18)

Audit date: 2026-06-09. Baseline: merged **3.0.16** (portfolio rollup, expression cookbook, sensor catalog).

## Standards alignment target

| Source | Role in Open-FDD |
|--------|------------------|
| ORNL/LBNL unified HVAC fault taxonomy | Canonical ontology backbone (`canonical_id`, `fault_mode`) |
| ASHRAE Guideline 36 | Expected sequences, trim-and-respond, plant requests, supervisory FDD |
| ASHRAE Standard 207 | Economizer FDD test-method language |
| Brick Schema | Primary semantic anchor (`required_point_roles`, equipment relationships) |
| Project Haystack | Optional tag crosswalk |

There is **no** universal industry fault-code standard. Open-FDD will use **short stable codes** (`AHU-ECON-001`) plus **semantic `canonical_id`** (`ahu.economizer.not_using_free_cooling`), with **legacy letter aliases** (`AHU-E`).

---

## Current fault families (v2 catalog)

Implemented in `workspace/api/openfdd_bridge/fault_catalog.py` (letter codes only):

| Family | Codes | Grade-A gap |
|--------|-------|-------------|
| AHU | A–F (6) | Need 20+ AHU modes (SAT, static, economizer, humidity, freeze, filter proxy) |
| VAV | A–E (5) | Need flow/damper/reheat/G36 request rules |
| HEATPUMP | A–E (5) | OK starter; align to RTU/HP templates |
| GEO | A–D (4) | OK for geo sites |
| CHILLER | A–F (6) | Plant-level CHW/CTW/PMP not split |
| DATACENTER | A–E (5) | Partial overlap with CRS healthcare |
| BUILDING | A–D (4) | DATA/CTRL/BACNET not separate families |

**Missing families entirely:** DOAS, MAU, FCU, FPU, CHW (plant), CTW, BLR, HWS, PMP, HX, ERV, CRS (healthcare), DATA, CTRL, BACNET.

---

## Rule cookbook & Arrow runtime

| Asset | Status |
|-------|--------|
| `docs/rule-cookbook/expression-cookbook.md` | Legacy pandas/YAML → Arrow translation (3.0.16) |
| `open_fdd/arrow_runtime/cookbook.py` | flatline, oob, mixing, rate_of_change, schedule masks |
| `open_fdd/arrow_runtime/sensor_catalog.py` | Bounds/flatline defaults per sensor kind |
| `open_fdd/arrow_runtime/rules.py` | Backend detection only — **no rule primitives** |
| Rule templates by system | **Missing** (`open_fdd/faults/templates/`) |
| Evidence builder | **Missing** (`evidence.py`) |
| Synthetic PyArrow tests per rule | Partial (bench rules only) |

### Arrow-native cookbook patterns (v2)

`flatline_1h`, `spread_1h`, `oob_rolling`, `rate_of_change`, `mixing_envelope`, `duct_spread_1h`, `custom_arrow`, `schedule_compare`, `stale_points`.

**Missing primitives:** persistence, deadband, cmd/fb mismatch, valve leak, damper stuck, reset stuck, low ΔT, approach, chatter, short-cycle, load/equipment mismatch, pressure relationship, G36 request rollup.

---

## Rule metadata gap

Current catalog entry fields: `code`, `category`, `title`, `severity`, `description`, `likely_causes`, `suggested_checks`, `cookbook_patterns`.

**Missing for Grade-A:**

- `canonical_id`, `subsystem`, `component`, `fault_mode`, `symptom`
- `required_point_roles` / `optional_point_roles`
- `rule_template_id`, `rule_doc_path`
- `related_faults`, `suppresses_faults`, `suppressed_by_faults`
- `standards_crosswalk` (ORNL, G36, 207, Brick, Haystack)
- `tuning_params` (persistence, deadband, seasonal/occupancy applicability)
- `evidence_fields` contract
- `operator_guidance` (technician / engineer / commissioning roles)
- `confidence` model

---

## Portfolio / central layer

| Component | Status |
|-----------|--------|
| `GET /api/building/portfolio-rollup` | Edge snapshot (faults, run hours, P8 overrides) |
| `portfolio/collector/` | HTTP poll + CSV append |
| `portfolio/dash/` | Per-site charts, light/dark, stock-style Δ |
| `portfolio/agent/*.example` | Skills/memory for central agent |
| Interval summary schema | **Started** (`portfolio/store/interval_schema.py`) |
| Tuning proposal schema | **Not implemented** |
| AI agent auto-tuning apply | **Not implemented** (edge has `apply-tuning` dry-run only) |
| Cross-site false-positive analytics | **Not implemented** |
| DuckDB/Parquet central store | **Not implemented** (CSV only) |

---

## Pandas on edge — violations & isolation

**Clean (no pandas):** `open_fdd/arrow_runtime/*`, `open_fdd/playground/arrow_templates.py`, Rule Lab `apply_faults_arrow` rules in `rules_py/`.

**Pandas present (edge bridge / ingest — migration target):**

| Module | Role | Grade-A action |
|--------|------|----------------|
| `feather_store.py` | Historian read/write | Keep pandas for CSV ingest path short-term; Arrow path for FDD batch |
| `fdd_runner.py` | Batch evaluation | Pandas only in legacy_row path; arrow path preferred |
| `bacnet_poll_ingest.py` | Poll CSV | Ingest layer — isolate, not Rule Lab |
| `poll_throughput.py` | Analytics | Read-only analytics |
| `playground.py` / `playground_exec.py` | Legacy evaluate | Deprecate `evaluate()` on edge |
| `data_loader.py`, `fdd_row_prep.py` | Legacy pipeline | Mark legacy |
| `open_fdd/playground/rows.py`, `sandbox.py` | Legacy row rules | Portfolio/dev only |

**Allowed pandas:** `portfolio/dash/`, `portfolio/store/` (future pandas/DuckDB), tests, `scripts/ahu_runtime_report.py`, legacy `open_fdd/engine/` (PyPI pandas era).

**Policy (3.0.18+):** New edge FDD code **must not** add pandas imports. CI guard: `tests/test_no_pandas_edge_fdd.py`.

---

## Healthcare / critical spaces

No dedicated CRS catalog. DATACENTER family partially covers CRAH. Need:

- Pressure relationship loss, isolation/OR pressurization
- ACH shortfall, humidity/temperature excursion
- `healthcare_risk` category separate from `energy`

---

## Central plant

CHILLER family covers chiller unit only. Missing documented rules for:

- Low ΔT syndrome, CHWST/DP reset stuck, bypass/decoupler
- Tower approach, condenser reset, staging chatter
- Boiler/HWS reset stuck, short cycling, simultaneous heat/cool rollup

---

## Dashboard analytics gap

Current Dash: run hours, fault counts, P8 overrides per site.

Missing operator cards: portfolio health score, false-positive rate, tuning queue, data-quality score, plant health rollups, healthcare risk panel, AI recommendations queue.

---

## Recommended implementation order

1. **3.0.18** — Schema + starter YAML catalog + primitives + audit (this patch)
2. **3.0.19** — Bridge sync: `fault_catalog.py` reads `open_fdd.faults.catalog` + aliases
3. **3.0.20** — Rule templates (DATA, AHU, VAV, CHW) + synthetic tests
4. **3.0.21** — Portfolio interval ingest + tuning proposal schema
5. **3.0.22** — Dash operator cards + AI agent tuning loop docs

---

## References

- [Rule cookbook](https://bbartling.github.io/open-fdd/rule-cookbook/)
- [Fault codes](https://bbartling.github.io/open-fdd/fault-codes/)
- [Portfolio (GitHub)](https://github.com/bbartling/open-fdd/tree/master/portfolio)
