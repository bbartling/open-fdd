---
title: Open-FDD integrity sweep
parent: Operations
nav_order: 1
---

# Open-FDD integrity sweep

The integrity sweep is a recurring, operator-style check that verifies Open-FDD platform health, graph integrity, and representative telemetry trustworthiness.

## Cadence

- Daytime recurring sweep target: every 20 minutes.
- Overnight window (`18:00-06:00` local): reduce duplicate low-signal chatter and prioritize richer overnight review artifacts.

## Source-of-truth order

1. Live backend data model (`/data-model/check`, `/data-model/sparql`, `/data-model/export`)
2. Current launch/auth/runtime context
3. Repo docs and playbooks

## Sweep checklist

1. Verify authenticated backend reachability.
2. Validate data model integrity and SPARQL query path.
3. Discover representative points from the current model (not hard-coded point lists).
4. Validate representative BACnet reads for model-derived devices/points.
5. Classify failures cleanly.

## Failure classes

- `auth_config_drift`
- `graph_model_drift`
- `bacnet_device_state_drift`
- `testbench_limitation`
- `likely_openfdd_product_behavior`
- `likely_ui_api_parity_bug`

## Mode detection

- `TEST_BENCH`: fake device semantics and deterministic schedule artifacts present.
- `LIVE_HVAC`: occupied-building semantics and live operational telemetry.

The sweep should always report mode + basis, then reason accordingly.

