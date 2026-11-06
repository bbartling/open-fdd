---
title: ADR — Open-FDD as a Normal Framework plugin
parent: Architecture
nav_order: 1
---

> Historical record. `archive/central-v4/` was later removed entirely; the 4.x line is tag `v4.0.11-central`.

# ADR-014 — Open-FDD as a Normal Framework plugin

- **Status:** Proposed (2026-11-05), owner decision; implemented in slices on `nf-plugin/*` branches
- **Supersedes when accepted:** the "central owns ingest + historian" parts of ADR-010 (Timescale hard cutover, in the 4.x tag) and ADR-011 (in the 4.x tag); the `services/central` delivery in ADR-013 (in the 4.x tag); the "one canonical telemetry writer" clause of the [DATA_CONTRACT storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)
- **Keeps:** SQL as the single source of FDD math (the `sql/fdd/postgres/rules` pack, `registry.yaml`, `role_map.json`); Timescale/PostgreSQL as the long-term historian; strict CSP static UI with vendored ECharts; no hard-coded sites, equipment or points; no BACnet writes without human approval

## Context

Open-FDD 4.0 runs beside Normal Framework (NF): `openfdd-central` (Rust) pulls NF over the portal
API or gRPC every hour into its own Timescale `sample` table, runs the SQL FDD pack, and serves the
static UI. That is a second historian, a second model store and a second auth system next to NF,
which already:

- polls the field bus and keeps every point, its Haystack tags and its latest value in Redis, plus a
  7-day RedisTimeSeries history, with NF-side resampling (`/api/v1/point/data?window=…&method=…`);
- pushes live values (`PointManager.ObserveDataUpdates`, gRPC server stream; HTTP via Envoy as
  `/api/v1/point/updates/data`);
- writes all point data and metadata into Postgres/TimescaleDB through its northbound integration
  (`instances`, `points`, `data` tables + per-layer views);
- hosts apps: static files at `/api/v1/apps/static/<app>/` and scheduled Node.js hooks with an
  `sdk.http` client and global-variable points;
- provides remote access, login and daily config backups through Normal Online.

The NF Bench Viz / Open-FDD Edge work (NF_NOTES bench, 2026-10-31 → 11-05) proved the NF-native
path on a Raspberry Pi: tag-driven pages, NF-resampled charts, live push, Haystack RDF export,
strict CSP, Caddy front door.

## Decision

Open-FDD ships as **one NF application** (`open-fdd`) instead of a separate stack.

1. **UI (`nf-app/static/`)** — the Open-FDD UI is an NF static app. It reads NF's API directly
   (same origin, NF/portal auth), never a parallel Open-FDD API. Base: the Open-FDD Edge pages
   (tokens, `openfdd-ui-theme`, strict CSP, vendored ECharts); the FDD / RCx / analytics tabs of
   central's static UI are ported onto NF data.
2. **Two profiles, one app:**
   - **edge-lite** (small boxes, e.g. Raspberry Pi): no extra database. Hooks evaluate rules on
     NF's resampled history and write fault results back to NF as points.
   - **full** (production edge, ≥ 4 GB RAM): NF's northbound TimescaleDB integration is the
     historian; a hook runs the SQL FDD pack against it and writes results to an `openfdd` schema
     in the same database plus fault points in NF.
3. **FDD math stays SQL.** One rule pack serves both profiles (full: TimescaleDB; edge-lite: an
   embedded PostgreSQL engine in the hook, evaluated against NF history, if the bench proves it
   fits; otherwise edge-lite ships a declared subset). No second hand-written rule implementation.
4. **Model = NF's Haystack model.** Rule inputs bind through `role_map.json` to Haystack
   classes/markers on NF points (`equipRef`, `class`, `markers`), not a separate `point_map`.
   The RDF export (Turtle, validated with Oxigraph) carries **external time-series references**
   from each point to its NF history endpoint and, in full profile, its TimescaleDB rows.
5. **Front door:** Caddy in front of NF (plain HTTP or self-signed TLS), app pages open, console
   and writes behind auth; remote access through the Normal Online portal.
6. **Deploy:** the existing manifest tool (`scripts/nf/hooks/nf_app_sync.py`) or the NF MCP pushes
   files and hooks; the repo is the source of truth.
7. **Archive:** once the plugin reaches parity, `services/central`, the ingest/provider crates and
   the portal compose move to `archive/central-v4/` (with `git mv`, README, restore notes), following
   `archive/README.md`.

## Consequences

- One writer remains: NF writes telemetry (Redis, and TimescaleDB in full profile); Open-FDD only
  writes FDD results. Open-FDD stops copying telemetry.
- Auth, remote access, backups and licensing come from NF / Normal Online; Open-FDD JWT/RBAC retires.
- Data depth: edge-lite is bound by NF's 7-day Redis retention; long trends need the full profile.
- Rust product code shrinks to what has no NF equivalent (none planned for slice 1).
- CI moves from Rust gates to: rule-pack SQL tests, node tests for the app, RDF validation, a
  manifest/deploy dry run, and live bench smoke.
- Open questions tracked in [the migration plan](../migration/nf-plugin/PLAN.html):
  embedded Postgres memory on the Pi, hook runtime limits (npm deps, run time), NF Timescale
  schema details, and portal auth for app API calls.
