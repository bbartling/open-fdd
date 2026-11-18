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

Not in this slice: SQL and pandas before/after replay of a proposed tuner change, inputs resolved through the RDF
bindings, and the labeled held-out evaluation of alert reduction that #1667 asks for. No alert-reduction number is
claimed here.
