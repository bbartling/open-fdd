# Grafana dashboards (optional)

Open-FDD does not ship pre-built dashboards here. Use the [Grafana SQL cookbook](https://bbartling.github.io/open-fdd/howto/grafana_cookbook) (source: `docs/howto/grafana_cookbook.md`) to build panels against the provisioned TimescaleDB datasource (`openfdd_timescale`).

Start Grafana with `./scripts/bootstrap.sh --with-grafana`.
