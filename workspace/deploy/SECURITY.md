# Open-FDD operator stack — security (firewall / OT LAN)

Designed to run **behind a building firewall**, not on the public internet.

## Roles

| Role | Login env | Typical user | API access |
|------|-----------|--------------|------------|
| **operator** | `OFDD_OPERATOR_USER` / `OFDD_OPERATOR_PASSWORD` | Local facility user | View dashboard, sites, ingest CSV, FDD results |
| **integrator** | `OFDD_INTEGRATOR_USER` / `OFDD_INTEGRATOR_PASSWORD` | Master systems integrator (MSI) | All operator + BACnet discover, supervisory scan, **write/release** |
| **agent** | `OFDD_AGENT_USER` / `OFDD_AGENT_PASSWORD` | AI / automation (Codex, scripts) | Rule Lab, playground, agent chat, BACnet discover (no OT writes) |

Legacy single-user: `OFDD_WEB_USER` / `OFDD_WEB_PASSWORD` maps to **operator**.

## Enable auth

Set on the bridge host (systemd, `auth.env.local`, or Ansible host_vars):

```bash
OFDD_AUTH_SECRET=<long random string>
OFDD_OPERATOR_USER=...
OFDD_OPERATOR_PASSWORD=...
OFDD_INTEGRATOR_USER=...
OFDD_INTEGRATOR_PASSWORD=...
OFDD_AGENT_USER=...
OFDD_AGENT_PASSWORD=...
```

When `OFDD_AUTH_SECRET` and at least one user are set, all `/api/*`, `/config/*`, `/ingest/*`, and `/openfdd-agent/*` require `Authorization: Bearer <token>` from `POST /api/auth/login`.

## Network

- Bridge defaults to **`127.0.0.1:8765`** in local dev (`run_local.sh`, `OFDD_BRIDGE_HOST` unset). **Always set auth** when binding non-loopback.
- Edge/Ansible deploy may set **`OFDD_BRIDGE_HOST=0.0.0.0`** so OT LAN workstations reach the dashboard — that is explicit operator opt-in only; pair with auth and UFW limited to the VLAN (or use Caddy on `:80` as the LAN entry).
- Commission agent stays **`127.0.0.1:8767`**; bridge proxies BACnet ops (no direct browser access to OT stack).
- Optional Caddy TLS/basic auth on port 80 — see `Caddyfile.example` (explicit opt-in for ingress).
- Set **`OFDD_TRUST_X_FORWARDED_FOR=1`** only behind a trusted reverse proxy (Caddy); otherwise client IP is the socket peer.
- **Do not** port-forward to the internet without VPN + stronger auth.

## BACnet writes

- Only **integrator** role may call `POST /api/bacnet/write` (including `null` priority release).
- All writes are audited in commission agent logs on the edge host.

## Local dev workflow

```bash
cp workspace/auth.env.example workspace/auth.env.local
cp workspace/caddy.env.example workspace/caddy.env.local   # optional; http://127.0.0.1/ entry
./scripts/build_and_test.sh    # vitest + prod React build + pytest — required before edge deploy
./scripts/run_local.sh start   # prod UI + stack; Caddy :80 → bridge 127.0.0.1:8765 when enabled
```

Use **`http://127.0.0.1/`** (Caddy) or **`http://127.0.0.1:8765/`** (Caddy off). Skip UI rebuild: `./scripts/run_local.sh restart --ui-skip`.

## Edge deploy (after local pass)

```bash
./scripts/build_and_test.sh
cd infra/ansible && ./deploy.sh --limit bacnet_pi -v
```

Set `ofdd_auth_secret`, `ofdd_integrator_user`, etc. in private `host_vars` before OT LAN exposure.

## Audit trail (security / forensics)

Append-only **JSON Lines** under `workspace/logs/`:

| File | Contents |
|------|----------|
| `audit.jsonl` | Login success/failure, BACnet discover/write, ingest, sensitive API access |
| `error.jsonl` | Unhandled exceptions and application errors |

Each record includes: `@timestamp`, `event_id`, `event_type`, `severity`, `outcome`, `actor` (username/role), `client.ip`, `client.user_agent`, `http.method/path/status`, `resource`, `action`, `detail` (passwords/tokens stripped).

**Integrator API:**

- `GET /api/audit/events?limit=100`
- `GET /api/audit/errors?limit=100`
- `GET /api/audit/summary`

**Dashboard:** green/red/yellow/gray status pills in the sidebar (`GET /health/stack`) for bridge, BACnet commission agent, poll driver, optional MCP.

Forward logs to SIEM (rsyslog/filebeat) in production; retain per incident response policy.

**Never logged:** passwords, bearer tokens, private keys.
