---
title: Local deployment (firewall hub)
parent: Operations
nav_order: 5
---

# Local deployment — firewall / on-prem hub

Open-FDD is **local-first**. The typical bench path is a GHCR-pulled Compose stack on a LAN host (e.g. bensbench) behind a firewall — **not** a public internet appliance.

## Threat model (current)

| Fact | Implication for agents |
|------|------------------------|
| Dashboard + API are **plain HTTP** on the LAN | Expect `http://127.0.0.1:3000` (UI) and `http://127.0.0.1:8080` (API). **No product TLS termination on local Compose yet.** |
| Intended exposure | Host firewall / VPN / OT LAN only. Do **not** advertise local `:3000`/`:8080` to the public internet. |
| Railway vs local | Railway public **web** may terminate TLS at the edge; local stack does **not** mirror that. Private Railway mesh to central is also plain HTTP on `*.railway.internal`. |
| Auth still required | Admin / agent JWT on central even over HTTP — never skip auth “because it’s local.” |

If a customer needs HTTPS on-prem, that is an **ops add-on** (reverse proxy / Caddy with certs in front of Compose) — not the default `react-ot` recipe today. Do not claim local TLS is shipped.

## Recipes

| Recipe | Compose | Use |
|--------|---------|-----|
| `react` | web + central (+ optional) | CSV / package lab UI |
| **`react-ot`** | + fieldbus + mqtt | OT soak / nightly stress (default bench) |

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

## Dual pipeline

- **Local** = Pipeline B (firewall dashboard + optional local OT).
- **Railway** = Pipeline A (bosspi → cloud MQTTS). Bootstrap: [`RAILWAY_DEPLOYMENT.md`](RAILWAY_DEPLOYMENT.md).

Same tip `sha-*` both sides. Do not cross-wire for parity.

## MCP against local central

```bash
export OPENFDD_API_BASE=http://127.0.0.1:8080
# Mint agent JWT — see mcp/INSTRUCTIONS.md
export OPENFDD_MCP_TOKEN=…
```

Use `http://` (not `https://`) for local Compose. See [`mcp/README.md`](../../mcp/README.md).

## Stress on local

After re-pin, run the stress matrix in [`STRESS_CLOSEOUT.md`](STRESS_CLOSEOUT.md) (`run_all`, synth59, gate 17, …). STRESS 7 (ZAP) targets **Railway public URL**, not the local HTTP dashboard.

## Anti-patterns

- Pasting a public URL for a local-only HTTP stack.
- Claiming “local has TLS” without an explicit fronting proxy.
- Building central/web images locally on bensbench.
- Pointing bosspi at local mqtt during Railway parity stress.
