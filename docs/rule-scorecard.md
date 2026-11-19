# Rule scorecard and offline review bundle

`open-fdd-scorecard` measures how often each FDD rule is right, on any SQL database, with nothing but
`pip install open-fdd` (standard library only: no Normal Framework, no Open-FDD app, no pandas). It works on
public labeled data (LBNL) and on a site's own confirmed verdicts, and it supports an **offline, privacy-preserving
review handoff**: the data owner exports a bundle, a reviewer fills in a verdict sheet, and no database or API
access is ever shared.

## Inputs

| Relation | Columns | Notes |
|---|---|---|
| results | `equipment_id, rule_id, window_start, window_end, status` | `FAULT` / `PASS` are decisions; anything else is "not assessed". Map your column names and status values with `--config` |
| labels / verdicts | `equipment_id, start_ts, end_ts, label, rule_id, fault_type, source, reviewer, notes` | `label` = `fault` / `normal` (or `confirmed` / `false_positive`); empty `rule_id` = applies to every rule; empty `label` = not reviewed |

Truth of a result window: a rule-specific label wins, then any rule-agnostic `fault`, then rule-agnostic `normal`,
else *unlabeled* (reported, never counted as TN).

Output per rule: TP, FP, FN, TN, not assessed, unlabeled, precision with a 95 % Wilson interval, recall, FPR,
false-positive share, median detection lead time, and `p_true_fault`: the estimated probability that the next FAULT
from that rule is real. With `--prior card.json` (for example a scorecard computed on LBNL data) the public-data
precision is a Beta prior worth `--prior-weight` verdicts, so a site starts from the public estimate and moves to its
own data as verdicts accumulate.

**Prevalence matters.** Precision measured on a labeled dataset depends on its fault / normal mix (LBNL has many
faulted files per fault-free file). Recall and FPR do not. Pass `--prevalence 0.05` (your expected share of truly
faulted windows) to get `precision_at_prevalence = recall·π / (recall·π + FPR·(1−π))` (rates smoothed as (k+0.5)/(n+1), so zero false positives in a short sample is not read as certainty); a prior card computed this way
is what `--prior` should use at a site.

## Run it inside your database

`open-fdd-scorecard sql` prints portable SQL (PostgreSQL, TimescaleDB, SQLite). Create two views,
`scorecard_results` and `scorecard_labels`, over your own tables and run it. The CLI runs the same SQL on CSV
exports in an in-memory SQLite database; the test suite checks both give identical counts.

## Offline review bundle

Owner side (on the machine that holds the data):

```bash
open-fdd-scorecard export --results results.csv \
    --history history_long_points.csv --point-map points.csv \
    --out bundle/ --private-dir keep_local/ --shift-days 364 --window-hours 6
zip -r bundle.zip bundle/          # send only this
```

- `history_long_points.csv`: `ts, equipment_id, point, value` in SI. `points.csv`: `point, role [, equipment_id]`.
- Several sites in one database: keep a `site_id` column in the results, history and point map (rename with
  `--site-column`). Equipment is then keyed by site + equipment, so `AHU_1` at two sites gets two aliases; the site
  id is dropped from the bundle and comes back only through `unalias` (as a `site_id` column).
- Role names: the point map may use the snake_case spelling (`zone_air_temp`); it is written as `zone-air-temp`.
  Inputs are checked before anything is written, and a malformed row is reported with its file and line number.
- Reviewer side: `open-fdd-scorecard check bundle/`, look at `history_long.csv` around each FAULT, fill in
  `bundle/verdicts.csv` (`label`, `fault_type`, `reviewer`, `notes`), send `verdicts.csv` back, and
  `open-fdd-scorecard run --bundle bundle/ --md card.md`.
- Owner side: `open-fdd-scorecard unalias --verdicts verdicts.csv --private-dir keep_local/ --out verdicts_real.csv`
  maps verdicts back to real equipment ids and times, to store next to the results.

Bundle files: `manifest.json` (format, version, privacy flags, SHA-256 of every file), `rule_results.csv`,
`labels.csv`, `verdicts.csv` (blank sheet, one row per FAULT episode: back-to-back FAULT windows of one rule on one unit, not checksummed), `history_long.csv`
(`ts, equipment_id, role, value`), `role_map.json` (roles per alias). Optional `config.json`.

### Privacy and security properties

- No connection: export, check, run and unalias are local file operations; nothing opens a socket or a database.
- Point names never leave: history is mapped to Open-FDD role names; unmapped points are dropped; `check` rejects
  anything that does not look like a role name.
- Equipment ids become `EQ-0001`-style aliases; site ids and every extra column are dropped.
- Optional uniform time shift (use whole weeks so hour of day and day of week, which rules depend on, are kept);
  the manifest's `created_utc` is shifted too, so the export date does not reveal the shift.
- Data minimization: only history within `--window-hours` of a FAULT window is exported.
- Re-identification data (alias map, shift) is written only to `--private-dir`, which must be outside the bundle.
- Integrity: `check` and `run --bundle` verify the SHA-256 of every exported file and refuse a changed bundle.
- Limits: values themselves are not perturbed, so a determined party could still match trends to weather or
  utility data; aliasing is pseudonymization, not anonymization. Share bundles under an agreement.

## LBNL labeled data

`open-fdd-ml export --download --out lbnl/` (needs `open-fdd[ml]`) writes the cached LBNL single-duct AHU subset as
`history_long.csv` (roles, SI) and `labels.csv` (one row per file: fault-free = `normal`, faulted = `fault`). Load
the history into your database, run your rules over it, export the results and score them against `labels.csv`.
Data: Lawrence Berkeley National Laboratory, LBNL FDD Data Sets, DOI 10.25984/1881324, CC BY 4.0.
