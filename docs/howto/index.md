---
title: How-to Guides
nav_order: 10
has_children: true
---

# How-to Guides

- [MQTT integration (optional)](mqtt_integration) — Mosquitto profile, BACnet2MQTT vs experimental MQTT RPC gateway on diy-bacnet-server; links to upstream docs.
- [Grafana dashboards (optional)](grafana_dashboards) — Optional Grafana; React frontend provides equivalent timeseries and fault views. Datasource and dashboard JSON.
- [Grafana SQL cookbook](grafana_cookbook) — SQL recipes for BACnet, faults, weather, system resources (variables, panels, sparklines).
- [PyPI releases (open-fdd)](openfdd_engine_pypi) — Tags, trusted publishing, local `twine check`.
- [Engine-only deployment and external IoT pipelines](engine_only_iot) — `--mode engine` vs pandas `RuleRunner`; same YAML on DataFrames.
- [Data model engineering (Brick + 223P MVP)](data_model_engineering) — Engineering UI, JSON round-trip, `s223`/`ofdd` RDF, SPARQL examples, and how that ties to FDD + DB for impact-style analytics.
- [Cloning and porting](cloning_and_porting) — Same tools, any building; checklist for OpenClaw clones on a bench.
- [OpenClaw subscription setup (Codex OAuth)](openclaw_subscription_setup) — ChatGPT subscription path vs API key; stale `openai/...` cleanup.
- [Monitor the fake fault schedule](fake_fault_schedule_monitoring) — Interpret 180°F spikes on the fake BACnet bench.
