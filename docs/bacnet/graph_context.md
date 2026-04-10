---
title: BACnet graph context
parent: BACnet
nav_order: 2
---

# BACnet graph context

This document captures BACnet-specific context the **OpenClaw lab** and operators should preserve for future clones, labs, and researchers.

The goal is simple: **do not rely on tribal knowledge**.

## Why this context matters

In live HVAC monitoring, the Open-FDD knowledge graph is not just metadata. It is the bridge between:

- BACnet devices and point addressing
- semantic equipment typing (AHU, VAV, zone, plant, meter, etc.)
- rule applicability
- FDD algorithm selection
- future optimization logic

If we know, from the graph:

- which BACnet device a point belongs to
- which object identifier is being scraped
- which Brick/equipment type the point belongs to
- which Open-FDD rule inputs are mapped

then we know much more than "the point exists". We know which fault rules should fire, and later we can know which optimization or supervisory logic should apply.

## What must be discoverable from the graph

For BACnet-backed verification, the test harness should always be able to retrieve or verify:

1. **BACnet device inventory** — device instance, device address, device object presence in the graph
2. **BACnet point addressing** — object identifier, point label / object-name alignment, point-to-device membership
3. **Equipment semantic context** — AHU / VAV / zone / plant / building associations, Brick class of the point, whether the point is marked for polling
4. **Rule relevance context** — which YAML fault rules are active, what `rule_input` mappings exist for the point/equipment, what rolling-window parameters matter for that rule
5. **Operational intent** — whether the point is used for FDD only, useful for future optimization / supervisory control, operator-facing or only diagnostic

## Live system interpretation

In a future live deployment, this BACnet graph context should support three increasingly valuable questions:

### 1. What is connected?

- Which BACnet devices exist?
- Which points are actually mapped?
- Which points are being polled?

### 2. What kind of HVAC system is this?

- Is the equipment an AHU, VAV, boiler, chiller, plant, or meter?
- What topology relationships exist?
- Which points matter for diagnostics vs operations?

### 3. What analysis should apply?

- Which FDD rules should run?
- Which optimization or supervisory algorithms are sensible here?
- Which results are expected if the fake BACnet devices deliberately enter a fault state?

This is the beginning of a machine-readable engineering context, not just a UI convenience.

## SPARQL assets in the repo

Relevant reusable queries live under [`openclaw/bench/sparql/README.md`](https://github.com/bbartling/open-fdd/tree/main/afdd_stack/openclaw/bench/sparql/README.md), especially:

- `04_bacnet_devices.sparql`
- `08_bacnet_telemetry_points.sparql`
- `05_brick_rule_mapping.sparql`
- `10_ahus.sparql`
- `13_vav_boxes.sparql`
- `19_hvac_equipment.sparql`
- `21_points.sparql`

## BACnet telemetry baseline query

`openclaw/bench/sparql/08_bacnet_telemetry_points.sparql` returns:

- `point_label`
- `brick_class`
- `unit`
- `device_instance`
- `device_address`
- `object_identifier`

That is a strong starting point for proving that BACnet addressing is present in the graph and matched to polling points.

## Backend SPARQL and auth

Graph validation requires `POST /data-model/sparql` with a valid `OFDD_API_KEY` when API auth is enabled. Load the same secret the stack uses (`stack/.env`) in the shell or agent context that runs overnight checks.

Some backends return a simplified shape `{"bindings": [...]}` rather than strict SPARQL JSON `{"results": {"bindings": [...]}}`. Test tooling should accept both.

## BACnet scraper / DIY gateway context

The BACnet scraper gateway OpenAPI is typically at **http://localhost:8080** (Swagger `/docs`). Notable JSON-RPC capabilities include:

- `client_whois_range`
- `client_point_discovery`
- `client_read_property`
- `client_read_multiple`
- `client_supervisory_logic_checks`
- `client_read_point_priority_array`

The bench can validate not only that Open-FDD has graph references, but also that the BACnet-side source system is queryable for independent verification.

## Engineering direction

Evolve toward a formal verification chain:

1. fake BACnet device emits deterministic fault pattern
2. BACnet gateway can independently read that device/point state
3. Open-FDD graph confirms the point is modeled and addressable
4. Open-FDD scrape path lands the telemetry
5. active YAML rules and rolling windows imply a specific fault expectation
6. Open-FDD fault APIs/UI confirm the result

That chain is the real standard for trustworthy FDD validation.

## Where this context is saved

This page lives under **docs/bacnet/** so humans cloning the repo can find it immediately, review it, and extend it without asking the original authors what was "meant."
