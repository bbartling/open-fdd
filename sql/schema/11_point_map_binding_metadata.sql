-- Resolved binding metadata on point_map (forward-only, idempotent).
-- source_unit holds the NF portal tag only; unit is overlay > tag > empty.
-- quantity and cadence_secs come from the engineer overlay when declared.

ALTER TABLE point_map ADD COLUMN IF NOT EXISTS source_unit text;
ALTER TABLE point_map ADD COLUMN IF NOT EXISTS quantity text;
ALTER TABLE point_map ADD COLUMN IF NOT EXISTS cadence_secs bigint;
ALTER TABLE point_map ADD COLUMN IF NOT EXISTS history_mode text;
