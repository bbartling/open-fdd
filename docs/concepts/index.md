---
title: Concepts
nav_order: 9
has_children: true
---

# Concepts

Conceptual guides and worked examples for how Open-FDD fits into larger workflows.

| Page | Description |
|------|-------------|
| [Cloud export example](cloud_export) | How a cloud vendor or MSI can pull fault and timeseries data from the Open-FDD API and send it to their cloud for deeper insights. Uses the `examples/cloud_export` script as a starting point. |
| [Context and recordkeeping](context_and_recordkeeping) | Durable context policy: what belongs in versioned docs vs private local memory. |
| [Operational states](operational_states) | Mode-aware interpretation between test bench and live HVAC environments. |
| [Big picture gaps and product suggestions](big_picture_gaps) | Higher-level product and workflow gaps observed in the field. |
| [VOLTTRON gateway, FastAPI, and data-model sync](volttron_gateway_and_sync) | VOLTTRON on the edge for BACnet and historian time series; FastAPI keeps graph, SPARQL, and modeling; cron versus API-owned sync. |
| [Target vision — Brick on VOLTTRON, Central, no FastAPI](brick_volttron_central_target) | Long-range architecture: Brick as canonical model, layer across VOLTTRON or Central, retiring the standalone FastAPI service once replacements exist. |

See also [Behind the firewall; cloud export is vendor-led](../index#behind-the-firewall-cloud-export-is-vendor-led) on the docs home.
