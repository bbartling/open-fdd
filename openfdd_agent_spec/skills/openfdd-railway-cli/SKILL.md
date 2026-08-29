---
name: openfdd-railway-cli
description: >-
  Use when installing, authenticating, linking, or re-pinning the Open-FDD
  Railway hub (central/mqtt/web) via the Railway CLI on bensbench. Triggers on:
  railway CLI, RAILWAY_TOKEN, railway login, railway link, railway redeploy,
  Railway re-pin, OPENFDD_NGINX_RESOLVER, sha tip on Railway, gleaming-cooperation.
---

# Railway CLI (Open-FDD hub)

Full ops: [`docs/operations/RAILWAY_DEPLOYMENT.md`](../../../docs/operations/RAILWAY_DEPLOYMENT.md)  
Checklist: [`RAILWAY_DEPLOYMENT_CHECKLIST.md`](../../../docs/operations/RAILWAY_DEPLOYMENT_CHECKLIST.md)

**Not Open-FDD MCP.** Railway CLI / Railway’s optional MCP manage cloud deploys. HVAC FDD tools stay in [`mcp/`](../../../mcp/) (`openfdd-mcp` + agent JWT to private central).

## Verified host state (bensbench, 2026-08-29)

| Item | Value |
| --- | --- |
| Package | `@railway/cli` via `npm i -g @railway/cli` |
| Verified version | **5.45.7** |
| Binary | `~/.nvm/versions/node/*/bin/railway` (nvm PATH) |
| Auth | **`railway login`** (browser) — verified; optional `RAILWAY_TOKEN` in `~/.config/railway/bensbench.env` for non-interactive |
| Link | `~/open-fdd` → project **`gleaming-cooperation`**, env **`production`** |
| Workspace | Ben Bartling's Projects |

### Live services (names matter for CLI)

| Railway service name | Role | Notes |
| --- | --- | --- |
| `openfdd-central-cQ-F` | central | Private; DNS `openfdd-central-cQ-F.railway.internal:8080` |
| `openfdd-mqtt` | mqtt | Private MQTTS |
| `openfdd-web` | web | Public SPA; `OPENFDD_CENTRAL_UPSTREAM=openfdd-central-cQ-F.railway.internal:8080` |

Always `railway status` / `railway service list` before re-pin — do **not** assume the central service is literally named `openfdd-central`.

Post-auth snapshot (pre tip re-pin): mqtt Online on `sha-3395551`; web **Crashed** with `invalid port in resolver "fd12::10"` (needs tip `openfdd-web:sha-9667888` + `OPENFDD_NGINX_RESOLVER=auto`).

## Patch train (bosspi → Railway)

Do **not** treat bensbench dual-MQTT as the cloud gate. After each tiny rev / ops fix:

1. Tip Actions green + GHCR Publish (`sha-*` == nightly digest)
2. GH tidy (0 open PRs; delete feature branch)
3. Re-pin central → mqtt → web; bosspi fieldbus arm64 to same `sha-*`
4. Gates: L1 `/api/health` → L3 mqtt Online + ingest → L4 Pi `has_telemetry` → stream healthy → L5 FDD
5. Sync [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../../../docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md) — CLOSE/remove validated; keep deferred unfinished

MQTT certs: `railway volume add` on `openfdd-mqtt` at `/mosquitto/certs`, upload `ca.pem` + server cert/key. Pi reachability: `railway tcp-proxy create --port 8883 --service openfdd-mqtt` (human-approved) or VPN. Never commit PEMs/tokens.

## Non-negotiables

- Never commit `RAILWAY_TOKEN`, JWTs, or Railway variable dumps.
- Prefer GHCR **`sha-<7>`** (same tip as bench soak). Sticky `:nightly` only after digest match.
- Deploy order: **central healthy → mqtt → web**. No fieldbus on Railway.
- Keep `OPENFDD_CENTRAL_UPSTREAM` aligned with the **actual** central service DNS name.
- Railway AI / Railway MCP ≠ Open-FDD FDD agent.
- Optional `railway setup agent` installs Railway’s Cursor skills/MCP — OK if human asks; still follow this skill + AGENTS.md.

## Agent workflow

```bash
# 1) Ensure CLI
command -v railway || npm i -g @railway/cli
railway --version

# 2) Auth — browser (verified) OR token file
railway whoami || railway login
# Non-interactive alternative:
#   set -a && source ~/.config/railway/bensbench.env && set +a

# 3) Link once (from open-fdd checkout)
cd ~/open-fdd
railway status >/dev/null 2>&1 || railway link
# Expect: gleaming-cooperation / production

# 4) Re-pin tip — use REAL service names from status
SHA=sha-9667888
CENTRAL_SVC=openfdd-central-cQ-F   # confirm via railway status

railway service source connect --service "$CENTRAL_SVC" \
  --image "ghcr.io/bbartling/openfdd-central:${SHA}"
# wait private /api/health 200

railway service source connect --service openfdd-mqtt \
  --image "ghcr.io/bbartling/openfdd-mqtt:${SHA}"

railway variable set OPENFDD_NGINX_RESOLVER=auto --service openfdd-web
railway service source connect --service openfdd-web \
  --image "ghcr.io/bbartling/openfdd-web:${SHA}"
```

Smoke: public SPA + `https://<web>/api/health`. Sidebar version must match tip.

## Anti-patterns

- Logging `railway variable list --json` (secrets) into SESSION_LOG / chat.
- Hard-coding `--service openfdd-central` when the live name is `openfdd-central-cQ-F`.
- Re-pinning web before central is healthy.
- Deploying `openfdd-fieldbus` on Railway for BACnet.
- Confusing Railway CLI/MCP with `openfdd-mcp` FDD tools.
