---
title: Troubleshooting
parent: Operations
nav_order: 12
---

# Troubleshooting

## Bridge not healthy

```bash
docker compose ps
docker compose logs openfdd-bridge --tail 100
curl -s http://127.0.0.1:8080/api/health | jq .
./scripts/openfdd_rust_edge_validate.sh
```

## Login fails

- Confirm `workspace/auth.env.local` exists and permissions are `600`
- Recreate bridge after auth changes: `docker compose up -d --force-recreate openfdd-bridge`
- Check `GET /api/auth/status`

## No historian data in plots

1. Confirm driver poll status (`/api/bacnet/poll/status` or Modbus equivalent)
2. Verify assignments in **Model → FDD mapping**
3. Check `workspace/data/historian/` for Feather files
4. Use **Historian storage** tab for partition summary

## CSV import rejected

- Run preflight: `POST /api/csv/import/preflight`
- Read `agent_hints` in response
- Check `GET /api/ingest/contract` for required columns

## BACnet discover empty

- Commission container must use `network_mode: host`
- Pi/host NIC on BACnet subnet
- Review `workspace/bacnet/commissioning/commission.env`

## Wrong GHCR architecture

```bash
./scripts/openfdd_rust_check_ghcr_platform.sh
NEW_TAG=3.2.4 OPENFDD_DOCKER_PLATFORM=linux/arm64 ./scripts/openfdd_rust_site_update.sh
```

## After bad update

```bash
tar -xzf ~/openfdd-backups/latest/workspace-full.tgz -C ~/open-fdd
docker compose up -d --force-recreate
```

## Get help

- [GitHub Issues](https://github.com/bbartling/open-fdd/issues)
- [Discord](https://discord.gg/Ta48yQF8fC)
