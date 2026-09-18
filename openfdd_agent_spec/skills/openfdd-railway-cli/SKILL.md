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

## Verified host state (Mint / bensbench, 2026-09-13)

| Item | Value |
| --- | --- |
| Package | `@railway/cli` via `npm i -g @railway/cli` |
| Auth | Prefer **`railway login`** (CLI session). Stale `RAILWAY_TOKEN` in `.secrets/.env` breaks CLI — `env -u RAILWAY_TOKEN` when needed. |
| Link | checkout → project **`gleaming-cooperation`**, env **`production`** |
| **Product hub pin** | **OPS PINNED** **`sha-f727a55`** / **3.5.29** / health **`3.5.29+f727a55e01a4`** · `multi_tenant=true` · backup `20260918T221510Z` · stress `20260918T231541Z` **`fully_qualified=true`**. Prior Soft Tip B: **`sha-4a5c11e`** / **3.5.28**. Wave N ACL baseline: **`sha-9072e0b`** / **3.5.10**. |
| Stress closeout | Wave N gate = ACL trio (31) + MQTTS continuity (32) + hub stress while ACME streams — [`BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md`](../../../docs/operations/BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md) · [`STRESS_CLOSEOUT.md`](../../../docs/operations/STRESS_CLOSEOUT.md) |
| Local firewall hub | HTTP only — [`LOCAL_DEPLOYMENT.md`](../../../docs/operations/LOCAL_DEPLOYMENT.md) |
| Fieldbus | **Not** a Railway service — ACME VIM OT edge (private) or bensbench x86 via `./scripts/openfdd_fieldbus_railway_up.sh sha-<7>` |

### Live services (names matter for CLI)

| Railway service name | Role | Notes |
| --- | --- | --- |
| `openfdd-central-cQ-F` | central | Private; DNS `openfdd-central-cQ-F.railway.internal:8080` |
| `openfdd-mqtt` | mqtt | Private MQTTS |
| `openfdd-web` | web | Public SPA; `OPENFDD_CENTRAL_UPSTREAM=openfdd-central-cQ-F.railway.internal:8080` |

Always `railway status` / `railway service list` before re-pin — do **not** assume the central service is literally named `openfdd-central`.

## Tooling map (do not confuse)

| Need | Tool |
| --- | --- |
| Publish / tip images | GitHub Actions `Publish Open-FDD stack to GHCR` + `./scripts/check_ghcr_tip_stack.sh` |
| Backup + re-pin hub | **This skill** (Railway CLI) |
| Edge → MQTTS | `./scripts/openfdd_fieldbus_railway_up.sh` on bensbench |
| FDD / analytics for Cursor/Codex | [`mcp/`](../../../mcp/) `openfdd-mcp` + agent JWT — **not** Railway MCP |
| Local CSV lab | `./scripts/openfdd_stack_up.sh react` (firewall HTTP) |

## Patch train (x86 fieldbus → Railway + stress LAST)

See [`PATCH_CYCLE.md`](../../../docs/operations/PATCH_CYCLE.md). After each tiny rev:

1. Tip Actions green + GHCR Publish
2. GH tidy (0 open PRs; delete feature branch)
3. **Backup** then re-pin central → mqtt → web
4. `./scripts/openfdd_fieldbus_railway_up.sh sha-<7>` (bensbench x86 only — no Pi)
5. `./scripts/nightly-ot-bench/run_railway_hub_stress.sh`
6. Sync [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../../../docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md)

MQTT certs: volume on `openfdd-mqtt` at `/mosquitto/certs` (`ca.pem`, `server.cert.pem`, `server.key.pem`, `acl`).  
**Learned (Wave N):** (1) `server.key.pem` must be readable by uid **1883** (`mosquitto`) — root `0600` → crash `Permission denied`; tip mqtt image entrypoint `chmod a+r` + `chown`. (2) Server cert **must include SAN** (`DNS:openfdd-mqtt`, `DNS:openfdd-mqtt.railway.internal`, TCP-proxy host) — rustls rejects CN-only → `ssl/tls alert bad certificate` while `openssl s_client` still OK. (3) Volume SFTP/`service files` fail while mqtt is crash-looping — detach volume → temporary alpine `sleep infinity` helper → chmod/upload → reattach → delete helper. Never leave stray Railway projects from `railway up` without `--project`. TCP proxy: `railway tcp-proxy list -s openfdd-mqtt`. Never commit PEMs/tokens.

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
SHA=sha-<7>   # tip pin. Health must match THIS tag (3.5.x+… on Wave L).
CENTRAL_SVC=openfdd-central-cQ-F   # confirm via railway status / service list

# Backup FIRST (hard gate)
./scripts/railway_central_workspace_backup.sh

railway service source connect --service "$CENTRAL_SVC" \
  --image "ghcr.io/bbartling/openfdd-central:${SHA}"
# wait private /api/health 200 — then mqtt → web
# Prefer: railway ssh -s "$CENTRAL_SVC" -- sh -lc 'curl -sf http://127.0.0.1:8080/api/health'

railway service source connect --service openfdd-mqtt \
  --image "ghcr.io/bbartling/openfdd-mqtt:${SHA}"

railway variable set OPENFDD_NGINX_RESOLVER=auto --service openfdd-web
# Historian packages under OPENFDD_STORAGE_URL need FDD parquet root:
railway variable set OPENFDD_PARQUET_ROOT=/workspace/openfdd --service "$CENTRAL_SVC"
railway service source connect --service openfdd-web \
  --image "ghcr.io/bbartling/openfdd-web:${SHA}"
# If ingest_ok stuck at 0 after mqtt re-pin: railway redeploy -s "$CENTRAL_SVC" -y

# Fieldbus is local on bensbench (not a Railway service):
./scripts/openfdd_fieldbus_railway_up.sh "$SHA"
```

Smoke: public SPA + `https://<web>/api/health` (lean readiness only). With auth ON, **`/api/tenants` requires Bearer** — do not smoke it unauthenticated (Kali O2c). After login, `/api/tenants` shows membership-scoped tenants; hub admin sees all. Version must match the **pinned** SHA. Export **`RAILWAY_ADMIN_PASSWORD`** from Railway vars for mid-wave gates (local `.env` must not clobber).

**Wave L mid-wave:** gates **11–14** (`22`–`25_wave_l_*.sh`). Full `run_railway_hub_stress.sh` at **L8**.

**Field:** bensbench x86 `openfdd-fieldbus` → Railway MQTTS only. Raspberry Pis are out of stress. See [`LOCAL_DEPLOYMENT.md`](../../../docs/operations/LOCAL_DEPLOYMENT.md).

## BACKUP before every central re-pin (hard gate)

```bash
cd ~/open-fdd
./scripts/railway_central_workspace_backup.sh
# → ~/openfdd-backups/railway/<UTC>/central-workspace.tgz (+ optional mqtt-certs.tgz)
```

Re-pin = **image tag only**. Never delete/recreate the `/workspace` volume. Docs: [`backup-update-restore.md`](../../../docs/operations/backup-update-restore.md).

**Always pin tip after Publish:** stale `3.3.N+oldsha` on Railway while tip is newer is a P0 fail. Re-pin central + mqtt + web + x86 fieldbus to the same `sha-<7>`.

## OT floor (fieldbus)

**Wave N lock:** poll + MQTT publish are compile-time **300 s** (`FIXED_POLL_INTERVAL_SECS`). Env/TOML overrides are ignored. First MQTT publish is immediate after connect, then every 300 s. Never burst OT; never deploy fieldbus on Railway.

## Data model (empty Overview)

Empty charts/FDD with healthy `ingest_ok` ⇒ missing **roles** (`zonetemp`/`sa_t` must normalize to `zone_t`/`sat`), not broken nginx. See package-mapping skill + `normalize_role` in `fdd_core`.

## Anti-patterns

- Logging `railway variable list --json` (secrets) into SESSION_LOG / chat.
- Hard-coding `--service openfdd-central` when the live name is `openfdd-central-cQ-F`.
- Re-pinning web before central is healthy.
- Re-pinning central **without** a workspace backup.
- Deploying `openfdd-fieldbus` on Railway for BACnet.
- Confusing Railway CLI/MCP with `openfdd-mcp` FDD tools.
- Leaving hub on a stale `sha-*` after tip Publish.
