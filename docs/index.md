---
title: Home
layout: default
nav_order: 1
permalink: /
---

# Open-FDD

**Open-FDD is a local-first Rust edge platform for building telemetry, semantic modeling, supervisory fault detection, and HVAC analytics.**

Open-FDD is open-source building analytics software for operators, integrators, and engineers who need vendor-neutral fault detection on premises — without sending BACnet traffic or historian data to the public internet.

## What it does

- Collects live data from **BACnet**, **Modbus**, **Haystack**, **JSON API**, and **CSV** imports
- Stores telemetry in an **Apache Arrow / Feather** historian at the edge
- Models sites, equipment, and points with **Project Haystack** semantics
- Runs **DataFusion SQL** rules for supervisory fault detection
- Serves a **React** dashboard for commissioning, plots, and PDF reports
- Exposes a **JWT-protected REST API** and **MCP** tools for AI-assisted engineering workflows

## Who it is for

| Role | Typical use |
|------|-------------|
| **OT / BAS integrators** | Live edge on a LAN or VPN — BACnet/Modbus commissioning, historian, FDD |
| **Energy / RCx engineers** | Offline CSV analytics on a workstation — import, merge, SQL rules, reports |
| **Developers & agents** | API + MCP for scripted commissioning, validation, and documentation |

## Deployment models

### Live OT edge

Run on a Linux edge host (industrial PC, VM, or Raspberry Pi) on the building LAN. Pull the published image, bind-mount `workspace/` for site state, and keep the API on loopback or behind a reverse proxy.

### Offline engineering

Run the same stack in Docker on a laptop. Import vendor CSV exports, build the Haystack model, run SQL FDD rules, and generate reports without live field buses.

{: .important }
Open-FDD is intended for **LAN, VPN, or OT-network deployment**. Do not expose the API directly on the public internet.

## Get started

1. [Quick Start]({{ site.baseurl }}/quick-start/) — GHCR bootstrap, first login, health check
2. [**FDD Rule Cookbook**]({{ site.baseurl }}/rules/cookbook/) — **DataFusion SQL + Pandas** HVAC fault patterns
3. [Architecture]({{ site.baseurl }}/architecture/) — services, data flow, storage
4. [API Reference]({{ site.baseurl }}/api/) — REST route map
5. [MCP & Agents]({{ site.baseurl }}/mcp-agents/) — Cursor / OpenClaw integration
6. [Operations]({{ site.baseurl }}/operations/) — [release channels]({{ site.baseurl }}/operations/release-channels.html), backup, GHCR
7. [Security]({{ site.baseurl }}/operations/security.html) — auth, secrets, BACnet write safety
8. [Documentation site]({{ site.baseurl }}/operations/github-pages.html) — GitHub Pages build (Actions-only)

## Primary image

```text
ghcr.io/bbartling/openfdd-edge-rust:${OPENFDD_IMAGE_TAG:-nightly}
```

See [Release channels]({{ site.baseurl }}/operations/release-channels.html) for `:beta` and `:latest` promotion policy.
