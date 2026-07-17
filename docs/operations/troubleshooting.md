---
title: Troubleshooting
parent: Operations
nav_order: 12
---

# Troubleshooting

## Central not healthy

```bash
docker compose -f docker/compose.standalone.yml ps
docker compose -f docker/compose.standalone.yml logs central --tail 100
curl -s http://127.0.0.1:8080/api/health | jq .
./scripts/openfdd_health_check.sh
```

## Login fails

- Confirm `workspace/auth.env.local` exists and permissions are `600`
- Recreate central after auth changes: `docker compose -f docker/compose.standalone.yml up -d --force-recreate central`
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
docker manifest inspect ghcr.io/bbartling/openfdd-central:nightly
OPENFDD_IMAGE_TAG=3.3.0 ./scripts/openfdd_stack_up.sh standalone
```

## After bad update

```bash
tar -xzf ~/openfdd-backups/latest/workspace-full.tgz -C ~/open-fdd
./scripts/openfdd_stack_up.sh standalone --no-pull
```

## Get help

- [GitHub Issues](https://github.com/bbartling/open-fdd/issues)
- [Discord](https://discord.gg/Ta48yQF8fC)
