-- Derived analytics / RCx / sensor-fault result cache (WP2a).
-- Forward-only. `analytics_result` is derived data, never telemetry.
-- Rows written before these columns existed carry empty stamps; the cache
-- treats them as incompatible and recomputes. No row is rewritten or removed.

ALTER TABLE analytics_result ADD COLUMN IF NOT EXISTS window_start text NOT NULL DEFAULT '';
ALTER TABLE analytics_result ADD COLUMN IF NOT EXISTS window_end text NOT NULL DEFAULT '';
ALTER TABLE analytics_result ADD COLUMN IF NOT EXISTS result_contract text NOT NULL DEFAULT '';
ALTER TABLE analytics_result ADD COLUMN IF NOT EXISTS sql_pack text NOT NULL DEFAULT '';
ALTER TABLE analytics_result ADD COLUMN IF NOT EXISTS model_revision text NOT NULL DEFAULT '';
ALTER TABLE analytics_result ADD COLUMN IF NOT EXISTS watermark_source text NOT NULL DEFAULT '';
ALTER TABLE analytics_result ADD COLUMN IF NOT EXISTS watermark_status text NOT NULL DEFAULT '';
ALTER TABLE analytics_result ADD COLUMN IF NOT EXISTS watermark_order bigint NOT NULL DEFAULT 0;
ALTER TABLE analytics_result ADD COLUMN IF NOT EXISTS watermark_utc text NOT NULL DEFAULT '';
ALTER TABLE analytics_result ADD COLUMN IF NOT EXISTS coverage text NOT NULL DEFAULT '';
ALTER TABLE analytics_result ADD COLUMN IF NOT EXISTS generated_at text NOT NULL DEFAULT '';
ALTER TABLE analytics_result ADD COLUMN IF NOT EXISTS engine text NOT NULL DEFAULT '';
ALTER TABLE analytics_result ADD COLUMN IF NOT EXISTS result_query_version text NOT NULL DEFAULT '';
ALTER TABLE analytics_result ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS analytics_result_building_updated_idx
  ON analytics_result (building_id, updated_at DESC);
