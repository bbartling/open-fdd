# Operator Bridge security hardening

The Open-FDD bridge and React dashboard run on BACnet/OT edge hosts. Default posture is **fail closed**: authentication required, BACnet writes off, Rule Lab execution bounded, minimal error detail to browsers.

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
| `OFDD_AUTH_DISABLED=1` | Skip Bearer tokens **only** when `OFDD_BRIDGE_HOST` is `127.0.0.1` / `localhost` |
| `OFDD_INSECURE_LAN_DEV=1` | Allows `OFDD_AUTH_DISABLED` on non-localhost bind (lab only) |
| `OFDD_BRIDGE_HOST=127.0.0.1` | Recommended for local `uvicorn` / compose on one machine |

Missing auth on `0.0.0.0` bind logs a warning; set `OFDD_AUTH_STRICT_STARTUP=1` to **fail startup** instead.

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

## Rule Lab / diagnostics

| Variable | Purpose |
|----------|---------|
| `OFDD_PLAYGROUND_TIMEOUT_S` | Total rule/script budget (default 30s) |
| `OFDD_PLAYGROUND_MEMORY_MB` | Child process RSS cap (default 512) |
| `OFDD_PLAYGROUND_SUBPROCESS=0` | Disable OS subprocess isolation (not recommended on edge) |
| `OFDD_PLAYGROUND_INPROCESS=1` | Run in API process (localhost dev/tests only) |
| `OFDD_DEBUG_TRACEBACKS=1` | Return tracebacks to browser (dev only) |
| `OFDD_DEBUG_DIAGNOSTICS=1` | Expose `repo_root` in agent context (integrator/agent) |

## Agent app edit

| Variable | Purpose |
|----------|---------|
| `OFDD_AGENT_ALLOW_APP_EDIT=1` | Allow agent tools that modify app source (default off) |

## Ollama / AI

Use `workspace/ollama.env.local`. Home dashboard uses read-only **building insight** (no chat). Interactive LLM chat is on the **AI Agent** tab only.
