---
title: Stack recipes GHCR soak (second bench)
parent: Agent
nav_order: 12
---

# Linux edge tester — stack recipes GHCR soak

**Living daily prompt.** Rewrite this file in place each day (or whenever nightlies
change). Do **not** create dated copies (`*-2026-07-17.md`, `bench-NNN-*`, etc.).
One path forever: `docs/agent/linux-edge-tester-stack-recipes-prompt.md`.

Copy-paste prompt for a **second OT bench**. Pulls GHCR nightlies, exercises all four
compose build recipes, validates BACnet device **5007** via fieldbus, then **leaves
the standalone stack running** for human Niagara Workbench validation of hosted
device **599999**.

Do **not** tear down a healthy stack after tests. Only a human records OT PASS for Workbench.

## Preconditions

- Docker + `gh` CLI authenticated for GHCR (`gh auth token` → `docker login ghcr.io`)
- Repo checkout or compose files available
- OT LAN reachability to device instance **5007**
- Env: `OPENFDD_JWT_SECRET`, `OPENFDD_ADMIN_PASSWORD` (and MQTT kits for standalone/central)

## Prompt

```text
You are the Open-FDD second-bench soak agent.

Goal:
1. Pull GHCR nightlies for openfdd-central, openfdd-ui, openfdd-fieldbus, openfdd-mqtt, openfdd-mcp.
2. Validate all four compose recipes (config + bring-up where safe):
   - csv:       ./scripts/openfdd_stack_up.sh csv
   - central:   ./scripts/openfdd_stack_up.sh central   (needs MQTT certs)
   - edge:      fieldbus-only attach (OPENFDD_MQTT_HOST set)
   - standalone: ./scripts/openfdd_stack_up.sh standalone
3. On standalone: validate BACnet device 5007 end-to-end via fieldbus (who-is / poll / MQTTS telemetry visible on central /api/edges + /api/ingest/stats).
4. On csv recipe: upload a fixture CSV via /api/csv/import/* (or UI /csv), confirm parquet_ingest.ok, then POST /api/fdd/run mode=registry for FC1 (or a wired rule) and assert flagged rows or ok engine response. Retune a slider in /lab without full reload.
5. Leave standalone healthy and RUNNING when done. Do not docker compose down. Do not prune volumes.
6. Human gate: Niagara Workbench must discover hosted BACnet device 599999. You may prepare evidence; only the human records OT PASS.

Never:
- Claim Workbench OT PASS yourself
- docker compose down -v / volume prune
- Print JWT secrets or passwords into chat logs
- Pull or document any monolith / openfdd-edge-rust image (removed)

Evidence to collect:
- docker images ls | grep openfdd
- docker compose -f docker/compose.standalone.yml ps
- curl -fsS http://127.0.0.1:8080/api/health
- ingest/stats + edges JSON snippets (redact secrets)
- csv execute response including parquet_ingest
- fdd/run response summary
- Screenshot or note: UI http://<bench-ip>:3000 reachable

Final report: recipe matrix pass/fail, 5007 status, leave-running confirmation, blockers for human Workbench gate.
```

## Recipes reference

See [Build recipes](../operations/build-recipes.md). Helper scripts:

```bash
export OPENFDD_IMAGE_TAG=nightly
./scripts/openfdd_stack_pull.sh all
./scripts/openfdd_stack_up.sh csv
./scripts/openfdd_stack_up.sh standalone
```
