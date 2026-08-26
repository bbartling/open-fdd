---
name: openfdd-stack-ghcr
description: >-
  Use when pulling, rebuilding, or verifying Open-FDD GHCR stack images.
  Test channel is nightly. Triggers on: nightly, openfdd-central, openfdd-web,
  GHCR, openfdd_stack_up, OPENFDD_IMAGE_TAG.
---

# Stack GHCR (nightly channel → immutable verify)

Full protocol: [`CONTAINER_AGENT.md`](../../CONTAINER_AGENT.md).

`nightly` is the channel selector. Qualification pulls `sha-<commit>` for
central/web/fieldbus/mqtt, asserts digests match `:nightly`, then starts the
stack with `OPENFDD_IMAGE_TAG=sha-<commit>`.

**Newest means OCI `created`, not the word nightly.** Run
`./scripts/ghcr_newest_by_created.py openfdd-central` before claiming tip.

**Unmerged `frontend/web` → local web only.** `openfdd_stack_up.sh` refuses
GHCR web when the tree drifted (override `OPENFDD_ALLOW_STALE_GHCR_WEB=1`).
Never paste a Caddy login until `./scripts/openfdd_demo_gate.sh` exits 0.

Product central image is Rust/debian only (no Python).

**Low-RAM hosts:** never local `docker build` for stack images. Prune unused
images before pull; wait for GH Actions publish; then pull +
`openfdd_stack_up.sh … --no-pull`. See [`CONTAINER_AGENT.md`](../../CONTAINER_AGENT.md).

Nightly publish (`ghcr-openfdd-stack.yml`) stamps `OPENFDD_GIT_SHA` into central
and writes web `version.json` `{ version, git, image_tag, service: openfdd-web }`.
Optional extra image tag `:3.3.2-n<run_number>` sits **beside** `:nightly` /
`:sha-*`. UI revision comes from central `/api/health` first.

For Railway, use the same GHCR `openfdd-web` image and set
`OPENFDD_CENTRAL_UPSTREAM=openfdd-central.railway.internal:8080` (assuming the
central service uses that name). Tip images resolve upstream DNS lazily
(`OPENFDD_NGINX_RESOLVER=auto`) so nginx does not die when `.railway.internal`
is not ready at process start. Deploy **central healthy first**, then mqtt (for
cloud MQTTS hubs), then web. Live OT hubs should include `openfdd-mqtt` by
default — MQTTS is the cloud transport; fieldbus stays on-prem.
Set `OPENFDD_AGENT_PASSWORD` on central for FDD AI / MCP (username `agent` →
operator JWT); do not put `OPENFDD_ADMIN_PASSWORD` into Cursor MCP config.
Admins may `POST /api/auth/agent-token` for short-lived operator JWTs.
Edge kits: operator/admin `POST /api/mqtt/edge-kits` or Operations MQTT UI
(ZIP never includes CA private key).
Local Compose keeps the default `central:8080`. Do not claim a Railway-ready
nightly until stack + MCP GHCR publish jobs are green and the target `sha-*`
digest resolves.

Hourly CSV append is API `POST /api/csv/import/package/append` on central (GHA image), not a local compile.

After GHCR publish, poll with `./scripts/ghcr_watch_central.py` (legacy shim: `wattlab_parity_watch_ghcr.py`), then maint pull + `synthetic_59_*` chain — not vibe19 dump-parity.

**BUILDING_50 stream sim:** `scripts/csv_flood_afdd_routine_sim.py` — see [`docs/agent/CSV_FLOOD_AFDD_ROUTINE.md`](../../docs/agent/CSV_FLOOD_AFDD_ROUTINE.md).

Workflow: `ghcr-openfdd-stack.yml` (retargets nightly on master).
MCP: separate `rust-ghcr-mcp.yml`.
