# Fault confidence screening

`open-fdd-ml confidence` reads the fault flags a rule engine produced and the point history behind them, groups the
flags into episodes, and gives every episode three scores and a label:

| Column | Meaning |
|---|---|
| `p_real` | Evidence that the equipment really is in the faulted state |
| `p_false_positive` | Evidence that the flag comes from bad data or an operating context the rule does not model |
| `p_tuning` | Evidence that the threshold or applicability of the rule is the problem |
| `label` | `likely_real`, `likely_false_positive`, `tuning_suggested` or `uncertain` (no score at or above 0.45) |
| `reason` | The evidence behind the label, in plain words |

It is advisory. It does not change a rule, a tuner, a tag or a stored result, and the original flags stay the source
of record.

## Input

Any engine works (SQLite, PostgreSQL/Timescale, DuckDB, pandas). Export two long tables:

`flags.csv`, one row per rule evaluation sample:

| Column | Required | Notes |
|---|---|---|
| `timestamp` | yes | UTC, or ISO 8601 with offset |
| `equipment_id`, `rule_id` | yes | Any stable identifiers |
| `flag` | yes | 1/0, true/false or FAULT/PASS |
| `value`, `threshold` | no | SI quantity the rule compared and its limit; enables margin and threshold sensitivity |
| `direction` | no | `above` or `below`; inferred when missing |
| `running` | no | 1 when the equipment was proven on |

`history.csv` (optional): `timestamp`, `equipment_id`, `point_id`, `value` in SI units.

```bash
open-fdd-ml confidence --flags flags.csv --history history.csv --out-dir confidence_out
```

```python
from open_fdd.ml.confidence import screen
result = screen(flags_df, history_df)   # dict of DataFrames: episodes, equipment, rules
```

The output folder holds `episodes.csv`, `equipment.csv`, `rules.csv` and `summary.json`.

## Evidence used

| Evidence | Pushes toward |
|---|---|
| Long, persistent episode | real |
| Inputs abnormal versus the same point outside the episode (robust z-score, MAD) | real |
| Large exceedance of the threshold, in robust spreads of the compared value | real |
| Other rules fault on the same equipment at the same time | real |
| Stale, flatlined, missing or clipped inputs during the episode | false positive (and discounts the real evidence above) |
| Equipment not proven running for most of the episode | false positive |
| Very short, intermittent episode | false positive |
| Few flagged samples survive a small threshold nudge (default 10 % of the robust spread) | tuning |
| Rule fires on most of the equipment it runs on (default 60 %, at least 3 units) | tuning |
| Rule flagged most of the time on one unit (chronic, default 50 %) | tuning |

The threshold nudge is computed offline from the data. Nothing is re-run or saved.

## Roll-ups

`equipment.csv` counts episodes and labels per unit. Two or more distinct rules labeled `likely_real` on one unit
gives `equipment issue likely`. Only tuning or data labels give `faults look like tuning` or
`faults look like data or context`.

`rules.csv` compares each rule across its equipment. A rule that fires on most units, or whose episodes mostly score
as tuning, gives `review threshold or applicability`.

## What the scores are not

The scores are heuristic log-odds turned into shares by a softmax. They are not calibrated probabilities until fitted
to labeled episodes (see #1721). A quiet anomaly score alone never yields `likely_false_positive`; that label needs
data-quality or operating-context evidence. Tuning suggestions do not include new values; propose and replay those
through the normal tuning workflow.

Validated on synthetic data with planted real faults, planted false positives and a deliberately tight rule, and
exercised on a real multi-equipment site.
