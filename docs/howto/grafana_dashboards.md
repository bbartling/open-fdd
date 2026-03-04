---
title: Grafana dashboards
parent: How-to Guides
nav_order: 41
---

# Grafana dashboards

No dashboards are provisioned by default. Only the **datasource** (TimescaleDB, uid: `openfdd_timescale`) is prebuilt.

To build your own dashboards using SQL and the Open-FDD database, see the **[Grafana SQL cookbook](grafana_cookbook)**.

You can also place dashboard JSON files in `stack/grafana/dashboards/` (or the directory mounted at `/var/lib/grafana/dashboards` in the Grafana container) and restart Grafana to load them.

## React frontend parity

The React UI provides equivalent time-series and stat views for FDD workflows:

- **Trending** — Multi-point time-series (site/equipment/point picker, date range, dual Y-axis). Uses the same `timeseries_readings` data as the Grafana BACnet timeseries dashboard.
- **Faults** — Active fault table (with **Device** and **Sensor/point** columns so you can see which bad sensor was found on which device), fault definitions, fault count (period) stat, and fault flags over time chart (from `fault_results` via `GET /analytics/fault-timeseries` and `GET /analytics/fault-summary`).
- **Overview** — Site cards with fault counts, equipment/points stats, and FDD status.
- **System resources** — A dedicated sidebar page that mirrors the Grafana “System Resources (Host & Containers)” dashboard: host memory used/available, load average (1m/5m/15m), swap used (stat cards with threshold colors), host memory and load time-series charts, container memory (MB) and CPU % charts, **Containers (latest)** table (CPU %, Mem MB, Mem %, PIDs), and **disk usage** per mount (used/free/total GB, % used, progress bar). Data comes from `host_metrics`, `container_metrics`, and `disk_metrics` via `GET /analytics/system/*`. Requires the **host-stats** service to be running so those tables are populated.

If you prefer building custom SQL dashboards in Grafana, use the [cookbook](grafana_cookbook) and the same tables (`host_metrics`, `container_metrics`, `disk_metrics`, `timeseries_readings`, `fault_results`, etc.).
