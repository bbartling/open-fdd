-- Open-FDD <-> NF TimescaleDB adapter. THE ONLY FILE THAT KNOWS NF's DDL.
--
-- Everything else (install.sql, hooks/lib/timescale.js, the history hook) reads samples through
--   openfdd.nf_samples(point_uuid text, ts timestamptz, value double precision)   NF native units (long-range history)
--   fdd.input_sample(site_id, point_key, ts, value)   SI values for the FDD rules (contract: sql/fdd/input_contract.json "sources")
-- Sweep queries keep point_uuid as the physical sensor identity, even when sensors share a role.
-- so if NF's tables differ from the default below, edit the SELECT here and re-run this file
-- (install() in hooks/lib/timescale.js runs core.sql, then this file, then install.sql; with psql:
--   psql -f core.sql -f adapter_nf.sql -f install.sql ). Edit BOTH views below when you change a table reference.
--
-- Documented by NF (docs.normal.dev/timescale): data(point_id, time, value), points(id, name).
-- Check the live box with:  \d data   \d points   \d instances   and  \dv
-- Typical edits:
--   * data lives in another schema          -> FROM nf.data
--   * value is numeric/bool or jsonb        -> value::double precision / (value->>'v')::double precision
--   * the key is the point uuid in a column of `points` -> join points p ON p.id = d.point_id and
--     select p.uuid::text (point_uuid MUST equal the NF point uuid the hook uses)
--   * one data table per layer              -> UNION ALL the layer views
CREATE SCHEMA IF NOT EXISTS openfdd;

CREATE OR REPLACE VIEW openfdd.nf_samples WITH (security_invoker = true) AS
SELECT d.point_id::text         AS point_uuid,
       d."time"::timestamptz    AS ts,
       d.value::double precision AS value
FROM public.data d;

-- SI samples for the FDD rules: every sample of a bound point (fdd.point, synced by the fdd hook from the Haystack
-- model) with its native value brought to SI by the point's si_scale / si_offset (value_si = value * si_scale + si_offset;
-- the affine map commutes with avg, so per-bucket averages equal the old avg-then-convert). NULL values are removed.
-- Join key: when data.point_id is a uuid the join compares uuids, so NF's (point_id, time) index is used; otherwise text.
-- Requires fdd.point (core.sql runs first). fdd.point keys are NF point uuids written by the hook.
DO $adapter$
DECLARE
  v_join text;
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'data' AND column_name = 'point_id' AND data_type = 'uuid') THEN
    v_join := 'd.point_id = p.point_key::uuid';
  ELSE
    v_join := 'd.point_id::text = p.point_key';
  END IF;
  EXECUTE format($v$
    CREATE OR REPLACE VIEW fdd.input_sample WITH (security_invoker = true) AS
    SELECT p.site_id::text                                        AS site_id,
           p.point_key::text                                      AS point_key,
           d."time"::timestamptz                                  AS ts,
           (d.value::double precision * p.si_scale + p.si_offset) AS value
    FROM fdd.point p
    JOIN public.data d ON %s
    WHERE d.value IS NOT NULL
  $v$, v_join);
END
$adapter$;
