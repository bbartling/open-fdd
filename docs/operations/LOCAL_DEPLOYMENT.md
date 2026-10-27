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
2. Add those names to the gitignored repo-root `.env`. `docker/compose.local.yml`
   forwards provider-related variables into `central` by name (Wave 1a); add a
   new `NF_CLIENT_*` pair to `.env` when you add a site — do not commit secrets.
3. Mount the sites directory read-only on central. The default local overlay
   binds `../scripts/nf` at `/config/nf:ro`. Prefer a host path outside the
   checkout, for example bind `~/.config/openfdd/sites` to `/config/nf/sites:ro`
   in a personal compose override, and set
   `OPENFDD_PROVIDER_SITES=/config/nf/sites` (directory) or a comma-separated
   list of files under that mount.
4. Restart central after config changes. `GET /api/providers/sites` lists each
   loaded site; a missing env ref fails only that site (`auth_not_configured`).
5. After onboarding, run
   `python3 scripts/nf/check_portal_fresh.py --env <secrets.env> --sites <site.json> --points <probes.json>`
   per portal (see [`scripts/nf/README.md`](../../scripts/nf/README.md)).

## MCP against local central

```bash
export OPENFDD_API_BASE=http://127.0.0.1:8080
# Mint agent JWT — see mcp/INSTRUCTIONS.md
export OPENFDD_MCP_TOKEN=…
```

Use `http://` (not `https://`) for local Compose. See [`mcp/README.md`](../../mcp/README.md).

## Stress

Closeout runs on an owned local stack (Codex-owned qualification). The Railway public-URL closeout in [`STRESS_CLOSEOUT.md`](STRESS_CLOSEOUT.md) is historical.

## Data-safe updates

`./scripts/openfdd_stack_up.sh` and `./scripts/openfdd_maint_update_resume.sh` reuse the `openfdd-timescale` named volume. They do not drop, truncate, or re-seed it. Postgres init SQL in `docker/compose.timescale.yml` runs only when that volume is empty. Central startup applies the same SQL forward-only (`CREATE … IF NOT EXISTS`) and leaves existing `sample` rows in place.

Maintenance prunes stopped containers and dangling images. It does not prune volumes. Volume prune requires `./scripts/openfdd_docker_maintenance.sh --prune-volumes --i-understand-data-loss` (or `--prune-volumes` with `OPENFDD_ALLOW_DESTRUCTIVE_DB=1`).

Leave `OPENFDD_RESET_DB` unset on updates. A one-time historian purge is `scripts/timescale/purge_historian.py` with a fresh `OPENFDD_RESET_DB` token and `OPENFDD_ALLOW_DESTRUCTIVE_DB=1` (or `--reset-db` and `--i-understand-data-loss`). The same token does not purge again. Central startup uses that same rule and refuses a token that lacks the allow flag. Building 50 reseed (`scripts/timescale/auto_seed.py`) copies into an empty site. It deletes that site only when `OPENFDD_SEED_FORCE=1` and `OPENFDD_ALLOW_DESTRUCTIVE_DB=1` are both set.

## Anti-patterns

- Pasting a public URL for a local-only HTTP stack.
- Claiming “local has TLS” without an explicit Caddy/standalone HTTPS mode (or ops proxy).
- Building central/web images locally on bensbench.
- Re-adding Railway or any cloud web-app host.
- `docker compose down -v`, `docker volume prune`, or `OPENFDD_RESET_DB` as part of an image update.
