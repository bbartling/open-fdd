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
| `insufficient_evidence` | No training source, training overlapping the episode, no rows in the window, no run proof in the window or the training rows (`no_run_proof`, `training_no_run_proof`), no proven running rows in the window, a SQL result marked unassessed (`assessed: false`, `operating_status: false`, `run_proof_source: null` or `skip_reason: no_run_proof`), or no method able to assess enough rows; `reasons` lists each one |

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

**Active rows** follow the run-proof contract (`sql/fdd/run_proof.json`, `open_fdd.run_proof.derive_run_proof`), the
same proof the SQL and pandas rules gate on: a resolved `run-proof` column first, then the unit's own status roles,
then its own command roles, running when above the contract threshold (`> 0.05`). A frame marked
`run_proof_resolved` counts only its `run-proof` column. Rows with an `occupied` role at 0 are not active. Training
rows are filtered the same way before any method is fitted. With no proof the review is `insufficient_evidence`; ML
never scores rows the SQL rule did not judge.

## Synthetic end-to-end demo

`python -m open_fdd.ml.review_demo ./review-demo` runs the whole workflow from an installed wheel with no NF,
database or network: it writes a seeded synthetic SI device folder (`AHU-DEMO`, damper stuck from day 8), two saved
SQL episodes (a real fault and an alert on a healthy day), their reviews, a labeled corpus and its evaluation, and
prints a summary. Two episodes cannot support a claim, so `eval.json` reports `claim_supported: false`.

## Scoring reviews on a labeled held-out corpus

`python -m open_fdd.ml.review_eval labeled.json --out eval.json` scores saved reviews against independent labels
(maintenance records, functional tests, engineer review). The corpus is
`{"test_device_weeks": <total or {equipment: weeks}>, "episodes": [...]}`, a bare list or JSON Lines.
`test_device_weeks` is the explicit exposure of the test period: every test equipment and its monitored weeks,
including units that raised no alert. Its total is the one alerts-per-device-week denominator for the overall block
and every category block; without it, burden is not reported (the older `device_weeks` key is ignored with a note). Each episode has
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
