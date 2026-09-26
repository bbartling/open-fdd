---
title: Home
layout: default
nav_order: 1
permalink: /
---

# Open-FDD

**Open-FDD is a local-first Rust edge platform for building telemetry, semantic modeling, supervisory fault detection, and HVAC analytics.**

Open-source building analytics for operators, integrators, and engineers who need vendor-neutral fault detection on premises — without sending BACnet traffic or historian data to the public internet.

## Field to cloud

Secure HVAC data collection, fault detection, and portfolio access for mechanical systems integrators.

<figure class="architecture-diagram">
  <img
    src="{{ site.baseurl }}/assets/open-fdd-field-to-cloud.png"
    alt="Open-FDD field-to-cloud architecture — BACnet/Modbus at the building, MQTTS to the hub, HTTPS/JWT for office and AI agents"
    width="1672"
    height="941"
    loading="eager"
    decoding="async"
  />
</figure>

| Path | Protocol |
|------|----------|
| Building OT → field edge | BACnet / Modbus (+ Haystack model) |
| Field → hub | MQTTS |
| Office browser | HTTPS → React SPA |
| AI / automation agents | JWT REST (+ optional MCP) |
| Weather assist | HTTPS Open-Meteo fetch at the edge |
| Offline import | CSV / JSON package |

## What it does

- Collects live data from **BACnet**, **Modbus**, **Haystack**, **JSON API**, and **CSV** imports
- Stores telemetry in an **Apache Parquet** historian (Arrow/DataFusion)
- Models sites with **Project Haystack** semantics
- Runs **DataFusion SQL** rules (`sql_rules/` registry)
- Serves a **React** SPA — Overview, FDD, RCx, findings against central `/api` only
- Exposes **JWT REST** and optional **MCP** for engineering agents

Pandas recipes stay in the [Pandas cookbook](rules/cookbook/pandas-cookbook.html) for notebooks / PyPI. Production FDD is DataFusion SQL only.

## Who it is for

| Role | Typical use |
|------|-------------|
| **OT / BAS integrators** | Live edge on LAN/VPN — BACnet/Modbus, historian, FDD |
| **Energy / RCx engineers** | CSV analytics on a workstation — import, SQL rules, reports |
| **Developers & agents** | API + MCP for commissioning and validation |

## Deployment models

### Live OT edge

Linux edge host on the building LAN. Pull GHCR images, bind-mount `workspace/`, keep API on loopback or behind a reverse proxy.

### Offline engineering

Same stack in Docker on a laptop. Import CSVs, map Haystack roles, run SQL FDD — no live field bus required.

{: .important }
Intended for **LAN, VPN, or OT-network** deployment. Do not expose the API on the public internet without an independent security review.

## Get started

1. [Quick Start]({{ site.baseurl }}/quick-start/) — Compose + Railway + GHCR
2. [**Rule Cookbook**]({{ site.baseurl }}/rules/) — DataFusion SQL + Pandas patterns (+ [anomaly screening]({{ site.baseurl }}/rules/sql-anomaly-detection.html))
3. [Haystack modeling]({{ site.baseurl }}/modeling/) — packages and SQL roles
4. [Architecture]({{ site.baseurl }}/architecture/) — services and data flow
5. [API & Security]({{ site.baseurl }}/api/) — REST + vulnerability reporting
6. [MCP & Agents]({{ site.baseurl }}/mcp-agents/) — Cursor / OpenClaw
7. [PyPI agent tools]({{ site.baseurl }}/ecm/) — `open-fdd-anomaly report` from mapped roles (local CSV, Railway or self-hosted Open-FDD, or a future vendor API) plus ECM workbooks (`pip install open-fdd`)
8. [Web App]({{ site.baseurl }}/web-app/) — SPA routes and RCx examples

## Stack images

```text
ghcr.io/bbartling/openfdd-central:${OPENFDD_IMAGE_TAG:-nightly}
ghcr.io/bbartling/openfdd-web:${OPENFDD_IMAGE_TAG:-nightly}
ghcr.io/bbartling/openfdd-fieldbus:${OPENFDD_IMAGE_TAG:-nightly}
ghcr.io/bbartling/openfdd-mqtt:${OPENFDD_IMAGE_TAG:-nightly}
ghcr.io/bbartling/openfdd-mcp:${OPENFDD_IMAGE_TAG:-nightly}
```

See [Build recipes]({{ site.baseurl }}/operations/build-recipes.html) and [Release channels]({{ site.baseurl }}/operations/release-channels.html).
