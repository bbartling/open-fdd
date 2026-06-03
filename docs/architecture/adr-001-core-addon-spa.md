---
title: ADR 001 — Core addon serves compiled SPA
nav_order: 5
parent: Getting Started
---

# ADR 001 — Core addon serves compiled SPA

**Status:** Accepted

## Context

The operator UI is a Vite/React SPA. We could split a static `openfdd-dashboard` image or serve the SPA from Caddy on the host.

## Decision

Keep the **compiled React SPA** baked into the **`openfdd-bridge` image** and served by FastAPI at runtime (one container: UI + API).

## Consequences

| Pro | Con |
|-----|-----|
| Single image to version and health-check | UI rebuild requires bridge image rebuild |
| Same auth/CORS/session as API | Larger bridge image |
| Matches current Acme/bensserver deploy | Separate dashboard image deferred |

## Alternatives considered

- **Sidecar static image** — extra compose service; only worth it if UI release cadence diverges from API.
- **Host Caddy `file_server`** — splits cache headers and deploy paths.

## References

- [Edge stack layout](edge_stack)
- `workspace/api/openfdd_bridge/main.py` — SPA fallback routes
- `scripts/build_operator_dashboard.sh`
