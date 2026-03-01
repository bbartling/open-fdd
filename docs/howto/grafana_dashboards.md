---
title: Grafana dashboards
parent: How-to Guides
nav_order: 41
---

# Grafana dashboards

No dashboards are provisioned by default. Only the **datasource** (TimescaleDB, uid: `openfdd_timescale`) is prebuilt.

To build your own dashboards using SQL and the Open-FDD database, see the **[Grafana SQL cookbook](grafana_cookbook)**.

You can also place dashboard JSON files in `stack/grafana/dashboards/` (or the directory mounted at `/var/lib/grafana/dashboards` in the Grafana container) and restart Grafana to load them.
