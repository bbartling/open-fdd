---
title: Architecture
nav_order: 13
has_children: true
---

# Architecture

```mermaid
flowchart LR
  BAS[BACnet / Modbus / Niagara] --> NF[(Normal Framework<br/>points, history, Haystack model)]
  NF -->|point/query, point/data| UI[Open-FDD UI<br/>nf-app/static]
  NF -->|hourly hook| FDD[FDD hook<br/>SQL pack in SQLite-WASM or PGlite]
  FDD -->|fault points| NF
  NF -->|optional BACnet AVs| BAS
  Portal[Normal Online portal] --> UI
```

NF owns the field bus, the point model, history, auth, remote access and config backups. Open-FDD adds the UI, the
FDD hook (SQL rules in an embedded engine), the weather hook and a SPARQL hook. The decision and its consequences
are in [ADR-014](architecture/adr-014-open-fdd-as-nf-plugin.html); what the app uses from NF's platform is in
[NF features](migration/nf-plugin/NF_FEATURES.html).

## Three pictures of the edge box

**1. BACnet polling to Redis.** NF reads each point on its poll period and keeps the newest value plus a rolling
7-day history in Redis (RAM, snapshotted to disk now and then), so API answers are immediate. NF's cloud config
backup does not include this history.

```mermaid
flowchart LR
  BAC[HVAC controller] -- BACnet read --> POLL[NF poller<br/>each point on its period]
  POLL --> LATEST[latest value per point]
  POLL --> HIST[history, last 7 days]
  LATEST -.-> DISK[(snapshot to disk)]
  HIST -.-> DISK
```

**2. Getting the data out: on site vs. over the internet.** Both paths reach the same NF API and data. The NF box
dials out to the Normal Online portal, so no inbound ports are opened on the building firewall.

```mermaid
flowchart LR
  LAN[On site: browser or script] --> CADDY[Caddy front door] --> NF[Normal Framework]
  REMOTE[Anywhere: browser, script, NF MCP] --> PORTAL[Normal Online portal<br/>login or API key] --> TUNNEL[tunnel dialed out by NF] --> NF
```

**3. What the front door does.** The dashboard and the read-only calls it makes are open; the NF console, app
configuration and every write need the password. NF itself listens on loopback only. Setup:
[Front door](operations/nf/front-door-caddy.html).

```mermaid
flowchart LR
  REQ[Request from the LAN] --> CADDY{Caddy}
  CADDY -- dashboard + the data it reads --> OPEN[open, no login] --> NF[Normal Framework]
  CADDY -- NF settings, changes, writes --> LOCK[password required] --> NF
```

Operations runbooks for the box (editions, upgrade, tagging, BACnet validation, gotchas):
[NF operations](operations/nf/index.html).

## Principles

- **One source of FDD math**: `sql/fdd` builds the Postgres pack, and the SQLite pack is generated and checked for parity.
- **Nothing site-specific in code**: everything is discovered from NF's model.
- **SI math, display on top** ([Units](units.html)).
- **Light on the box**: NF resamples history; small boxes use the SQLite engine; heavy work never runs on the box.

## Migration records

Notes from the move from the 4.x central stack, kept for reference:
[Plan](migration/nf-plugin/PLAN.html), [Status](migration/nf-plugin/STATUS.html),
[NF features](migration/nf-plugin/NF_FEATURES.html), [Removed in 5.0](migration/nf-plugin/ARCHIVE_MAP.html).
