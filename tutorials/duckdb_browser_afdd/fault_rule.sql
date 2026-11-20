-- Teaching rule: supply air above 16 degrees Celsius while cooling is enabled.
-- The simulator runs this every 10 real seconds against the latest simulated hour.

INSERT INTO fdd.rule_result (equipment_id, rule_id, window_end, status, fault_samples)
WITH analysis_window AS (
    SELECT COALESCE(MAX(time), CURRENT_TIMESTAMP) AS window_end
    FROM nf.data
),
-- Turn the two point roles into columns at each equipment timestamp.
readings AS (
    SELECT equipment_id, ts,
           MAX(value) FILTER (WHERE role = 'sat') AS sat_c,
           MAX(value) FILTER (WHERE role = 'cooling_enabled') AS cooling_enabled
    FROM fdd.input_sample CROSS JOIN analysis_window
    WHERE ts > window_end - INTERVAL '1 hour' AND ts <= window_end
    GROUP BY equipment_id, ts
),
-- Keep every mapped AHU, including those with no complete readings.
scored AS (
    SELECT equipment.equipment_id,
           COUNT(*) FILTER (
               WHERE sat_c IS NOT NULL AND cooling_enabled IN (0, 1)
           ) AS usable_samples,
           COUNT(*) FILTER (
               WHERE sat_c > 16 AND cooling_enabled = 1
           ) AS faults
    FROM (SELECT DISTINCT equipment_id FROM fdd.point) AS equipment
    LEFT JOIN readings USING (equipment_id)
    GROUP BY equipment.equipment_id
)
SELECT equipment_id, 'SAT-HIGH', window_end,
       CASE
           WHEN usable_samples = 0 THEN 'NOT_ASSESSED'
           WHEN faults > 0 THEN 'FAULT'
           ELSE 'PASS'
       END,
       CASE WHEN usable_samples = 0 THEN NULL ELSE faults END
FROM scored CROSS JOIN analysis_window
ON CONFLICT (equipment_id, rule_id, window_end) DO UPDATE
SET status = excluded.status,
    fault_samples = excluded.fault_samples;

