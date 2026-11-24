# Fault confidence triage

`open-fdd-ml confidence` reads the output of rule-based FDD and answers, for every fault episode: is this likely a
real fault, a false positive caused by data or operating context, or a sign that the rule needs review? It rolls the
episodes up per equipment and per rule and writes a short triage report for a person, or for an agent relaying to a
person.

It is advisory. It reads rule output and point history; it never changes a rule, a tuner, a tag or a stored result,
and the original rule results stay the source of record.

## Run it

```bash
# Open-FDD rule results in a database (default table fdd.rule_result; rule_result on SQLite)
open-fdd-ml confidence --sqlite fdd.db --out-dir triage
open-fdd-ml confidence --duckdb fdd.duckdb --site main-campus --since 2026-11-01
OPENFDD_CONFIDENCE_DSN="postgresql://readonly@host/db" open-fdd-ml confidence --postgres --data-quality-rules SV-

# Sample-level flags from any engine, as a table or a CSV
open-fdd-ml confidence --duckdb flags.duckdb --layout flags --table fault_flags
open-fdd-ml confidence --flags flags.csv --history history.csv --print md
```

```python
from open_fdd.ml.confidence import screen, screen_sql
from open_fdd.ml.confidence_sql import SourceMap, HistoryMap
from open_fdd.ml.confidence_report import build_report, to_markdown

result = screen_sql(conn, SourceMap(site_id="main-campus"), HistoryMap())   # any DB-API connection
report = build_report(result)        # dict, JSON-serialisable
print(to_markdown(report))
```

The output folder holds `report.json`, `report.md`, `episodes.csv`, `equipment.csv` and `rules.csv`. By default the
compact JSON report is printed to stdout; `--print md` prints the Markdown instead.

## Supported inputs

| Input | Engines | Notes |
|---|---|---|
| Open-FDD `fdd.rule_result` (default) | SQLite 3.25+, DuckDB, PostgreSQL, TimescaleDB | Consecutive FAULT windows of one equipment, rule and subject form an episode. Statuses other than FAULT and PASS count as not assessed |
| Sample flags table (`--layout flags`) | Same | One row per evaluation: `timestamp, equipment_id, rule_id, flag`, optional `value, threshold, running` |
| CSV or DataFrame | In-memory SQLite (standard library) | `--flags` or `--results`; same SQL as the database path |
| Point history (optional) | Same | Default `fdd.input_sample` joined to `fdd.point`; or any long table with `--point-table ''` |

Tested on SQLite, DuckDB and PostgreSQL. TimescaleDB uses the PostgreSQL path unchanged.

Episode building and per-rule totals run in the database as one portable query: CTEs, `ROW_NUMBER()` windows,
`CASE`, `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`. No `SQRT`, `STDDEV`, `FILTER` or date functions, so the same text runs on
every engine. Only episode and totals rows reach Python, so tables with millions of rows do not have to fit in pandas.
History is read per equipment, only around the episodes being scored (`--max-history-episodes`, default 500, longest
first). The test suite aggregates 1.15 million flag rows in SQLite.

### Custom schemas

Map your names with `--map NAME=COLUMN` (use `NAME=` for a column you do not have) and `--table`. History columns map
with `--history-map`. Status values map with `--fault-status` and `--pass-status`.

```bash
open-fdd-ml confidence --duckdb plant.duckdb --table alarms --map equipment_id=equip --map status=state \
  --map subject_key= --map fault_hours= --map covered_hours= --map site_id= \
  --fault-status ALARM --pass-status OK --history-table trends --point-table '' --history-map point_key=tag
```

Names are validated as plain SQL identifiers (`name` or `schema.name`). On SQLite, store timestamps as ISO 8601 UTC
text (`2026-11-01T06:00:00.000000Z`) so text order is time order; use native timestamps elsewhere. Use read-only
credentials; the PostgreSQL connection is opened read-only and the DSN is read from `OPENFDD_CONFIDENCE_DSN`, not the
command line.

## Labels and scores

| Column | Meaning |
|---|---|
| `p_real` | Evidence that the equipment really is in the faulted state |
| `p_false_positive` | Evidence that the flag comes from bad data or an operating context the rule does not model |
| `p_tuning` | Evidence that the rule's threshold or applicability is the problem |
| `label` | `likely_real`, `likely_false_positive`, `tuning_suggested`, or `uncertain` when no share reaches 0.45 |
| `reason` | The evidence behind the label, in plain words |

| Evidence | Pushes toward |
|---|---|
| Long, persistent episode (`fault_hours / covered_hours` for results) | real |
| Inputs abnormal versus the same point outside the episode (robust z-score) | real |
| Average exceedance of the threshold, in standard deviations of the compared value | real |
| Other rules fault on the same equipment at the same time | real |
| Stale, missing or clipped inputs during the episode | false positive, and discounts the real evidence above |
| Equipment not proven running for most of the episode | false positive |
| Very short, intermittent episode | false positive |
| Few flagged samples survive a 10 % standard-deviation threshold nudge | review |
| Rule fires on at least 60 % of the equipment it runs on (at least 3 units) | review |
| Rule flagged at least half the time on one unit | review |

Status points (`kind` bool, or values only 0 and 1) are not called stale; a fan that stays on is healthy. Missing
readings are counted against the point's own median spacing (or `expected_interval_s`); event-based points with
irregular spacing are not scored for gaps. The threshold nudge is computed from the data; nothing is re-run or saved.

### Data-quality rules

Pass sensor-validation rules with `--data-quality-rules SV-,DQ-` (rule-id prefixes). For those, poor input data
confirms the fault, and clean inputs suggest review. Their likely-real episodes count as `data_issues`, not equipment
faults, so a unit with only data problems is reported as `sensor or data issue`, and a data-quality rule confirmed on
most units is reported as a data problem across equipment.

## Triage report

`report.json` (version 1) and `report.md` list, in order: what to check next, the likely-real faults ranked by
`p_real`, confirmed data issues, repeating false-positive patterns per rule, rules to review, and an equipment health
ranking. A unit with two or more independent rules labeled likely real is `equipment issue likely`.

## What the scores are not

The scores are heuristic log-odds turned into shares; they are not calibrated probabilities until fitted to labeled
episodes (see #1721). A quiet anomaly score alone never yields `likely_false_positive`; that label needs data-quality
or operating-context evidence. Rule-review suggestions carry no new values; propose and replay those through the
normal tuning workflow.

Validated on synthetic data with planted real faults, planted false positives and a deliberately tight rule, and
exercised on a real multi-equipment site.
