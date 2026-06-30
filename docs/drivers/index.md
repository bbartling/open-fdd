---
title: Drivers
layout: default
nav_order: 5
has_children: true
permalink: /drivers/
---

# Drivers

Open-FDD supports live field protocols and CSV import. Each driver exposes a tree in the dashboard and REST endpoints under `/api/{driver}/*`.

| Driver | Guide |
|--------|-------|
| [BACnet](bacnet.html) | IP discover, poll, overrides |
| [Modbus](modbus.html) | TCP register reads |
| [Haystack](haystack.html) | Remote Haystack server client |
| [JSON API](json-api.html) | HTTP polling sources |
| [CSV](csv.html) | Offline / engineering imports |

Unified tree: `GET /api/drivers/tree`
