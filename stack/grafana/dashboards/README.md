# Grafana dashboards

No dashboards are provisioned by default. Only the **datasource** (TimescaleDB, uid: `openfdd_timescale`) is prebuilt.

To build your own dashboards using SQL and the Open-FDD database, see **[Grafana SQL cookbook](../../../docs/howto/grafana_cookbook.md)** in the docs.

You can also place dashboard JSON files in this folder (or in the directory mounted at `/var/lib/grafana/dashboards` in the Grafana container) and restart Grafana to load them.
