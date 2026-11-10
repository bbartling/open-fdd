-- Open-FDD <-> NF TimescaleDB adapter. THE ONLY FILE THAT KNOWS NF's DDL.
--
-- Everything else (install.sql, hooks/lib/timescale.js, the history hook) reads samples through
--   openfdd.nf_samples(point_uuid text, ts timestamptz, value double precision)
-- Sweep queries keep point_uuid as the physical sensor identity, even when sensors share a role.
-- so if NF's tables differ from the default below, edit the SELECT here and re-run this file
-- (install() in hooks/lib/timescale.js runs it before install.sql; with psql:
--   psql -f adapter_nf.sql -f install.sql ).
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

CREATE OR REPLACE VIEW openfdd.nf_samples AS
SELECT d.point_id::text         AS point_uuid,
       d."time"::timestamptz    AS ts,
       d.value::double precision AS value
FROM public.data d;
