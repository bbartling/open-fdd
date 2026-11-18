# Reviewing a SQL fault episode with ML evidence

First slice of #1667. `python -m open_fdd.ml.review` takes one saved SQL fault episode, the SI device folder for the
same equipment and an explicit known-good training source. It writes a JSON review next to the SQL result and never
replaces it.

```bash
python -m open_fdd.ml.review episode.json ./AHU_1 --train ./AHU_1_known_good --out review.json
python -m open_fdd.ml.review episode.json ./AHU_1 --train-until 2026-06-01 --methods grey_box,pca,ocsvm
```

`episode.json` needs `rule_id`, `verdict`, `start_utc` and `end_utc`. Any other fields (identity, SI tuners, assessed
coverage, run proof, rule revision, input watermark) are copied into the review unchanged.

## Outcomes

| `outcome` | When |
|---|---|
| `corroborated` | A baseline-learning method (gray-box, PCA, one-class SVM, COPOD), fitted on training rows that do not overlap the episode, assessed at least half of the episode's active rows and flagged at least 25 % of those |
| `needs_review` | The methods assessed the episode and stayed quiet |
| `insufficient_evidence` | No training source, training overlapping the episode, no rows or no active rows in the window, a SQL result marked unassessed (`assessed: false` or `run_proof: false`), or no method able to assess enough rows; `reasons` lists each one |

A quiet or unsupported detector is not evidence of a false positive: the review never emits that label, keeps
`sql_verdict` and `report_inclusion: keep`, and says why in `reasons`. Labeling a SQL episode a false positive needs
independent healthy or maintenance evidence. A training folder or cutoff is recorded as an operator assertion, not a
verified label. If that baseline already contains the fault, the methods go quiet and the episode stays in the report
as `needs_review`.

Each method record has its status, the roles it used, active / assessed / flagged row counts, the assessed coverage
and flagged share. A corroborating PCA adds its top contributors, and gray-box adds the median residual per family.
The review also records the policy thresholds, seed, package version and SHA-256 fingerprints of the episode and
folder files.

Not in this slice: SQL and pandas before/after replay of a proposed tuner change and inputs resolved through the RDF
bindings. No alert-reduction number is claimed here.

## Scoring reviews on a labeled held-out corpus

`python -m open_fdd.ml.review_eval labeled.json --out eval.json` scores saved reviews against independent labels
(maintenance records, functional tests, engineer review). The corpus is
`{"device_weeks": <total or {equipment: weeks}>, "episodes": [...]}`, a bare list or JSON Lines. Each episode has
`equipment`, `category`, `split` (`train`, `selection` or `test`), `label` (`fault`, `healthy` or `unknown`),
`sql_verdict`, the `review` record (or `review_outcome`), and optional `label_onset_utc` / `sql_start_utc` for delay.
List labeled genuine faults SQL never raised too (`sql_verdict` empty) so they count against recall.

Only the `test` split is scored, overall and per `category`. Because the review never removes a SQL alert, the
report compares tiers: `raw_sql` (every SQL fault), `reviewed_priority` (the corroborated ones) and one
`method:<name>` tier per method. Each tier lists alerts, alerts per device-week, true / false / unlabeled alerts,
precision and recall with Wilson 95 % intervals, median detection delay and the missed fault IDs. Each block also
reports the review outcomes, reviewer workload (everything not corroborated) and excluded coverage
(`insufficient_evidence` share). `unknown` labels count toward burden and workload, never toward precision or recall.

`claim_supported` stays `false` until the test split has at least `--min-labeled` (default 20) labeled faults and
healthy episodes and train/selection episodes end before the first test episode; `holdout.shared_equipment` shows
whether an equipment holdout also holds. Quote no alert-reduction figure while `claim_supported` is false.
