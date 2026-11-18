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
| `insufficient_evidence` | No training source, training overlapping the episode, no rows in the window, no run proof in the window or the training rows (`no_run_proof`, `training_no_run_proof`), no proven running rows in the window, a SQL result marked unassessed (`assessed: false`, `run_proof: false`, `run_proof_source: null` or `skip_reason: no_run_proof`), or no method able to assess enough rows; `reasons` lists each one |

A quiet or unsupported detector is not evidence of a false positive: the review never emits that label, keeps
`sql_verdict` and `report_inclusion: keep`, and says why in `reasons`. Labeling a SQL episode a false positive needs
independent healthy or maintenance evidence. A training folder or cutoff is recorded as an operator assertion, not a
verified label. If that baseline already contains the fault, the methods go quiet and the episode stays in the report
as `needs_review`.

Each method record has its status, the roles it used, active / assessed / flagged row counts, the assessed coverage
and flagged share. A corroborating PCA adds its top contributors, and gray-box adds the median residual per family.
The review also records the policy thresholds, seed, package version and SHA-256 fingerprints of the episode and
folder files.

Not in this slice: SQL and pandas before/after replay of a proposed tuner change, inputs resolved through the RDF
bindings, and the labeled held-out evaluation of alert reduction that #1667 asks for. No alert-reduction number is
claimed here.

**Active rows** follow the run-proof contract (`sql/fdd/run_proof.json`, `open_fdd.run_proof.derive_run_proof`), the
same proof the SQL and pandas rules gate on: a resolved `run-proof` column first, then the unit's own status roles,
then its own command roles, running when above the contract threshold (`> 0.05`). A frame marked
`run_proof_resolved` counts only its `run-proof` column. Rows with an `occupied` role at 0 are not active. Training
rows are filtered the same way before any method is fitted. With no proof the review is `insufficient_evidence`; ML
never scores rows the SQL rule did not judge.
