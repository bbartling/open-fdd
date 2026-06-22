# Agent Guide

This repository is Rust-only. Use the JSON API first; shell scripts are only for bootstrap/update.

## Start session

```bash
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"sub":"agent","role":"agent"}' | jq -r .access_token)"

curl -s http://127.0.0.1:8080/api/building/checkin \
  -H "Authorization: Bearer $TOKEN" | jq .

curl -s http://127.0.0.1:8080/api/agent/tools \
  -H "Authorization: Bearer $TOKEN" | jq .
```

## Never

- delete `workspace/`
- run `docker compose down -v`
- run `docker volume prune`
- print `.env` or token secrets
- expose the API outside LAN/Tailscale
- write BACnet points unless the user explicitly approved it

## Safe scripts

```bash
./scripts/openfdd_edge_bootstrap.sh
./scripts/openfdd_site_backup.sh
./scripts/openfdd_site_update.sh
./scripts/openfdd_check_ghcr_platform.sh
```

## Assignment rule

All agent-created point mappings, FDD rule bindings, historian storage refs, external refs, and CDL algorithm bindings must go through Haystack IDs.

Use:

```text
GET  /api/model/assignments
POST /api/model/assignments/save
POST /api/model/assignments/resolve
GET  /api/control/cdl/bindings
POST /api/control/cdl/bindings/save
```

Do not bind FDD or CDL directly to BACnet, Modbus, JSON API, or remote Haystack sources. Bind drivers to Haystack IDs first, then bind rules/algorithms to those IDs.
