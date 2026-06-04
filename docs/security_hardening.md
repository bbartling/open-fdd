# Operator Bridge security hardening

The Open-FDD bridge and React dashboard run on BACnet/OT edge hosts. Default posture is **fail closed**: authentication required on any non-loopback bind, BACnet writes off, Rule Lab execution bounded, minimal error detail to browsers.

## Safe deployment modes

| Mode | `OFDD_BRIDGE_HOST` | Auth | Typical use |
|------|-------------------|------|-------------|
| **Localhost dev** | `127.0.0.1` | `OFDD_AUTH_DISABLED=1` optional | Single-machine `uvicorn` / compose on laptop |
| **LAN demo (insecure)** | `0.0.0.0` or `::` | `OFDD_AUTH_DISABLED=1` **and** `OFDD_INSECURE_LAN_DEV=1` (or `OFDD_ALLOW_PUBLIC_UNAUTHENTICATED_DEV=1`) | Commissioning lab on trusted LAN only — not production |
| **Edge / production** | `0.0.0.0` or `::` (behind Caddy) | `OFDD_AUTH_SECRET` + role passwords **required** | BACnet edge VM, OT network |

Startup **fails** if the bridge listens on `0.0.0.0` / `::` without configured credentials and without the explicit insecure LAN dev flags above.

## Required for LAN / edge production

| Variable | Purpose |
|----------|---------|
| `OFDD_AUTH_SECRET` | HMAC signing key (32+ characters) |
| `OFDD_OPERATOR_USER` / `OFDD_OPERATOR_PASSWORD` | Read-mostly operator role |
| `OFDD_INTEGRATOR_USER` / `OFDD_INTEGRATOR_PASSWORD` | Rule Lab, model import, BACnet commission |
| `OFDD_AGENT_USER` / `OFDD_AGENT_PASSWORD` | Agent tools and app-edit gates |

Set in `workspace/auth.env.local` (gitignored). Caddy should reverse-proxy to the bridge; do not expose port 8765 to the internet without TLS and auth.

## Dev-only (localhost)

| Variable | Purpose |
|----------|---------|
| `OFDD_AUTH_DISABLED=1` | Skip Bearer tokens when `OFDD_BRIDGE_HOST` is loopback (`127.0.0.1`, `localhost`, `::1`) |
| `OFDD_BRIDGE_HOST=127.0.0.1` | Recommended for local `uvicorn` / compose on one machine |

## Dev-only (insecure LAN — lab)

| Variable | Purpose |
|----------|---------|
| `OFDD_INSECURE_LAN_DEV=1` | Allows `OFDD_AUTH_DISABLED` on `0.0.0.0` / `::` bind |
| `OFDD_ALLOW_PUBLIC_UNAUTHENTICATED_DEV=1` | Alias for `OFDD_INSECURE_LAN_DEV` (extra explicit name) |

Both insecure flags require `OFDD_AUTH_DISABLED=1`. Do not set on field/production edges.

## Optional strictness

| Variable | Purpose |
|----------|---------|
| `OFDD_AUTH_STRICT_STARTUP=1` | Also **fail startup** when auth is missing on a non-public bind (e.g. single NIC IP) |

## CORS

| Variable | Purpose |
|----------|---------|
| `OFDD_CORS_ORIGINS` | Comma-separated browser origins (e.g. `http://192.168.1.10:5173`) |
| `OFDD_CORS_ALLOW_PRIVATE_LAN=1` | Opt-in: add detected LAN IP origins (not implied by `0.0.0.0` bind) |

## BACnet writes

| Variable | Purpose |
|----------|---------|
| `OFDD_ENABLE_BACNET_WRITE=1` | Enable `POST /api/bacnet/write` (default **off**) |

Optional allowlist: `workspace/bacnet/write_allowlist.json` with `device_instances` and/or `object_identifiers`.

## Public vs authenticated diagnostics

| Endpoint | Auth | Content |
|----------|------|---------|
| `GET /health` | None | Liveness only: `ok`, `service`, `version`, `auth_required` |
| `GET /health/stack` | Bearer (any role) | Stack traffic-light; service `url` / `bacnet_bind` only with `OFDD_DEBUG_DIAGNOSTICS=1` (integrator/agent) |
| `POST /api/auth/ws-ticket` | Bearer | Short-lived WebSocket ticket (~120s) |
| `WS /ws/dashboard` | `?ticket=` or `Sec-WebSocket-Protocol: ofdd.<ticket>` | Full snapshot when authenticated; redacted only if `OFDD_PUBLIC_DASHBOARD_WS=1` |

Wall-display check-engine traffic lights still use public `GET /api/faults/status` and `GET /api/building/status`. The dashboard UI uses authenticated stack health and a WebSocket ticket after login.

## Rule Lab / diagnostics

| Variable | Purpose |
|----------|---------|
| `OFDD_PLAYGROUND_TIMEOUT_S` | Total rule/script budget (default 30s) |
| `OFDD_PLAYGROUND_MEMORY_MB` | Child process RSS cap (default 512) |
| `OFDD_PLAYGROUND_SUBPROCESS=0` | Disable OS subprocess isolation (not recommended on edge) |
| `OFDD_PLAYGROUND_INPROCESS=1` | Run in API process (localhost dev/tests only) |
| `OFDD_DEBUG_TRACEBACKS=1` | Return tracebacks to browser (dev only) |
| `OFDD_DEBUG_DIAGNOSTICS=1` | Verbose stack health (`url`, `bacnet_bind`) and `repo_root` in agent context |
| `OFDD_PUBLIC_DASHBOARD_WS=1` | Unauthenticated WebSocket with **redacted** snapshot (lab wall display only) |
| `OFDD_WS_TICKET_TTL_SEC` | WebSocket ticket lifetime (default 120, max 600) |

## Agent app edit

| Variable | Purpose |
|----------|---------|
| `OFDD_AGENT_ALLOW_APP_EDIT=1` | Allow agent tools that modify app source (default off) |

## Ollama / AI

Use `workspace/ollama.env.local`. Home dashboard uses read-only **building insight** (no chat). Interactive LLM chat is on the **AI Agent** tab only.
