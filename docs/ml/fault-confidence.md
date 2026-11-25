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

# Compare the screen to the raw rules (synthetic planted-fault benchmark)
open-fdd-ml confidence --evaluate --out-dir eval
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

The output folder holds `report.json`, `report.md`, `episodes.csv`, `episodes.jsonl`, `equipment.csv` and `rules.csv`.
By default the compact JSON report is printed to stdout; `--print md` prints the Markdown instead. `episodes.jsonl` has
one JSON object per episode (identity, label, the three probabilities and the reason, then an `evidence` object), with
UTC timestamps and `null` for evidence that was not assessed, for agents that page through episodes.

## Identifiers for downstream tools

`episodes.jsonl` and `report.json` copy source identifiers verbatim so a downstream graph, review bundle or root-cause
tool can join without a lookup table:

| Field | Contract |
|---|---|
| `equipment_id` | Exactly the `equipment_id` stored on the rule-result or flags row. No slug, display name or hash is substituted. |
| `rule_id` | Exactly the source `rule_id`. |
| `subject` | The source `subject_key`, or `""` when the table has none. |
| `site_id` | The source `site_id` column when present, otherwise the `--site` filter. `null` in `episodes.jsonl` (omitted from `report.json` objects) when neither was given. The literal strings `"None"` and `"nan"` are kept as identifiers, not treated as missing. Flags input that includes a `site_id` column is copied through. When a table covers more than one site and `--site` is not set, the command errors instead of merging episodes that share an `equipment_id` across sites. |
| `episode_id` | `E000001`, `E000002`, … stable for one run of the command, not a durable identifier across runs. |
| `start`, `end` | ISO 8601 UTC ending in `Z` (`episodes.jsonl` uses seconds; `report.json` minute precision). |

`report.json` repeats the same `equipment_id` (and `site_id` when known) on `likely_real`, `confirmed_data_issues` and
`equipment_ranking`. Unassessed numeric evidence is JSON `null`, never `0`. CSV inputs (`--flags`, `--results`,
`--history`, `--labels`) read identifier columns (`equipment_id`, `rule_id`, `site_id`, `point_id`, `subject`,
`subject_key`) as text so leading zeros are kept. When both the episodes and the `--labels` table have a `site_id`,
a label only matches an episode at the same site (a label with no site still matches by equipment).

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
command line. Both PostgreSQL reads run in one REPEATABLE READ transaction, so they see the same snapshot.

`--since` (inclusive) and `--until` (exclusive) accept any ISO 8601 time with or without an offset and are converted to
UTC in the form each engine compares. `--site` also scopes the history reads; history without a `site_id` column is
left out when `--site` is set. These three filters apply to database sources only; filter a CSV before screening it.

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
| Stale, missing or clipped inputs during the episode | false positive, and discounts process-fault evidence (persistence, anomaly, margin, co-faults), falling to zero once half the episode is stale, gapped or clipped |
| Equipment not proven running for most of the episode | false positive, and discounts the real evidence above (a process rule cannot confirm a fault while the unit is off) |
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

## Calibrating against reviewed episodes

With reviewer verdicts, `--labels verdicts.csv` (`equipment_id, start_ts, end_ts, label`, optional `rule_id`; label
`fault` or `normal`) compares the heuristic `p_real` with three numpy-only fits on held-out folds (grouped by
equipment when there are enough units):

* **Temperature scaling** — one parameter on the heuristic score (`p_real_temperature`). `T > 1` softens
  over-confident probabilities.
* **Isotonic regression** — a monotone map of that score (`p_real_isotonic`).
* **L2-regularised logistic regression** on the episode evidence (`p_real_calibrated`, kept under that name for
  compatibility).

The report shows held-out Brier score, expected calibration error and AUC for each, next to the heuristic. A
rule-specific verdict overrides a rule-agnostic one. Fitting needs at least 20 labeled episodes and 5 of each
verdict; otherwise the report says it was not fitted. Public labeled data (#1721) can seed the fit before a site
has its own verdicts. These maps are not a substitute for a well-calibrated score in the absence of labels, and
they are not fitted to the built-in generator.

## Comparing the screen to the rules

The screen does not replace the rules; it ranks the episodes they already flagged. To measure whether that ranking
helps, you need ground truth: a reviewer verdict per episode, or the built-in synthetic set whose planted cases are
known.

```
# Built-in benchmark (no site data). Default: several seeds, mean and spread reported.
# Planted cases: real faults (one with a brief history gap), full and partial stale sensors,
# equipment-off false positives, mixed rule tightness, and sensor noise.
open-fdd-ml confidence --evaluate --out-dir eval
# one seed, and the CSVs if you want to inspect or re-run them
open-fdd-ml confidence --evaluate --seeds 7 --write-benchmark bench --out-dir eval
```

`eval/evaluation.json` and `eval/evaluation.md` report:

* **Operational precision and recall** for the *real-fault* class, scored only on labeled real faults vs labeled
  false positives so a mis-tuned rule does not dominate. The raw rule treats every flagged episode as a predicted
  real fault; the screen keeps only episodes labeled `likely_real`. Overall figures (including tuning episodes) are
  listed as well. Tuning episodes are reported separately (how often they are labeled `tuning_suggested`).
* **False-positive reduction** at a fixed real-fault recall (default 0.90, also 0.80 and 1.00), on the operational
  set. A 60 % reduction at 0.90 recall means the screen dropped three fifths of the labeled false positives while
  still catching at least 90 % of the labeled real faults. Change the target with `--target-recall`.
* **Several seeds** (default `7,11,19,23,31`): mean, standard deviation, min and max of the headline metrics.
  Pass `--seeds 7` or `--seed 7` for a single run. `--seed` also sets the generator seed for `--write-benchmark`
  (default 7). `--seeds` overrides `--seed` when both are given.
* **Confusion matrix** of the three ground-truth classes (`real`, `false_positive`, `tuning`) against the four
  screen labels (`likely_real`, `likely_false_positive`, `tuning_suggested`, `uncertain`).
* **Calibration** of `p_real` as a probability that the episode is a real fault (Brier score, expected calibration
  error, AUC). With enough labels, held-out temperature scaling, isotonic regression and the logistic fit are shown
  as well.

To score your own rule output the same way, pass the usual input plus a verdict file. Labels are
`equipment_id, start_ts, end_ts, label` with optional `rule_id`. `label` is `fault`, `false_positive` or `tuning`
(`real` / `confirmed` and `normal` / `stale` / `off` / `review` are accepted). A rule-specific verdict wins over a
rule-agnostic one.

```
open-fdd-ml confidence --evaluate --flags flags.csv --history history.csv --labels reviews.csv --out-dir eval
open-fdd-ml confidence --evaluate --sqlite fdd.db --labels reviews.csv --out-dir eval
```

Without reviewed labels you cannot compute precision or recall on a site. Run `--evaluate` on the synthetic set to
see how the method behaves on planted cases, then use `report.md` on the site as a qualitative triage (likely-real
faults, false-positive patterns, rules to review). The screen still does not change a threshold or a stored result.

## What the scores are not

Without `--labels` the scores are heuristic log-odds turned into shares, not calibrated probabilities. A quiet anomaly score alone never yields `likely_false_positive`; that label needs data-quality
or operating-context evidence. Rule-review suggestions carry no new values; propose and replay those through the
normal tuning workflow.

Validated on synthetic data with planted real faults, planted false positives and a deliberately tight rule, and
exercised on a real multi-equipment site.
