-- Open-FDD rule scorecard: portable SQL (PostgreSQL, TimescaleDB, SQLite; ANSI CTEs only).
--
-- Joins FDD rule results to fault labels and counts, per rule, TP / FP / FN / TN.
-- Expects two relations, which you create as VIEWs over your own tables:
--
--   scorecard_results(equipment_id, rule_id, window_start, window_end, status)
--       status: 'FAULT' and 'PASS' are decisions; anything else (INCONCLUSIVE, SKIPPED, ERROR, STALE, ...) is
--       counted as not assessed.
--   scorecard_labels(equipment_id, start_ts, end_ts, label, rule_id)
--       label: 'fault' or 'normal'. rule_id NULL = applies to every rule (a dataset label, e.g. a whole LBNL
--       faulted file, or a known healthy period); rule_id set = a verdict on that rule only (e.g. a technician
--       said this FAULT was a false positive -> label 'normal' with that rule_id).
--
-- Truth of a result window (overlap: label.start_ts < window_end AND label.end_ts > window_start):
--   1. a rule-specific label wins (fault beats normal if both overlap),
--   2. else any rule-agnostic 'fault' label  -> fault,
--   3. else any rule-agnostic 'normal' label -> normal,
--   4. else unlabeled (reported, never counted as TN).
-- Timestamps must share one type and zone in both relations (timestamptz in PostgreSQL, ISO-8601 UTC text in SQLite).

WITH truth AS (
  SELECT
    r.equipment_id, r.rule_id, r.window_start, r.window_end, r.status,
    MAX(CASE WHEN l.rule_id = r.rule_id AND l.label = 'fault'  THEN 1 ELSE 0 END) AS rs_fault,
    MAX(CASE WHEN l.rule_id = r.rule_id AND l.label = 'normal' THEN 1 ELSE 0 END) AS rs_normal,
    MAX(CASE WHEN l.rule_id IS NULL     AND l.label = 'fault'  THEN 1 ELSE 0 END) AS any_fault,
    MAX(CASE WHEN l.rule_id IS NULL     AND l.label = 'normal' THEN 1 ELSE 0 END) AS any_normal
  FROM scorecard_results r
  LEFT JOIN scorecard_labels l
    ON l.equipment_id = r.equipment_id
   AND l.start_ts < r.window_end
   AND l.end_ts > r.window_start
  GROUP BY r.equipment_id, r.rule_id, r.window_start, r.window_end, r.status
),
classified AS (
  SELECT
    rule_id,
    CASE WHEN status IN ('FAULT', 'PASS') THEN status ELSE 'NA' END AS decision,
    CASE
      WHEN rs_fault = 1 THEN 'fault'
      WHEN rs_normal = 1 THEN 'normal'
      WHEN any_fault = 1 THEN 'fault'
      WHEN any_normal = 1 THEN 'normal'
      ELSE 'unlabeled'
    END AS truth
  FROM truth
)
SELECT
  rule_id,
  SUM(CASE WHEN decision = 'FAULT' AND truth = 'fault'  THEN 1 ELSE 0 END) AS tp,
  SUM(CASE WHEN decision = 'FAULT' AND truth = 'normal' THEN 1 ELSE 0 END) AS fp,
  SUM(CASE WHEN decision = 'PASS'  AND truth = 'fault'  THEN 1 ELSE 0 END) AS fn,
  SUM(CASE WHEN decision = 'PASS'  AND truth = 'normal' THEN 1 ELSE 0 END) AS tn,
  SUM(CASE WHEN decision = 'NA' AND truth <> 'unlabeled' THEN 1 ELSE 0 END) AS not_assessed,
  SUM(CASE WHEN truth = 'unlabeled' THEN 1 ELSE 0 END) AS unlabeled,
  SUM(CASE WHEN decision = 'FAULT' AND truth = 'unlabeled' THEN 1 ELSE 0 END) AS unlabeled_faults
FROM classified
GROUP BY rule_id
ORDER BY rule_id;
