---
title: Bench recovery (machine death)
parent: Operations
nav_order: 2
---

# Bench recovery — recreate Open-FDD field edge if this host dies

**Purpose:** If **bensbench** (or any field laptop) is lost, a new x86 Linux box can resume the Railway hub + fieldbus topology and continue the **3.3.21→3.3.26** patch trains using **only** GitHub + GHCR + Railway + documented secrets (never secrets in git).

Living evidence: [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](BUG_REPORT_OT_MODBUS_HAYSTACK.md).  
Patch trains (mirrored Cursor plans): [`patch_trains/`](patch_trains/).  
AI handoff: [`recovery/AI_CONTEXT_HANDOFF.md`](recovery/AI_CONTEXT_HANDOFF.md).  
Stress handbook: [`STRESS_CLOSEOUT.md`](STRESS_CLOSEOUT.md).  
Rev loop: [`PATCH_CYCLE.md`](PATCH_CYCLE.md).

## What survives without this disk

| Asset | Where | Notes |
|-------|--------|------|
| Product source + scripts | `github.com/bbartling/open-fdd` `master` | Clone fresh |
| Stack images | `ghcr.io/bbartling/openfdd-{central,web,mqtt,fieldbus}:sha-<7>` | Pull only — never local docker build on low-RAM |
| Hub data | Railway volume `/workspace` | Restore from `~/openfdd-backups/railway/<UTC>/` **if you copied backups off-box**; else hub Parquet may still be on Railway |
| MQTT edge kit | **Not in git** | Re-issue via `POST /api/mqtt/edge-kits` **only if** Railway mqtt volume has CA **key**; today often **reuse `pi-1` kit** (CA key absent) — see BUG_REPORT |
| Railway CLI token | Operator secret | `railway login` / `RAILWAY_TOKEN` |
| GH token | Operator secret | `gh auth login` |
| Creekside fixture zip | Operator file | Path historically `/home/ben/OpenFdd_Creekside.zip` — **copy off-box**; not in git |
| Cursor plans | **Also in-repo** under `docs/operations/patch_trains/` | Do not rely on `~/.cursor/plans` alone |
| Tuner baseline JSON | `docs/operations/recovery/*_tuners_snapshot*.json` | Vibe19 vs Lab counts |

## Target topology (do not invent a new one)

```text
[new x86 host]
  openfdd-fieldbus (GHCR sha-<7>, host net)
       │ MQTTS
       ▼
Railway: openfdd-mqtt :8883 (TCP proxy reseau.proxy.rlwy.net:44763)
       │
       ▼
Railway: openfdd-central-cQ-F  (volume /workspace)
       │
       ▼
Railway: openfdd-web  https://openfdd-web-production-af99.up.railway.app
```

- **No** Raspberry Pi on Open-FDD closeout.
- **No** local `react-ot` hub as AFDD head-end for patch cycles.
- Project: Railway `gleaming-cooperation` / env `production`.

## Day-0 on a new machine (checklist)

### 1) OS + tools

```bash
# docker, gh, railway CLI, python3, git, curl, jq
gh auth login
railway login   # or export RAILWAY_TOKEN
docker login ghcr.io   # if private pulls required
```

### 2) Clone + link Railway

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
git checkout master && git pull
railway link   # gleaming-cooperation / production / openfdd-central-cQ-F
```

Optional: copy [`~/.config/railway/bensbench.env.example`](../../.config/railway/bensbench.env.example) pattern — **never commit** filled `bensbench.env`.

### 3) Discover tip pin

```bash
git log -1 --oneline
cat VERSION
gh run list --branch master --workflow "Publish Open-FDD stack to GHCR" --limit 3
# SHA=sha-<first7 of tip commit that Publish succeeded for>
```

Health must read `3.3.N+<fullsha-prefix>` after re-pin.

### 4) Hub backup (before any re-pin)

```bash
./scripts/railway_central_workspace_backup.sh
# → ~/openfdd-backups/railway/<UTC>/central-workspace.tgz (+ mqtt-certs.tgz)
# COPY THAT DIRECTORY OFF-BOX (USB / other host / encrypted cloud)
```

### 5) Re-pin hub (central → mqtt → web)

See [`RAILWAY_DEPLOYMENT.md`](RAILWAY_DEPLOYMENT.md):

```bash
SHA=sha-<7>
CENTRAL_SVC=openfdd-central-cQ-F
railway service source connect --service "$CENTRAL_SVC" \
  --image "ghcr.io/bbartling/openfdd-central:${SHA}"
railway service source connect --service openfdd-mqtt \
  --image "ghcr.io/bbartling/openfdd-mqtt:${SHA}"
railway variable set OPENFDD_NGINX_RESOLVER=auto --service openfdd-web
railway service source connect --service openfdd-web \
  --image "ghcr.io/bbartling/openfdd-web:${SHA}"
curl -sS "$OPENFDD_API_BASE/api/health"   # expect 3.3.N+…
```

Public web: `https://openfdd-web-production-af99.up.railway.app`

### 6) Fieldbus only on this host

```bash
# Edge kit: deploy/mqtt/kits/bldg2__pi-1/  (restore from backup OR mint if CA allows)
./scripts/openfdd_fieldbus_railway_up.sh "$SHA"
curl -sf http://127.0.0.1:8081/health
# Railway: /api/edges → has_telemetry true for pi-1 / bldg2
```

Defaults in script: `OPENFDD_MQTT_HOST=reseau.proxy.rlwy.net`, port `44763`, site `bldg2`, edge `pi-1`.

Field devices: hosted weather loopback AV (see `config/fieldbus/` + compose edge railway) — no JCI/Pi required for stress.

### 7) Stress LAST (must cite this tip)

```bash
export OPENFDD_API_BASE=https://openfdd-web-production-af99.up.railway.app
# ensure RAILWAY_ADMIN_PASSWORD available for gates that need it
./scripts/nightly-ot-bench/run_railway_hub_stress.sh
```

Matrix: [`STRESS_CLOSEOUT.md`](STRESS_CLOSEOUT.md) STRESS 0–6 (synth59, gate17, B100 `RAILWAY_ONLY=1`, Creekside, gate19, light ZAP).

**Creekside zip:** place operator copy then run spot scripts under `scripts/gates/creekside_package_import_spot.sh`.

### 8) Resume patch trains

1. Read [`patch_trains/openfdd_patch_series_3.3.21_to_3.3.26_program.plan.md`](patch_trains/openfdd_patch_series_3.3.21_to_3.3.26_program.plan.md)
2. Open **one** child plan at a time
3. Log every Verdict in BUG_REPORT (silent skip forbidden)
4. Optional: copy plans into `~/.cursor/plans/` for Cursor UI TODOs

### 9) GH hygiene every rev

```bash
gh pr list --state open          # must be 0 at END
git ls-remote --heads origin     # only master (+ current PR head while open)
gh run list --branch master --limit 15
```

## Off-box backup pack (operator — do this before the disk dies)

Copy periodically to USB / second host (secrets encrypted):

```text
~/openfdd-backups/railway/<latest>/          # central-workspace.tgz + mqtt-certs.tgz
~/open-fdd/deploy/mqtt/kits/bldg2__pi-1/     # edge kit PEMs (sensitive)
~/OpenFdd_Creekside.zip                      # fixture
~/.config/railway/bensbench.env              # if used (sensitive)
open-fdd/.env                                # if used (sensitive) — never git
```

Git alone is **not** enough for kits/certs/zips.

## Scripts map (all in-repo)

| Script | Role |
|--------|------|
| `scripts/railway_central_workspace_backup.sh` | Hub volume tar |
| `scripts/openfdd_fieldbus_railway_up.sh` | x86 field → Railway MQTTS |
| `scripts/nightly-ot-bench/run_railway_hub_stress.sh` | CSV + ZAP closeout |
| `scripts/gates/railway_b100_parity_spot.sh` | B100 Railway parity |
| `scripts/gates/creekside_package_import_spot.sh` | Creekside import |
| `scripts/openfdd_docker_maintenance.sh` | Low-RAM non-aggressive cleanup |

## Anti-patterns

- Local `docker build` of central/web on a small bench
- Standing up `react-ot` as production AFDD head-end for closeout
- Putting Pis back on stress path
- Committing kits, tokens, OT LAN IPs, or filled `.env`
- Claiming a rev CLOSED with stress artifacts from an older `sha-*`
