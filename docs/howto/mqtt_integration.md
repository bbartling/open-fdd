---
title: MQTT integration (optional)
parent: How-to guides
nav_order: 3
---

# MQTT integration (optional)

**VOLTTRON’s default platform bus is ZeroMQ (ZMQ)** VIP and pub/sub — **not** MQTT and **not** RabbitMQ. Open-F-DD documentation assumes **site VOLTTRON** handles BACnet/Modbus and historians write **SQL**. See **[Site VOLTTRON and the data plane (ZMQ)](../concepts/site_volttron_data_plane)**.

This page covers an **optional** **Mosquitto** broker from `afdd_stack/stack/docker-compose.yml` when you enable the **`mosquitto`** / MQTT-related **compose profile**. Use it only if **you** add MQTT clients (Home Assistant, custom bridges, cloud shadow topics, etc.). It is **not** required for FDD, for the React UI, or for VOLTTRON ingest.

---

## What you can do

1. **Start Mosquitto** from `afdd_stack/stack/` using the compose file’s **MQTT profile** (see comments in `docker-compose.yml` and [Quick reference](quick_reference)).
2. **Publish or subscribe** from your own services at the edge or in the data center. Keep ACLs and TLS aligned with your security model.
3. **Do not confuse** this broker with **VOLTTRON’s internal message bus** — that remains **ZMQ** per upstream VOLTTRON docs.

---

## Related docs

- [Getting started](../getting_started) — bootstrap and compose
- [Quick reference](quick_reference) — ports and checks
- [Edge field buses (VOLTTRON)](../bacnet/) — field protocols live in VOLTTRON, not in Open-F-DD
