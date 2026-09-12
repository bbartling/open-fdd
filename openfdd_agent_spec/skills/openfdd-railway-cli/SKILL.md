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

## Verified host state (bensbench, 2026-09-11)

| Item | Value |
| --- | --- |
| Package | `@railway/cli` via `npm i -g @railway/cli` |
| Auth | **`railway login`** (browser) — verified; optional `RAILWAY_TOKEN` in `~/.config/railway/bensbench.env` |
| Link | `~/open-fdd` → project **`gleaming-cooperation`**, env **`production`** |
| **Product hub pin** | **`sha-e80237c`** / VERSION **3.5.6** / health **`3.5.6+e80237c0e758`** · `multi_tenant=false` · `active_tenant_id=legacy` · `tenant_budgets=false` (Wave L **PINNED**). Rollback **`sha-9c3e8b1`** / **3.4.0** (Wave K). |
| Stress closeout | Mid-wave = smoke + gates **11–15**. Full stress at Wave L **L8** / shippable pins — [`STRESS_CLOSEOUT.md`](../../../docs/operations/STRESS_CLOSEOUT.md) · skill [`openfdd-stress-closeout`](../openfdd-stress-closeout/SKILL.md) |
| Local firewall hub | HTTP only — [`LOCAL_DEPLOYMENT.md`](../../../docs/operations/LOCAL_DEPLOYMENT.md) |
| Fieldbus | **Not** a Railway service — bensbench x86 via `./scripts/openfdd_fieldbus_railway_up.sh sha-<7>` |

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

Smoke: public SPA + `https://<web>/api/health` (and `/api/tenants` — Wave L: `multi_tenant=false`, empty `historian_prefix`, `active_tenant_id=legacy` when OFF). Version must match the **pinned** SHA (`3.5.3+d67d27b…` for `sha-d67d27b`). Export **`RAILWAY_ADMIN_PASSWORD`** from Railway vars for mid-wave gates (local `.env` must not clobber).

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

## OT floor (x86 fieldbus)

`OPENFDD_FIELDBUS_POLL_INTERVAL_SECS=60` and `OPENFDD_MQTT_PUBLISH_INTERVAL_SECS=60`. Never set `OPENFDD_FIELDBUS_DEV_FAST_POLL=1` in production.

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
