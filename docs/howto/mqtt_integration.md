---
title: MQTT integration (optional)
parent: How-to Guides
nav_order: 3
---

# MQTT integration (optional) — Open-FDD + diy-bacnet-server

Open-FDD does **not** require MQTT for core FDD, BACnet scraping, or the web UI. MQTT is **optional** and aimed at **future** edge/automation patterns and **generic** brokers (typically **Mosquitto**), not a specific cloud vendor.

## What the stack can do today

1. **Mosquitto (compose profile)**  
   Run `./scripts/bootstrap.sh --with-mqtt-bridge` to start a broker on **`localhost:1883`** (see [Getting started](../getting_started) and [Quick reference](quick_reference)).

2. **BACnet2MQTT (diy-bacnet-server)**  
   When **`BACNET2MQTT_ENABLED=true`** and **`MQTT_BROKER_URL`** point at that broker, **diy-bacnet-server** publishes per-point state under **`MQTT_BASE_TOPIC`** (default `bacnet2mqtt`) and can publish Home Assistant discovery under **`HA_DISCOVERY_TOPIC`**. This is documented in the **[diy-bacnet-server repo](https://github.com/bbartling/diy-bacnet-server)** (README and `HOME_ASSISTANT_MQTT_CHEATSHEET.md`).

3. **MQTT RPC gateway (experimental, diy-bacnet-server)**  
   When **`MQTT_RPC_GATEWAY_ENABLED=true`**, the same gateway process can subscribe to **`{MQTT_RPC_TOPIC_PREFIX}/cmd`** and publish structured acks on **`.../ack`**, using the **same method names** as HTTP JSON-RPC (`server_hello`, `client_whois_range`, `client_read_property`, etc.). Optional **telemetry** topics advertise supported methods and periodic metadata.  
   Configure via **`stack/.env`** (variables are passed through **`stack/docker-compose.yml`** to the **bacnet-server** service). See the upstream **[MQTT RPC gateway](https://github.com/bbartling/diy-bacnet-server/blob/master/README.md#mqtt-rpc-gateway-optional-experimental)** section for topic layout and security notes (TLS, ACLs).

## Open-FDD product scope

- Core data path remains **HTTP JSON-RPC** from the **BACnet scraper** and API to **diy-bacnet-server**.
- MQTT features are **additive**: monitoring via BACnet2MQTT, command/ack experimentation via the RPC gateway, without replacing the database-backed scraper or auth model (**`OFDD_BACNET_SERVER_API_KEY`** → **`BACNET_RPC_API_KEY`** on the gateway).

## Related docs

- [Getting started](../getting_started) — `--with-mqtt-bridge`
- [Quick reference](quick_reference) — broker port and status checks
- [BACnet overview](../bacnet/overview) — gateway and scraper roles
