-- Synthetic stand-in for NF's TimescaleDB northbound schema (the real DDL is unconfirmed; see README).
-- Tables: instances, points, data (hypertable, 1-day chunks) in schema public, like the NF connector.
-- ~60 days (2026-09-01 .. 2026-10-31 UTC) of 5-minute data for one AHU's roles, values in NF units (°F, inH2O, %).
-- Re-runnable: drops and rebuilds the three tables (CASCADE also drops openfdd.nf_samples; run install again).
CREATE EXTENSION IF NOT EXISTS timescaledb;

DROP TABLE IF EXISTS public.data CASCADE;
DROP TABLE IF EXISTS public.points CASCADE;
DROP TABLE IF EXISTS public.instances CASCADE;

CREATE TABLE public.instances (id uuid PRIMARY KEY, name text NOT NULL);
CREATE TABLE public.points (id uuid PRIMARY KEY, instance_id uuid REFERENCES public.instances(id), name text NOT NULL, units text);
CREATE TABLE public.data (point_id uuid NOT NULL, "time" timestamptz NOT NULL, value double precision);
SELECT create_hypertable('public.data', 'time', chunk_time_interval => interval '1 day');
CREATE INDEX ON public.data (point_id, "time" DESC);

INSERT INTO public.instances VALUES (md5('instance')::uuid, 'nf-test');

-- role -> NF unit; point name 'AHU-1/<role>', uuid = md5(name)
DROP TABLE IF EXISTS pg_temp.roles;
CREATE TEMP TABLE roles (role text, unit text);
INSERT INTO roles VALUES
  ('sat', 'degF'), ('sat_sp', 'degF'), ('rat', 'degF'), ('mat', 'degF'), ('oa_t', 'degF'), ('oa_h', '%RH'),
  ('zone_t', 'degF'), ('duct_static', 'inH2O'), ('duct_static_sp', 'inH2O'), ('fan_status', ''), ('fan_cmd', '%'),
  ('oa_damper_pct', '%'), ('htg_valve_pct', '%'), ('clg_valve_pct', '%');

INSERT INTO public.points
SELECT md5('AHU-1/' || role)::uuid, md5('instance')::uuid, 'AHU-1/' || role, unit FROM roles;

INSERT INTO public.data (point_id, "time", value)
SELECT md5('AHU-1/' || r.role)::uuid, g.t,
  CASE r.role
    WHEN 'oa_t'   THEN s.oa
    WHEN 'oa_h'   THEN 55 + 25 * sin(g.d * 0.9) + s.nz * 4
    WHEN 'rat'    THEN 72 + s.nz * 0.4
    WHEN 'zone_t' THEN 72.5 + s.nz * 0.6
    WHEN 'mat'    THEN 0.3 * s.oa + 0.7 * (72 + s.nz * 0.4)
    WHEN 'sat_sp' THEN 55
    WHEN 'sat'    THEN CASE WHEN s.fan_on THEN 55 + s.nz * 0.5 + CASE WHEN g.d BETWEEN 30 AND 32 THEN 9 ELSE 0 END ELSE 72 END
    WHEN 'duct_static_sp' THEN 1.5
    WHEN 'duct_static' THEN CASE WHEN NOT s.fan_on THEN 0.02
                                 WHEN g.d BETWEEN 10 AND 12 THEN 0.45 + s.nz * 0.02
                                 ELSE 1.5 + s.nz * 0.03 END
    WHEN 'fan_status' THEN CASE WHEN s.fan_on THEN 1 ELSE 0 END
    WHEN 'fan_cmd'    THEN CASE WHEN NOT s.fan_on THEN 0 WHEN g.d BETWEEN 10 AND 12 THEN 100 ELSE 60 + 10 * sin(g.d) END
    WHEN 'oa_damper_pct' THEN CASE WHEN NOT s.fan_on THEN 0 ELSE least(100, greatest(15, 20 + 80 * (s.oa - 50) / 30.0)) END
    WHEN 'htg_valve_pct' THEN CASE WHEN s.fan_on AND s.oa < 50 THEN least(100, (55 - s.oa) * 4) ELSE 0 END
    WHEN 'clg_valve_pct' THEN CASE WHEN s.fan_on AND s.oa > 65 THEN least(100, (s.oa - 60) * 5)
                                   WHEN s.fan_on AND g.d BETWEEN 40 AND 41 THEN 80 ELSE 0 END
  END
FROM generate_series(timestamptz '2026-09-01 00:00:00+00', timestamptz '2026-10-30 23:55:00+00', interval '5 minutes') AS g0(t)
CROSS JOIN LATERAL (SELECT g0.t AS t, extract(epoch FROM g0.t - timestamptz '2026-09-01 00:00:00+00') / 86400.0 AS d) g
CROSS JOIN roles r
CROSS JOIN LATERAL (
  SELECT 55 + 22 * sin(g.d * 2 * pi() / 60.0) + 10 * sin((g.d - 0.25) * 2 * pi()) + sin(g.d * 977.0) * 0.8 AS oa,
         sin(g.d * 3331.0 + length(r.role)) AS nz,
         (extract(dow FROM g.t) BETWEEN 1 AND 5 AND extract(hour FROM g.t) BETWEEN 6 AND 18) AS fan_on
) s
-- a 3 hour outage of the SAT sensor on day 20 (gap handling)
WHERE NOT (r.role = 'sat' AND g.d BETWEEN 20 AND 20.125);

ANALYZE public.data;
