---
title: Python tools (PyPI)
nav_order: 15
---

# Python tools (`pip install open-fdd`)

The PyPI package **`open-fdd`** is the toolbox for AI agents and engineers who work *next to* the Open-FDD
[Normal Framework app](install.html): pandas reference FDD rules (SI only, cross-checked against the SQL pack),
ECM workbooks, reports and anomaly screening, plus a client that reads a Normal Framework (NF) box directly.

**Versions are separate.** The PyPI package is **4.x** (`open-fdd 4.5.0`); the NF app is **5.x**. Run
`open-fdd-version --pretty` to see both (`package_version`, `app_version`; the app version is only known inside a
repository checkout). The Rust "central" API of the 4.x stack is retired, so nothing in the package reads from it any
more: history now comes from NF itself (LAN or Normal Online portal), the app's CSV export, or a device folder.

## Install

```bash
pip install open-fdd                  # ECM workbooks + the NF client (standard library only)
pip install "open-fdd[nf]"            # + pandas/numpy/pyyaml: SI frames and the pandas rules
pip install "open-fdd[reporting]"     # + python-docx, matplotlib, plotly: findings reports
pip install "open-fdd[anomaly]"       # + statsmodels, scikit-learn: anomaly screening
pip install "open-fdd[rdf]"           # + rdflib: read the app's RDF/Turtle export
```

Extras: `oracle` (pandas, numpy, pyyaml), `analytics` and `nf` (both = `oracle`), `reporting`, `anomaly`, `rdf`,
`ecm-web` (FastAPI for the ECM web demo), `test`, `dev`. Python 3.10 or newer.

## Connect to NF

| Variable | Meaning |
|---|---|
| `NF_URL` | Base URL of the box (any path). Also read: `NF_LAN_URL` (LAN), `NFURL` (Normal Online portal) |
| `NF_CLIENT_ID`, `NF_CLIENT_SECRET` | An NF API key (console: Settings, API Keys). Token flow, refreshed on expiry |
| `NF_CONSOLE_USER`, `NF_CONSOLE_PASSWORD` | HTTP basic auth, for a LAN front door that asks for a login |
| `NF_CA_FILE` | A self-signed LAN certificate to trust (added to the system CAs) |
| `NF_ENV_FILE` | A `KEY=VALUE` file read first (the real environment wins). Never commit it |

- **LAN** (`--via lan`): `NF_LAN_URL`, falling back to `NF_URL`. Fast, and the only path that can read
  `/api/v1/bacnet/*` with an API key.
- **Portal** (`--via portal`): `NFURL`, e.g. `https://<installation-uuid>.normal-online.net`. Use an API key; the
  portal answers 401 without a bearer token. Point history, queries and platform info work through it.
- With neither `--via` nor a flag the order is `NF_URL`, `NFURL`, `NF_LAN_URL`.
- Retries cover idempotent calls only (every call here is a read, plus the token call) on HTTP 403, 429 and 5xx with
  exponential backoff. NF has a known intermittent empty-body 403 on `/api/v1/auth/token` that succeeds on retry.
- The tools never write to NF.

```bash
export NF_URL=https://192.168.1.50           # or NFURL for the portal
export NF_CLIENT_ID=...  NF_CLIENT_SECRET=...
export NF_CA_FILE=./lan-ca.crt               # only for a self-signed LAN certificate
open-fdd-nf info
```

## SI units and role binding

Everything the rules see is SI, exactly like the app: temperature degC, pressure Pa, flow L/s, power kW, energy kWh,
percent 0 to 100 only for humidity. `open_fdd.nf.units` is a port of `nf-app/static/units.js` (same table, same
canonical units); see [Units](units.html).

`open_fdd.nf.model` follows the app's binding (`fdd.js`) and its `siPlan` (`hooks/fdd.js`):

- A point fills a role when its NF **class** is listed for the role (ranked first) or it carries **every marker** of
  the role. Equipment kinds come from the equip's markers.
- Binding is **site scoped**: a point belongs to an equip only if both `equipRef` and `siteRef` match. Weather points
  fill only `web_*` roles.
- Command and position roles are **fractions 0 to 1**: a `%` unit is divided by 100; a ratio/fraction unit or a Bool
  point is kept; a **unitless** number is skipped (0-100 and 0-1 cannot be told apart). Status roles must land in
  0 to 1. Temperature, pressure and flow roles with a missing or mismatched unit are skipped, never guessed.
- Every skip is recorded with its reason in `df.attrs["skipped"]`.

The role catalog the package uses is shipped in `open_fdd/data/` (copies of `nf-app/static/fdd-catalog.json`,
`sql/fdd/role_scales.json`, `sql/fdd/role_map.json`), kept in sync by `python scripts/nf/sync_pypi_data.py`
(`--check` in CI).

## Command line tools

### `open-fdd-nf`: read a box, run the rules

Common options: `--url`, `--env FILE`, `--via lan|portal`, `--ca-file`, `--timeout`, `--site`, `--equip`; time range
`--days N` (default 7) or `--start/--end` (UTC ISO), `--window` seconds (default 300). Errors print `error: ...` and
exit 2.

```text
open-fdd-nf {info,model,pull,rules,report,analyze}
  info     platform info and the sites in the model
  model    equipment with the points bound to each FDD role
  pull     history of the bound roles as SI CSV (or parquet)
  rules    run the pandas reference rules and print a summary
  report   rules.csv + summary.md (and findings with --findings)
  analyze  read-only agent analytics tools, run on the box (see below)
```

| Command | Output | Example |
|---|---|---|
| `info` | JSON: URL, `platform/info`, sites | `open-fdd-nf info --via portal` |
| `model [--json]` | table (site, equip, type, roles, columns) or JSON with the point bound to each role | `open-fdd-nf model --site "North Campus"` |
| `pull --out F` | one wide file, columns `"<equip> <role> [<unit>]"`, UTF-8 BOM, SI. `.parquet` needs pyarrow | `open-fdd-nf pull --equip AHU-1 --days 7 --out ahu1.csv` |
| `rules [--rules A,B] [--all] [--json]` | status counts and the fault rows (all rows with `--all`) | `open-fdd-nf rules --days 7 --json` |
| `report --out DIR [--findings] [--docx]` | `rules.csv`, `summary.md`; with `--findings` the Engineering Findings JSON (+ DOCX) | `open-fdd-nf report --days 14 --out out --findings` |

#### `open-fdd-nf analyze`: the six read-only analytics tools

`open-fdd-nf analyze TOOL [--site S] [--equip E] [--rule R] [--days N] [--view V] [--dense] [--json] [--wait SEC]`
starts the NF app's on-request `analytics` hook (`POST /api/v1/apps/open-fdd/hooks/analytics`, `args.tool`), waits for the
run and prints its answer. The math exists once, in JavaScript (the same code as the dashboard, on the fine 5-minute grid);
Python only transports. The hook only reads: it cannot write points, schedules or BACnet values (its HTTP client refuses
everything but GET and the read-only `point/query` / `auth/token` POSTs). StartHook is sent exactly once, never retried.
Needs the 5.0.3 app (hook `analytics`); an older app answers `404`.

| TOOL (short name) | Args | Rows / result |
|---|---|---|
| `analyze_ahu_weekly_runtime` (`weekly-runtime`) | `--site --equip --days` (28) | per ISO week: `run_hours`, `schedule_hours`, `in_schedule_hours`, `after_hours`, `partial_week`, `mean_oat_on_c`, `schedule_source` / `schedule_label` |
| `analyze_mechanical_cooling` (`cooling`) | `--site --equip --days` (28) | `bins`: hours in the six SI outdoor-air bins (`<10`, `10-16`, `16-21`, `21-27`, `27-32`, `>=32` degC), `total_hours` |
| `analyze_economizer` (`economizer`) | `--site --equip --days` (7) | `n`, `n_identifiable`, `median_residual_k`, `mae_k` |
| `get_fdd_fault_timeline` (`fault-timeline`) | `--equip --rule` (+ `--site --days` (1) `--dense`) | `timeline` of `{ts, state}` with state `confirmed` / `ok` / `unknown`, from the hook's timeline point, never `fault_pct`; state changes only unless `--dense`; `approximate: true` only when no timeline point exists |
| `resolve_equipment_roles` (`roles`) | `--equip` (NF uuid, or an id with `--site`) | `roles`: role to bound points; `runnable_rules` |
| `explain_missing_rcx_view` (`explain-view`) | `--view` (+ `--site --equip`) | `available`, `missing_roles`, `reasons`, per-equip `status` (`ready`, `kind_mismatch`, `missing_roles`, `no_data`) |

Every row carries `siteRef`, `equipRef` and `equipUuid`: key on `equipUuid`, so two sites that both have an `AHU-1` never
share a row. `--equip` matches an NF uuid first, then a Haystack id or name. The list tools return every matching equip;
the single-equip tools (`fault-timeline`, `roles`) **fail** when the id matches several sites and list the candidates
(pass `--site` or the uuid): they never guess. Answers are capped at about 200 KB (`truncated: true`, newest timeline entries
kept). From Python: `from open_fdd.nf.analytics import analyze; analyze(client, "weekly-runtime", site="S", days=28)`.

`rules` statuses: `fault`, `ok`, `not-assessed` (missing roles, equipment never proven on, or zero covered samples: an
unknown is never healthy) and `error`. `coverage` is the share of the frame the rule was assessed over.

### `open-fdd-report`: Engineering Findings reports

Builds the evidence-reviewed findings report (priority pack, appendices, fault inventory) from a checklist JSON
and/or real history. Needs `open-fdd[reporting]`.

| Source flag | Meaning |
|---|---|
| `--checklist-json FILE` | a controls service checklist (candidate findings) |
| `--nf` | pull history from NF (`--url`, `--env`, `--via`, `--site`, `--equip`, `--days`, `--start/--end`), run the pandas rules, report |
| `--csv FILE` | the app's CSV export, fully offline (columns are matched to roles by point name) |

Other flags: `--out DIR` (required), `--building`, `--docx`, `--xlsx`, `--no-charts`, `--max-findings`,
`--allow-priority`, scope (`--systems`, `--equipment-prefix`, `--rule-ids`, `--boost-terminal`) and review
(`--pin-finding`, `--drop-finding`, `--note`, `--notes-file`). Output: findings JSON, fault inventory, quality gate
(exit 2 if the gate fails).

```bash
open-fdd-report --nf --equip AHU-1 --days 14 --out out/ahu1 --docx
open-fdd-report --csv open-fdd_site_20261101-0000_20261108-0000.csv --out out/offline
```

The old WattLab `--dump/--package` input is gone: it needed a host bridge that is not part of the package.

### `open-fdd-ecm`: ECM workbooks

Energy conservation measure workbooks (Excel) with provenance, G14 statistics and agent hooks. Standard library plus
openpyxl; no NF needed.

| Subcommand | What it does |
|---|---|
| `calculators` | list the calculators (economizer runtime cap, fan affinity, outside air loads, kW/ton, boiler efficiency, CHWS reset, condenser water, ...) |
| `demo [--out F]` | write the demo workbook |
| `stage2-workbook [--out F --project P --facility F]` | write a Stage 2 workbook skeleton |
| `agent <command>` | `import_energyplus_evidence`, `list_workbook_inputs`, `list_missing_inputs`, `propose_input_update` (dry run only) |

```bash
open-fdd-ecm calculators
open-fdd-ecm demo --out ecm_demo.xlsx
open-fdd-ecm agent list_missing_inputs ecm_demo.xlsx
```

### `open-fdd-anomaly`: screen a device folder

Statistical screening (z-score, MAD, STL, isolation forest) of an AHU device folder (`history_wide.csv` +
`column_map.json`). Needs `open-fdd[anomaly]`.

```bash
open-fdd-anomaly screen ./ahu1_folder --out out/scan --top-n 5
open-fdd-anomaly report ./ahu1_folder --out out/rcx --units si --compile   # Typst sources (+ PDF with typst on PATH)
```

`screen` writes a scoreboard, support plots and day zooms; `report` writes single-system (or `--scope building`)
RCx Typst sources.

### `open-fdd-version`

Prints the version axes as JSON (`--pretty` to indent): `package_version` (also `open_fdd_python_version`, 4.x),
`app_version` (NF app, 5.x, only in a checkout), `git_revision`, `rule_catalog_version`, `rule_catalog_hash`.

## Python API

### `open_fdd.nf`: NF client, model, frames, rules, export readers

```python
from datetime import datetime, timedelta, timezone
from open_fdd.nf import NFClient, load_model, equipment_frames, run_rules

client = NFClient.from_env(via="lan")             # or NFClient(url, auth=("portal", id, secret))
model = load_model(client)                         # sites, equips, devices, points
end = datetime.now(timezone.utc); start = end - timedelta(days=7)
frames = equipment_frames(client, model, start, end, site="North Campus")
table = run_rules(frames)                          # tidy DataFrame
print(table[table.status == "fault"])
```

| Name | Purpose |
|---|---|
| `NFClient(base_url, auth=None \| ("basic", u, p) \| ("portal", id, secret), timeout, ca_file)` | HTTP client; `from_env(via, env_file)`; `platform_info()`, `sites()`, `query_all(layer, structured_query)` (paged, rejects a repeated page token), `point_data(uuids, start, end, window_sec, method)` (batches of 40, chunks of 7 days) |
| `load_model(client)` | `Model(sites, equips, devices, points)` from the model and default layers |
| `bind_equipment(model, roles, site, equip)` | which points fill which roles, per equipment |
| `equipment_frames(client, model, start, end, window_sec=300, roles=None, site=None, equip=None)` | `{(site, equip): DataFrame}`: UTC index, one column per bound role (pandas Haystack name such as `discharge-air-temp`), SI values; `df.attrs` has `bindings`, `role_units`, `skipped`, `equipment_type` |
| `run_rules(frames, rules=None, params_by_rule=None)` | `(site, equip, rule, status, fault_hours, fault_pct, coverage, raw_status, missing_roles, notes)` |
| `read_csv_export(path)`, `csv_frames(path, column_roles=None)` | the app's Export CSV (BOM, CRLF, `"<equip> <point> [<unit>]"`) as a frame / as SI equipment frames |
| `read_turtle(path)` | the app's RDF/Turtle export as a `Model` (needs `rdflib`) |

`open_fdd.nf.report.write_report(frames, out_dir, findings=False)` writes the CSV and markdown summary and can feed the
reporting pipeline. `open_fdd.reporting.report_template` has history sources `device_folder`, `nf` (`NfSource`) and
`nf_csv` (`CsvExportSource`).

### `open_fdd.rules`: the 71 pandas rules

The reference implementations of the rule cookbook, SI only (the rules never convert units; convert at ingest, as
`open_fdd.nf` does). Each rule declares its roles, parameters and gating (operational proof, occupancy). Rule
statuses: `PASS`, `FAULT`, `SKIPPED_MISSING_ROLES`, `SKIPPED_EQUIPMENT_OFF`, `NOT_ASSESSED_NO_OCCUPANCY`,
`NOT_APPLICABLE_EQUIPMENT_TYPE`, `ERROR`. The full list with the real code is the
[pandas cookbook](rules/pandas-cookbook.html); the SQL twin and parity are in [FDD rules](fdd-rules.html).

```python
from open_fdd.rules import run_all, RULES_BY_ID
results = run_all(frames[("North", "AHU-1")], poll_seconds=300)   # list[RuleResult]
```

### ECM, reporting and anomaly

- `open_fdd.ecm_engineering`: `ECMJob`, calculators, workbook builders, `haystack_bindings.adapt_nf_model(model)` /
  `adapt_turtle(path)` (ECM assets and `fdd_ready` flags from the NF model).
- `open_fdd.reporting`: `build_engineering_findings(rule_results=...)` and `render_engineering_report`.
- `open_fdd.analytics`: motor run hours, occupancy, M&V change point, weather psychrometrics, load satisfaction.
- `open_fdd.analytics.anomaly`: the screening used by `open-fdd-anomaly`.

## Recipes for agents

**Pull a site from NF and run FDD in pandas.**
`open-fdd-nf model` (confirm the roles bound), `open-fdd-nf rules --days 7`, then `equipment_frames` and
`run_rules` for detail. A `not-assessed` row names the missing role in `missing_roles`; fix the model in NF, not here.

**Compare with the NF app's SQL results.** The app writes one result point per (site, equip, rule) with the `fault`
marker and a `ruleRef`. Query them with `client.query_all("default", {"field": {"property": "ruleRef", "text": "FC1"}})`
and compare `latestValue` (fault percent) with `run_rules` for the same window. The two engines are held equal by
[parity](rules/parity.html); a difference points at a binding or scale skip (look at `df.attrs["skipped"]`).

**Generate a report or ECM workbook.**
`open-fdd-report --nf --equip AHU-1 --days 14 --out out --docx` for findings; `open-fdd-ecm demo --out wb.xlsx` and
`open-fdd-ecm agent list_missing_inputs wb.xlsx` for a workbook and its open inputs.

**Work offline from the app's CSV export.** Download the CSV from the Export tab, then
`csv_frames("export.csv")` (or `open-fdd-report --csv`). Columns are matched to roles by point name
(`discharge-air-temp`, `ahu_sat`, ...); pass `column_roles={"AHU-1 SAT [°F]": "ahu_sat"}` for the rest. Units come from
the bracket in the header, so either export unit mode works.

**Alongside the NF MCP.** Use the MCP to *change* the site: connect, tag points, create equipment, fix classes and
units (`tag_points`, `manage_equipment`, `search_points`). Use this package to *read* the result: `open-fdd-nf model`
shows whether the roles now bind and `open-fdd-nf rules` whether the data is assessable. Keep the loop: model in NF, check with
`open-fdd-nf`, never patch site specifics into scripts. See [Modeling](modeling.html) and [Export](export.html).
