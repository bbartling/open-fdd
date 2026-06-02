---
title: ADR 001 — Core addon serves compiled SPA
nav_order: 5
parent: Getting Started
---

# ADR 001 — Operator dashboard stays in the bridge core addon

**Status:** Accepted  
**Date:** 2026-06-02  
**Context:** Docker-first edge deploy; question whether to split React UI into a separate `openfdd-dashboard` container.

## Decision

Keep the **compiled React SPA** baked into the **`openfdd-bridge` image** and served by FastAPI at runtime (same pattern as Home Assistant Core: one core container with UI + API).

Production always uses **Vite build output** (`workspace/api/static/app/`), never the Vite dev server on edge hosts.

## Rationale

| Factor | Core addon (chosen) | Separate dashboard container |
|--------|---------------------|------------------------------|
| HA OS alignment | Matches HA Core (UI + backend together) | Organizational only; not required for Buildroot/supervisor/OTA |
| Operations | One health check, one loopback upstream via Caddy | Two services + path-based Caddy routing |
| Same-origin | Browser hits `/` and `/api/*` on one upstream | Requires careful ingress split |
| Security | Acceptable with loopback bind + auth on `/api/*` | Slightly smaller API route table; modest gain |
| Release cadence | UI change rebuilds bridge image | Independent UI image updates |

HA-at-scale readiness comes from **supervisor manifest**, **pinned images**, **host ingress (Caddy)**, and **persistent workspace bind-mounts** — not from splitting static file serving.

Future **GPU/Ollama** workloads remain separate addons (`ollama`, `mcp-rag`); they do not depend on where static JS is served.

## Consequences

- `docker/Dockerfile` retains `dashboard` → `bridge` multi-stage build.
- [`supervisor/manifest.yaml`](../../supervisor/manifest.yaml) lists `bridge` as `role: core` (includes SPA).
- Hashed assets under `/assets/*` use long-lived `Cache-Control` (see bridge static mount).
- `index.html` and SPA routes are not long-cached (client routing + deploy updates).

## Deferred: `openfdd-dashboard` addon

Revisit a dedicated nginx static container **only if**:

1. UI releases much faster than bridge API (independent rollouts needed).
2. Bridge image size on ARM edge hardware becomes painful.
3. Supervisor productization requires a visible Dashboard addon in the manifest.
4. Policy requires the API process to expose zero non-API HTTP routes.

If implemented later: nginx container on loopback `:8080`, Caddy routes `/api/*` and `/health` → bridge, all other paths → dashboard; see evaluation notes in project planning docs.

## References

- [HA OS alignment](haos_alignment.md)
- [Operator dashboard](../howto/operator_dashboard.md)
- [Edge deploy (Docker)](../edge_deploy_docker.md)
- Build: [`docker/Dockerfile`](../../docker/Dockerfile), [`scripts/build_operator_dashboard.sh`](../../scripts/build_operator_dashboard.sh)
- Serve: [`workspace/api/openfdd_bridge/main.py`](../../workspace/api/openfdd_bridge/main.py)
