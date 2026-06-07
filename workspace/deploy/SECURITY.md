# Open-FDD operator stack — security (firewall / OT LAN)

Designed to run **behind a building firewall**, not on the public internet. Use VPN or a trusted building VLAN only — **do not expose Open-FDD directly to the internet**.

## Roles

| Role | Login env | Typical user | API access |
|------|-----------|--------------|------------|
| **operator** | `OFDD_OPERATOR_USER` / password or `OFDD_OPERATOR_PASSWORD_HASH` | Local facility user | View dashboard, sites, ingest CSV, FDD results |
| **integrator** | `OFDD_INTEGRATOR_USER` / password or hash | Master systems integrator (MSI) | All operator + BACnet discover, supervisory scan, **write/release** |
| **agent** | `OFDD_AGENT_USER` / password or hash | AI / automation (Codex, scripts) | Rule Lab, playground, agent chat, BACnet discover (no OT writes) |

Legacy single-user: `OFDD_WEB_USER` / `OFDD_WEB_PASSWORD` maps to **operator**.

## Generate credentials (required for LAN/production)

**Do not** copy values from `workspace/auth.env.example` — the bridge refuses known example secrets/passwords when bound to a LAN IP, `0.0.0.0`, `OFDD_ENV=production`, or with BACnet writes enabled.

```bash
python workspace/scripts/generate_auth_env.py > workspace/auth.env.local
```

Prefer bcrypt hashes over plaintext in production/LAN:

```bash
python workspace/scripts/hash_password.py   # prompts securely (no CLI password arg)
# OFDD_INTEGRATOR_PASSWORD_HASH=$2b$12$...
```

Hashed env vars take precedence over plaintext. Plaintext triggers a startup warning in strict modes.

## Enable auth

Set on the bridge host (systemd, `auth.env.local`, or Ansible host_vars):

```bash
OFDD_AUTH_SECRET=<long random string>   # min 32 chars on LAN binds
OFDD_OPERATOR_USER=...
OFDD_OPERATOR_PASSWORD_HASH=...         # preferred
OFDD_INTEGRATOR_USER=...
OFDD_INTEGRATOR_PASSWORD_HASH=...
OFDD_AGENT_USER=...
OFDD_AGENT_PASSWORD_HASH=...
```

When `OFDD_AUTH_SECRET` and at least one user are set, all `/api/*`, `/config/*`, `/ingest/*`, and `/openfdd-agent/*` require `Authorization: Bearer <token>` from `POST /api/auth/login`.

### Bearer token lifetime

Default **`OFDD_AUTH_TTL_SEC=28800`** (8 hours) — appropriate for OT operator sessions. Override as needed; values above 7 days are clamped unless `OFDD_AUTH_TTL_ALLOW_LONG=1` (local dev only).

### Login rate limiting

Failed logins are limited per client IP + username (default: 5 failures / 5 minutes, 5-minute lockout). Lockouts are audited as `auth.login.lockout`. Responses use a generic `invalid credentials` message.

### Dev-only auth bypass

`OFDD_AUTH_DISABLED=1` works **only** on loopback (`127.0.0.1` / `localhost`) without BACnet writes or `OFDD_ENV=production`.

Lab LAN demo (insecure): add `OFDD_INSECURE_LAN_DEV=1` — never use on production edges.

## Network

- Bridge defaults to **`127.0.0.1:8765`** in local dev (`run_local.sh`). **Always set auth** when binding non-loopback.
- Edge/Ansible deploy may set **`OFDD_BRIDGE_HOST=0.0.0.0`** so OT LAN workstations reach the dashboard — pair with fresh auth secrets and UFW limited to the VLAN.
- Commission agent stays **`127.0.0.1:8767`**; bridge proxies BACnet ops (no direct browser access to OT stack).
- Optional Caddy TLS/basic auth on port 80 — see `Caddyfile.example`.
- Set **`OFDD_TRUST_X_FORWARDED_FOR=1`** only behind a trusted reverse proxy (Caddy).
- **Do not** port-forward to the internet without VPN + stronger auth.

## BACnet writes

- Disabled by default. Set **`OFDD_ENABLE_BACNET_WRITE=1`** only when intentionally testing supervisory writes.
- Only **integrator** role may call `POST /api/bacnet/write`.
- Requires **`workspace/bacnet/write_allowlist.json`** unless `OFDD_BACNET_WRITE_ALLOW_ANY=1` (lab only).
- Allowlist entries support device/object/property filters, priority min/max, value min/max, and allowed discrete values.
- **`OFDD_BACNET_WRITE_DRY_RUN=1`**: validate + audit writes but do not send to field devices.
- Every write attempt (allowed, denied, dry-run) is audited in `audit.jsonl`.

Keep BACnet writes disabled unless you are deliberately commissioning with an allowlist.

## BACnet driver registry (Add device)

- **Enabled by default** for integrator commissioning (add/sync/delete devices in the driver tree).
- Read-only monitor sites: set **`OFDD_DISABLE_BACNET_DISCOVERY_MUTATIONS=1`** on the bridge.
- After changing bridge env files, run **`docker compose up -d --force-recreate bridge`** — `docker compose restart` does not reload `env_file` values.

## WebSocket tickets

Short-lived tickets (`OFDD_WS_TICKET_TTL_SEC`, default 120s) upgrade Bearer sessions to `/ws/dashboard`. Replay protection is **in-process only** — safe for single-worker uvicorn. Multi-worker deployments need shared ticket state (Redis/SQLite); otherwise tickets may be replayed across workers.

## Local dev workflow

```bash
python workspace/scripts/generate_auth_env.py   # or copy example for loopback-only bench
cp workspace/caddy.env.example workspace/caddy.env.local   # optional
./scripts/build_and_test.sh
./scripts/run_local.sh start
```

Loopback-only insecure bench (no auth):

```bash
OFDD_BRIDGE_HOST=127.0.0.1 OFDD_AUTH_DISABLED=1 ./scripts/run_local.sh start
```

## Edge deploy (after local pass)

```bash
./scripts/build_and_test.sh
cd infra/ansible && ./deploy.sh --limit bacnet_pi -v
```

Set `ofdd_auth_secret`, role users, and password hashes in private `host_vars`. Set `OFDD_ENV=production` on edge hosts.

## Audit trail (security / forensics)

Append-only **JSON Lines** under `workspace/logs/`:

| File | Contents |
|------|----------|
| `audit.jsonl` | Login success/failure/lockout, BACnet discover/write, ingest, sensitive API access |
| `error.jsonl` | Unhandled exceptions and application errors |

Each record includes: `@timestamp`, `event_id`, `event_type`, `severity`, `outcome`, `actor` (username/role), `client.ip`, `client.user_agent`, `http.method/path/status`, `resource`, `action`, `detail` (passwords/tokens stripped).

**Integrator API:**

- `GET /api/audit/events?limit=100`
- `GET /api/audit/errors?limit=100`
- `GET /api/audit/summary`

### Automatic log rotation

On bridge startup (no operator action required):

- Prune `audit.jsonl` and `error.jsonl` records older than **`OFDD_LOG_RETENTION_DAYS`** (default **90**).
- Archive oversized logs when **`OFDD_LOG_MAX_MB`** (default **50**) is exceeded.
- Remove stale `workspace/.local-run/*.log` files past the retention window.

Forward logs to SIEM (rsyslog/filebeat) in production; retain per incident response policy.

**Never logged:** passwords, bearer tokens, private keys.

## Production vs development

| Setting | Local dev | LAN / production |
|---------|-----------|------------------|
| `OFDD_BRIDGE_HOST` | `127.0.0.1` | `0.0.0.0` or site IP + auth |
| Credentials | example OK on loopback | `generate_auth_env.py` + hashes |
| `OFDD_AUTH_DISABLED` | loopback only | **refused** |
| `OFDD_ENABLE_BACNET_WRITE` | off unless testing | off unless allowlist commissioned |
| `OFDD_ENV` | unset | `production` on edges |
| Token TTL | 8h default | 8–12h recommended |
