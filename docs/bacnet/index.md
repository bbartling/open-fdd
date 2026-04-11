---
title: Edge field buses (VOLTTRON)
nav_order: 6
has_children: false
---

# Edge field buses (VOLTTRON)

**Open-FDD does not implement BACnet, Modbus, or other field buses.** Those protocols run **only inside each building’s VOLTTRON** deployment (platform driver, BACnet proxy, Modbus devices, etc., per **your** VOLTTRON configuration). Telemetry reaches Open-FDD through **SQL** (historian, ETL) and **topic identity** aligned with `points` / `external_id`—not through this repository hosting OT traffic.

**Message bus:** VOLTTRON’s default inter-platform path is **ZeroMQ (ZMQ)** VIP and pub/sub as described in upstream docs. **RabbitMQ is not** part of Open-FDD’s reference architecture; if you add AMQP for a custom integration, treat it as **out of scope** for these docs.

**Where to read next**

- **[Site VOLTTRON and the data plane (ZMQ)](../concepts/site_volttron_data_plane)** — canonical on-prem vs cloud + ZMQ framing.
- **[VOLTTRON gateway, FastAPI, and data-model sync](../concepts/volttron_gateway_and_sync)** — SQL, optional API, Central.
- **[VOLTTRON Central and AFDD parity](../howto/volttron_central_and_parity)** — bootstrap and historian colocation.

**Legacy material (removed from navigation)**  

Older releases documented **diy-bacnet-server**, **bacnet-scraper**, and FastAPI **JSON-RPC proxy** flows. Those containers are **not** started by default Compose anymore. Historical detail lives only in **`afdd_stack/legacy/README.md`** and in **git history** for deleted pages (`overview`, `fault_verification`, `graph_context`, `gateway_rpc_contract`). Do not plan new deployments against that path unless you maintain a **private fork**.

Upstream field stack: [VOLTTRON readthedocs](https://volttron.readthedocs.io/).
