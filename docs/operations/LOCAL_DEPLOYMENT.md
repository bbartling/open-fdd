---
title: Local deployment (firewall hub)
parent: Operations
nav_order: 5
nav_exclude: true

---

# Local deployment — firewall / on-prem hub

Open-FDD is **local-first**. The typical bench path is a GHCR-pulled Compose stack on a LAN host (e.g. bensbench) behind a firewall — **not** a public internet appliance.

## Threat model (current)

| Fact | Implication for agents |
|------|------------------------|
| Dashboard + API are **plain HTTP** on the LAN | Expect `http://127.0.0.1:3000` (UI) and `http://127.0.0.1:8080` (API). **No product TLS termination on local Compose yet.** Login passwords and Bearer JWTs travel in the clear — **trusted/isolated LAN or VPN only**. For shared/untrusted networks, terminate TLS on an ops reverse proxy in front of Compose. |
| Intended exposure | Host firewall / VPN / OT LAN only. Do **not** advertise local `:3000`/`:8080` to the public internet. |
| Cloud hosting | Retired. Railway and cloud web-app hosting are prohibited; hosting is the local single-host stack ([LOCAL_HOSTING.md](LOCAL_HOSTING.md)). |
| Auth still required | Admin / agent JWT on central even over HTTP — never skip auth “because it’s local.” |

If a customer needs HTTPS on-prem, use the supported **Caddy standalone HTTPS**
paths (operator-provided cert, managed local CA, or explicit lab self-signed) —
see [`SECURITY_QUALIFICATION_POLICY.md`](SECURITY_QUALIFICATION_POLICY.md) and
`deploy/caddy/Caddyfile.standalone.https*`. Default `react-ot` / `csv` Compose
helpers remain plain HTTP behind a firewall. Do not claim production TLS or a
Nessus trust closeout from lab self-signed alone.

## Recipes

Named product recipes: **Recipe 1** cloud hub (mqtt+central+web, amd64) · **Recipe 2** OT edge (central+web+protocol, broker optional). See [build-recipes.md](build-recipes.md).

| Helper | Named recipe | Compose | Use |
|--------|--------------|---------|-----|
| **`edge` + `compose.edge.railway.yml` (removed, historical)** | optional WAN → Recipe 1 | fieldbus only → hub MQTTS (historical) | Legacy (archived OT edge) |
| `csv` / `react` | **Recipe 2** (no/optional protocol) | web + central | Local CSV / broker-free edge lab |
| `react-ot` / `standalone` | **Recipe 2** (+ local mqtt optional) | + fieldbus (+ mqtt) | Optional local OT lab (not closeout; no Pis) |

Docs: [build-recipes.md](build-recipes.md) · agent: [`CONTAINER_AGENT.md`](../../openfdd_agent_spec/CONTAINER_AGENT.md) · skill [`openfdd-stack-ghcr`](../../openfdd_agent_spec/skills/openfdd-stack-ghcr/SKILL.md).

## Bootstrap (GHCR pull — preferred)

```bash
cd ~/open-fdd
# After GHCR Publish for tip:
SHA=sha-<7chars>   # e.g. sha-15baccf
export OPENFDD_IMAGE_TAG="$SHA"

# Low-RAM: skip aggressive docker prune if operator already cleaned
./scripts/openfdd_maint_update_resume.sh react-ot "$SHA" --skip-maintenance

curl -sf http://127.0.0.1:8080/api/health | jq '{ok,version,service}'
# UI: http://127.0.0.1:3000   (or host LAN IP :3000 behind firewall)
# Fieldbus health (react-ot): http://127.0.0.1:8081
```

**Never** `docker build` stack images on low-RAM hosts — wait for Actions, pull `sha-*`.

MQTT ACL for local: place under `deploy/mqtt/certs/acl` (tip mqtt images read `acl_file /mosquitto/certs/acl`).

## Dual pipeline (retired for closeout)

Historical: patch-cycle OT was **one** MQTTS path (x86 fieldbus → the retired Railway hub). Optional local `react-ot` is a lab only — do not use it as the AFDD head-end. Current hosting: [`LOCAL_HOSTING.md`](LOCAL_HOSTING.md).

## Multi-site NF providers (local stack)

Run any number of NF portal sites from configuration only — no site names in
product code.

1. Copy real site files out of the repo (for example
   `~/.config/openfdd/sites/site_a.json`). Use
   [`scripts/nf/provider_sites.example.json`](../../scripts/nf/provider_sites.example.json)
   as the shape. Each file is one site object or a one-element array. Credential
   fields use distinct `env:NAME` refs per site, for example
   `env:NF_CLIENT_SECRET_SITE_A` and `env:NF_CLIENT_SECRET_SITE_B`.
2. Put NF portal credential values in a **dedicated gitignored env file**, not the
   whole stack `.env`. Default path: `config/nf/provider-credentials.env` (copy
   from [`config/nf/provider-credentials.env.example`](../../config/nf/provider-credentials.env.example),
   `chmod 600`). Override with `OPENFDD_NF_PROVIDER_CREDENTIALS_ENV` in repo-root
   `.env` (for example `~/.config/openfdd/nf-provider-credentials.env`). Only
   names referenced as `env:...` in provider JSON belong in that file — not
   `OPENFDD_JWT_SECRET`, Timescale passwords, or other stack secrets.
   `docker/compose.local.yml` loads that file into `central` optionally; legacy
   single-site `NF_CLIENT_ID` / `NF_CLIENT_SECRET` / `NFURL` may still be set in
   repo-root `.env` and are forwarded by name when present.
3. Mount the sites directory read-only on central. `docker/compose.local.yml`
   binds `${OPENFDD_SITES_DIR:-${HOME}/.config/openfdd/sites}` on the host to
   `/config/sites:ro` inside `central`. Docker Compose does **not** expand `~`;
   leave `OPENFDD_SITES_DIR` unset only when `HOME` is set in the shell that
   runs `docker compose`, or set `OPENFDD_SITES_DIR` explicitly in repo-root
   `.env`. **Before the first stack start**, create that host directory as the
   operator user (Docker creates a missing short-syntax bind source as
   **root-owned**):

   ```bash
   mkdir -p "${OPENFDD_SITES_DIR:-$HOME/.config/openfdd/sites}"
   ```

   The overlay also binds `../scripts/nf` at `/config/nf:ro` (generic helpers
   only). Set `OPENFDD_PROVIDER_SITES=/config/sites` (directory of `*.json`) or
   a comma-separated list of files under that mount.
4. Reload provider config after edits. **`GET /api/providers/sites`** lists each
   loaded site; a missing env ref fails only that site (`auth_not_configured`).

   - **JSON only** under an unchanged mount (same `OPENFDD_SITES_DIR` and
     `OPENFDD_PROVIDER_SITES`): restart `central` is enough (`docker compose …
     restart central`).
   - **`OPENFDD_SITES_DIR` or `OPENFDD_PROVIDER_SITES` changed** in repo-root
     `.env`: recreate `central` so bind mounts and env reload — run the same
     `docker compose … up -d` you use for stack bring-up (for example
     `./scripts/openfdd_stack_up.sh portal --no-pull` or
     `./scripts/openfdd_local_repin.sh`; both already use `up -d --no-build`, not
     restart-only).
5. After onboarding, run
   `python3 scripts/nf/check_portal_fresh.py --env <secrets.env> --sites <site.json> --points <probes.json>`
   per portal (see [`scripts/nf/README.md`](../../scripts/nf/README.md)).

## NF ingest backfill and throughput

Device backfill (`POST /api/ingest/backfill`) enqueues at most **48** exact UTC
hours for **one** committed plan group (`device_id`). Multi-device sites need
many requests unless you use site backfill.

**Site backfill** (`POST /api/ingest/backfill/site`, operator JWT) takes
`canonical_site`, `provider_instance_id`, `idempotency_key`, and a half-open UTC
hour range (`start`, `end`). It enqueues every group from the active committed
plan (`schedule_plan_devices` on the active plan). One request is capped at
**48** hours and **2048** device×hour jobs. Repeating the same idempotency key
and range returns the same jobs (per-window logical keys dedupe in Postgres).

Example (seven days, one site):

```bash
curl -s -X POST "$OPENFDD_API_BASE/api/ingest/backfill/site" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "idempotency_key": "backfill-site-7d-2026-10-20",
    "canonical_site": "YOUR_SITE_ID",
    "provider_instance_id": "nf:your-connection-id",
    "start": "2026-10-13T00:00:00Z",
    "end": "2026-10-20T00:00:00Z"
  }'
```

Watch drain with `GET /api/ingest/jobs?site_id=…` and **Operations →
Providers**.

### Tuning variables (compose / `.env`)

Forwarded into `central` by `docker/compose.local.yml` and
`docker/compose.portal.yml` (Wave 1a):

| Variable | Role |
| --- | --- |
| `OPENFDD_INGEST_CATCHUP_HOURS` | Scheduler catch-up per device on startup (max 48). |
| `OPENFDD_INGEST_DAILY_CATCHUP_DAYS` | Daily schedule catch-up depth (max 7). |
| `OPENFDD_INGEST_PUBLICATION_DELAY_SECS` | Delay before a closed hour is planned. |
| `OPENFDD_PROVIDER_TICK_SECS` | Provider scheduler tick (default 30). |
| `OPENFDD_PROVIDER_MAX_CONCURRENT` | Parallel site polls (default 2). |
| `OPENFDD_INGEST_PORTAL_MAX_IN_FLIGHT` / `OPENFDD_INGEST_PORTAL_MAX_PER_MINUTE` | Shared portal rate limits for all workers. |

Measured throughput on a typical lab host is about **4–8 ingest jobs/min**
when portal history is the bottleneck (34 groups × 18 hours ≈ 612 jobs is on the
order of **1–3 hours** queue drain). Single-group sites often finish **48**
windows in under **15 minutes**. Record your measured rate after each backfill;
do not assume gap-free ingest.

### Coverage cadence binding

Verified coverage (`GET /api/ingest/gaps?view=status`) needs each approved plan
point to carry an expectation: `history_mode` `interval` with `cadence_secs`, or
`cov` with optional `heartbeat_secs`. Values come from Normal Framework point
metadata on inventory sync, or from the engineer model overlay (`POST
/api/model/point` — Wave 2c). Points with no binding stay **`not_assessed`**
(`expected_slots: 0`); an empty gaps list does **not** mean complete coverage.
Operations shows **Not assessed** with the reason (`cadence_not_bound` until
cadence is bound). Provider health lists **approved** vs **withheld** plan
points and withheld reasons (for example provisional points).

## MCP against local central

```bash
export OPENFDD_API_BASE=http://127.0.0.1:8080
# Mint agent JWT — see mcp/INSTRUCTIONS.md
export OPENFDD_MCP_TOKEN=…
```

Use `http://` (not `https://`) for local Compose. See [`mcp/README.md`](../../mcp/README.md).

## Stress

Closeout runs on an owned local stack (Grok-owned qualification harness — [`openfdd_agent_spec/ownership.yaml`](../../openfdd_agent_spec/ownership.yaml)). The Railway public-URL closeout in [`STRESS_CLOSEOUT.md`](STRESS_CLOSEOUT.md) is historical.

## Data-safe updates

`./scripts/openfdd_stack_up.sh` and `./scripts/openfdd_maint_update_resume.sh` reuse the `openfdd-timescale` named volume. They do not drop, truncate, or re-seed it. Postgres init SQL in `docker/compose.timescale.yml` runs only when that volume is empty. Central startup applies the same SQL forward-only (`CREATE … IF NOT EXISTS`) and leaves existing `sample` rows in place.

Maintenance prunes stopped containers and dangling images. It does not prune volumes. Volume prune requires `./scripts/openfdd_docker_maintenance.sh --prune-volumes --i-understand-data-loss` (or `--prune-volumes` with `OPENFDD_ALLOW_DESTRUCTIVE_DB=1`).

Leave `OPENFDD_RESET_DB` unset on updates. A one-time historian purge is `scripts/timescale/purge_historian.py` with a fresh `OPENFDD_RESET_DB` token and `OPENFDD_ALLOW_DESTRUCTIVE_DB=1` (or `--reset-db` and `--i-understand-data-loss`). The same token does not purge again. Central startup uses that same rule and refuses a token that lacks the allow flag. Building 50 reseed (`scripts/timescale/auto_seed.py`) copies into an empty site. It deletes that site only when `OPENFDD_SEED_FORCE=1` and `OPENFDD_ALLOW_DESTRUCTIVE_DB=1` are both set.

## Compose environment (central)

The local stack merges `docker/compose.portal.yml`, `docker/compose.timescale.yml`, and `docker/compose.local.yml`. Operator tuning in repo-root `.env` is forwarded into the `central` service:

| Variable | Purpose |
| --- | --- |
| `OPENFDD_INGEST_CATCHUP_HOURS` | Hourly ingest catch-up bound per device |
| `OPENFDD_INGEST_DAILY_CATCHUP_DAYS` | Daily ingest replay span |
| `OPENFDD_INGEST_PUBLICATION_DELAY_SECS` | Delay after local midnight before daily windows enqueue |
| `OPENFDD_PROVIDER_TICK_SECS` | Provider poller / ingest worker tick |
| `OPENFDD_AFDD_MODE` | `bulk` (default) or `continuous` |
| `OPENFDD_AFDD_BUILDING_ID` | Optional single-building AFDD scope |
| `OPENFDD_AFDD_BUILDING_IDS` | Optional comma-separated building list |
| `OPENFDD_AFDD_INTERVAL_MINUTES` | Continuous AFDD cadence |
| `OPENFDD_AFDD_LOOKBACK_VALUE` / `OPENFDD_AFDD_LOOKBACK_UNIT` | Rolling lookback per AFDD cycle |

For continuous AFDD across every loaded NF site, leave **`OPENFDD_AFDD_BUILDING_ID`**
and **`OPENFDD_AFDD_BUILDING_IDS` unset** and set `OPENFDD_AFDD_MODE=continuous`
(see [`AFDD_MODES.md`](AFDD_MODES.md)). Compose forwards the names above from
repo-root `.env`; unset names stay unset inside central (`${VAR:-}`).

The **Multi-site NF providers** section above covers site JSON paths and the
narrow `OPENFDD_NF_PROVIDER_CREDENTIALS_ENV` file for per-site `env:NAME`
values. See `.env.example` and [`INGEST_QUEUE.md`](INGEST_QUEUE.md).

Post-re-pin smoke: `./scripts/ops/assert_local_stack_after_repin.sh sha-<7>` reads the build id from `GET /api/version` (anonymous `/api/health` is liveness-only).

## Anti-patterns

- Pasting a public URL for a local-only HTTP stack.
- Claiming “local has TLS” without an explicit Caddy/standalone HTTPS mode (or ops proxy).
- Building central/web images locally on bensbench.
- Re-adding Railway or any cloud web-app host.
- `docker compose down -v`, `docker volume prune`, or `OPENFDD_RESET_DB` as part of an image update.
