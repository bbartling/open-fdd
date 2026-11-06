---
title: Upgrade NF (compose)
parent: NF operations
nav_order: 3
---

# Upgrade or refresh NF with Docker Compose

NF installed with the official installer runs from a compose project (for example `/opt/nf` or `~/nf`): an `nf`
container and a `redis` container, both using the same `NF_TAG`, on host networking. These notes cover pulling
images safely. They apply to the NF box only; Open-FDD itself is redeployed with `nf_app_sync.py`
([Install](../../install.html)).

## Where the data lives

| What | Container path | Host path |
|---|---|---|
| NF config, apps, hook files | `/var/nf` | the folder behind `NF_DATA_DIR` in NF's `.env` |
| Redis (latest values and the 7-day history) | `/data` | the folder behind `NF_REDIS_DIR` |

These host folders are usually under the compose directory, **not** `/var/nf` on the host. Check
`docker compose config` or the `.env`. Open-FDD's source is in git, but anything only on the box (model tags, API
keys, quality rules) is in these folders and in NF's cloud config backup, so back them up first.

## Same-tag pull (refresh, no version change)

```bash
cd <nf-compose-dir>
cp -p docker-compose.yml docker-compose.yml.bak-$(date +%Y%m%d-%H%M)   # and .env
docker compose pull
docker compose up -d
```

If the registry still serves the same image for the tag, `up -d` does **not** recreate the containers (uptime keeps
counting) and no data files change. That is the expected result; it proves the pull path and credentials work.

## Version change (retag)

1. Confirm the new tag exists in **your** registry and is the intended release. Do not retag to a name you have not
   seen listed.
2. Back up the compose file and `.env`; make sure NF's config backup is current (console, Settings, Backup) and
   copy `NF_DATA_DIR` if you can stop NF briefly.
3. Change `NF_TAG` once; it must be the same for `nf` and `redis`.
4. `docker compose pull && docker compose up -d`. Never `docker compose down -v`.
5. Check the console loads, the license is valid, BACnet points keep polling, hooks run
   (`nf_app_sync.py status`), and the portal URL still answers.
6. Roll back by restoring the compose backup and running `docker compose up -d` again.

## After any pull

Confirm the portal path and the API still work end to end, not just the container state:

```bash
python3 scripts/nf/tools/nf_portal_sensors.py portal --env ~/.secrets/nf_api.env --tags temp,sensor
```

It reads live points through the Normal Online tunnel (Cloudflare) using an API key, which exercises the tunnel, the
gateway and the model in one go.

## Notes

- `nfcli` is not in the 3.10 images. Backups are in the console (Settings, Backup; System has Backup and Restore).
- **Do not paste `nf version` or environment dumps into tickets or chat.** They print NF's environment, including
  the cloud backup URL with its write signature ([NF gotchas](nf-gotchas.html)).
- NF's cloud config backup uploads about once a day; it contains configuration (BACnet config, objects, config keys,
  equipment types, layers, connections, workflows), **not** the Redis history and not app files.
- Docker builds and heavy images do not belong on a small host; pull images, never build there.
