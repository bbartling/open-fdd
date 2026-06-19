---
title: Dashboard routes
parent: Appendix
nav_order: 2
---

# Dashboard routes

Single-page app served by **openfdd-bridge** at `/` (production: Caddy on `:80`). All paths below are relative to the site root unless noted.

**Auth:** Routes under `RequireAuth` need a valid JWT (login at `/login`). Role gates are enforced on API calls from each tab.

---

## Public

| Path | Page | Notes |
|------|------|-------|
| `/login` | Login | JWT session; redirects to `/` when authenticated |

---

## Main workspace (authenticated)

| Path | Tab / page | Purpose |
|------|------------|---------|
| `/` | Home | Overview, fault analytics, equipment, model health (hash sections) |
| `/rule-lab` | Rule Lab | Author, lint, preview, compare PyArrow vs SQL rules |
| `/model` | Data model | BRICK model, point bindings, FDD assignments |
| `/plot` | Plot | Timeseries plot from feather historian |
| `/bacnet` | BACnet | Commission UI, inventory, driver tree |
| `/modbus` | Modbus | Modbus driver (when enabled) |
| `/niagara` | Niagara | baskStream connector stations & poll |
| `/json-api` | JSON API | External JSON ingest driver |
| `/agent` | Building agent | Ollama / agent check-in |
| `/host` | Host stats | Container and host metrics |

---

## Analytics & RCx

| Path | Destination | Notes |
|------|-------------|-------|
| `/analytics` | `/#overview` | Redirect to home overview |
| `/analytics/faults` | `/#fault-analytics` | Fault analytics hash |
| `/analytics/equipment` | `/#equipment` | Equipment hash |
| `/analytics/health` | `/#model-health` | Model health hash |
| `/analytics/rcx` | RCx report builder | Generate, list, preview, delete DOCX reports |

---

## Legacy redirects

| Path | Redirects to |
|------|----------------|
| `/algorithms` | `/` |
| `/data-model` | `/model` |
| `/fdd-assignments` | `/model` |
| `/fdd` | `/model` |
| `/faults` | `/#fault-analytics` |

---

## Home hash sections

The home page uses URL fragments for deep links:

| Hash | Section |
|------|---------|
| `#overview` | Dashboard overview |
| `#fault-analytics` | Fault tree and analytics |
| `#equipment` | Equipment rollup |
| `#model-health` | Model / data health |

---

## Static assets

| Path | Content |
|------|---------|
| `/assets/*` | Built dashboard JS/CSS (Vite) |
| `/docs`, `/redoc` | OpenAPI (bridge process, not SPA) |

API calls from the dashboard use paths documented in [REST API reference]({{ "/appendix/bridge_api/" | relative_url }}).
