---
title: Site VOLTTRON and the data plane (ZMQ)
parent: Concepts
nav_order: 1
---

# Site VOLTTRON and the data plane (ZMQ)

This page is the **default architecture** for how telemetry reaches Open-F-DD: **inside each building**, one or more **VOLTTRON** instances own the field layer. The Open-F-DD application tier (Postgres, optional FastAPI + React, FDD jobs or agents) **does not speak BACnet, Modbus, or other OT buses** and does not replace the VOLTTRON message bus.

Whether you run Open-F-DD **on-prem** (VM or appliance in the plant) or **in a cloud VPC**, the same rule applies: **field protocols and drivers live on site in VOLTTRON**; the app tier consumes **already-normalized** time series and metadata.

---

## What runs where

| Location | Responsibility |
|----------|------------------|
| **Building / site LAN** | **VOLTTRON 9**: platform driver, BACnet proxy, Modbus or other drivers as *you* configure upstream—not in this repo. **Inter-agent traffic** uses the VOLTTRON **VIP** path over **ZeroMQ (ZMQ)**. Pub/sub between agents uses the platform message bus VOLTTRON documents for your release. **RabbitMQ is not** part of this project’s default story; do not assume a separate AMQP bus for core ingest. |
| **Same site or central host** | **SQL historian** (or equivalent writers) persisting topics into **Postgres / Timescale** with `tables_def` aligned to your deployment. Open-F-DD’s **SQL schema** (`sites`, `equipment`, `points`, `timeseries_readings`, faults, …) is the integration surface for rules and UI. |
| **App tier (on-prem or cloud)** | **Optional** FastAPI + React for Brick CRUD, SPARQL, export/import; **FDD** via `run_fdd_loop()` or agents reading the **same DSN**. No requirement to colocate the app tier with VOLTTRON; **the database** (and secure networking) is the contract. |

---

## How data actually flows

1. **Devices** → VOLTTRON drivers / proxies on the **OT LAN** (BACnet, Modbus, etc. **only inside VOLTTRON**, per your VOLTTRON config—not Open-F-DD code).
2. **Agents** → publish/subscribe on the **ZMQ-backed** VOLTTRON bus; historians **archive** selected topics to SQL.
3. **Open-F-DD** → reads **Postgres** (and optional API-driven graph work). **`openfdd_stack.volttron_bridge`** and **`external_id` / point keys** align historian rows with Brick-oriented metadata.

If something is not in **SQL** (or not mapped into Open-F-DD tables), the **React** app and **FDD rules** cannot see it—**wire ingest is VOLTTRON’s job**.

---

## Implications for docs and APIs

- **REST `/bacnet/*` helpers** in the optional FastAPI app are **legacy / lab** paths for proxying an external gateway when *you* choose to run one; they are **not** the default product surface and **do not** mean Open-F-DD hosts BACnet/IP. Prefer **VOLTTRON** documentation for discovery, writes, and scheduling on the bus.
- **`bacnet_device_id` / `object_identifier`** on points may still appear in the **data model** (imports, migration, RDF) as **opaque metadata**—not as proof that **this service** is polling BACnet.

---

## See also

- [VOLTTRON gateway, FastAPI, and data-model sync](volttron_gateway_and_sync) — layering Central, SQL, and optional API.
- [VOLTTRON Central and AFDD parity (monorepo)](../howto/volttron_central_and_parity) — bootstrap and multi-site patterns.
- [`afdd_stack/legacy/README.md`](https://github.com/bbartling/open-fdd/blob/main/afdd_stack/legacy/README.md) — removed Docker services (BACnet scraper, diy-bacnet container, …) for historical reference only.

Upstream: [VOLTTRON documentation](https://volttron.readthedocs.io/), [SQL Historian](https://volttron.readthedocs.io/en/stable/volttron-api/services/SQLHistorian/README.html).
