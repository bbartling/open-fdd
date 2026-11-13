-- Read-only DB role for the optional pgweb sidecar (Full edition only; run as installer/postgres).
-- Replace the password before running, and keep it out of git.
-- Example:
--   CREATE ROLE openfdd_ro LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '...';
ALTER ROLE openfdd_ro SET default_transaction_read_only = on;
ALTER ROLE openfdd_ro SET statement_timeout = '10s';

GRANT USAGE ON SCHEMA public TO openfdd_ro;
GRANT SELECT ON public.data, public.points, public.instances TO openfdd_ro;
GRANT USAGE ON SCHEMA openfdd TO openfdd_ro;
GRANT SELECT ON openfdd.nf_samples, openfdd.config TO openfdd_ro;
GRANT USAGE ON SCHEMA fdd TO openfdd_ro;
GRANT SELECT ON fdd.point, fdd.rule_result, fdd.rule_config, fdd.input_sample TO openfdd_ro;
