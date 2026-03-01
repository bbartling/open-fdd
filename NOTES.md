# Notes (high-level, for maintainer only)

- **Docs:** All documentation lives in `docs/`. Root has only this file and `README.md`.
- **Docker nuclear prune:** Full teardown (stop, rm containers, rmi images, volumes, networks, prune). See `docs/howto/danger_zone.md` for steps.
- **FDD ideas (future):** Store fault_energy_impact (low/typical/high); fault_test_vectors + CI runner for regression.
- **Weather / timeseries:** Open-Meteo → `timeseries_readings` (temp_f, rh_pct, etc.). Check via Grafana or `docs/howto/grafana_cookbook.md`.
- **FDD logs / fault_results:** `docker exec openfdd_timescale psql -U postgres -d openfdd -c "SELECT ... FROM fdd_run_log ..."` and `fault_results`; see docs for queries.
- **HA addon:** `./scripts/bootstrap.sh --ha-addon` → `openfdd-addon:local`. Copy `stack/ha_addon` to HA addons; image = `openfdd-addon:local`. Smoke test via Developer Tools → Services (`openfdd.*`). Details: `docs/integrations/home_assistant.md`.
- **PyPI:** Prefer a small **integration-helpers** package only (e.g. `openfdd-client`): HTTP client + optional WS + optional Pydantic models. Full platform stays repo/Docker.
