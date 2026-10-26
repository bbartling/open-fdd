---
name: openfdd-nf-edge-bench
description: >-
  Use when installing, licensing, upgrading, scanning, or trending a Normal
  Framework (NF) edge box for an Open-FDD site: offline/GA install, device-flow
  license, BACnet scan, trend periods, console auth, API keys, and the portal
  tunnel. Triggers on: NF install, NF license, normal-online.net, BACnet scan in
  NF, point period, point/copy, CONSOLE_PASSWORD, TOKEN_SIGNING_SECRET, API key,
  tls bad record MAC, nf-redis, /opt/nf.
---

# NF edge box (install, license, trend)

`architecture_epoch: portal-timescale-v1`.

NF owns BACnet at the edge. Open-FDD central only reads NF history over HTTPS
(see [`openfdd-nf-provider`](../openfdd-nf-provider/SKILL.md)). Nothing in this
repo polls BACnet any more.

Never write hostnames, LAN or tailnet IPs, passwords, client secrets, or license
JWTs into git. Keep them in `chmod 600` env files outside the repo and refer to
them by path.

## Preflight

```bash
cat /etc/os-release; free -h; df -h /
docker --version && docker compose version
sudo ss -ulpn | grep 47808 || echo "47808 free"   # nothing else on BACnet/IP
```

Stop any other BACnet stack on the box first. Two BACnet clients on UDP 47808 fight.

## Install

- Installer: `curl -fsSL https://raw.githubusercontent.com/normalframework/nf-sdk/master/install.sh | sh`.
  For a licensed GA box use `NF_OFFLINE=1 NF_RELEASE=ga`. Result: `/opt/nf`
  (`docker-compose.yml`, `.env` with `REGISTRY`, `NF_TAG`, `NF_PORT=8080`),
  data in `/var/nf` and `/var/nf-redis`, containers `nf-nf-1` and `nf-redis-1`,
  host network. `nf` and `redis` must use the same `NF_TAG`.
- Upgrades and restarts: `docker compose up -d` in `/opt/nf`. **Never `down -v`**;
  that deletes the trend history and the license.

### Image pull fails with `tls: bad record MAC`

Seen on one site VM: every `docker pull` from the NF registry died mid-layer with
`tls: bad record MAC` (curl to the blob host exited 56) while other large
downloads worked. Lowering `max-concurrent-downloads` did not help. Workaround:

```bash
# on a machine that can pull
docker pull <registry>/<nf image>:<tag>; docker pull <registry>/<redis image>:<tag>
docker save <both images> | gzip > nf_images.tgz
scp nf_images.tgz <site-box>:/tmp/
# on the site box
gunzip -c /tmp/nf_images.tgz | sudo docker load
cd /opt/nf && sudo docker compose up -d --pull never
```

Expect the same for every NF upgrade on that box until its network path is fixed.
The stock installer runs `set -e` and stops at the pull step, so do the license
step separately (below).

## License (device flow)

The installer's online path uses the portal device flow. Same steps by hand:

1. `POST https://portal.normal-online.net/api/v1/license/device/start` with
   `{"version":"<major.minor>"}`. It returns a sign-in link and user code.
   A person signs in and approves. An agent only relays the link and code.
2. Poll `POST .../device/poll` with `{"deviceCode":...}` until `APPROVED`.
3. `POST .../device/complete` with `{deviceCode, mid: <machine info>, version}`
   returns the license.
4. Apply it: `POST http://localhost:8080/api/v1/platform/license` `{"license":...}`.

Check the expiry it reports. Trial/short licenses expire in days; renew before
then or trending stops. The installation UUID becomes the portal URL:
`https://<installation-uuid>.normal-online.net`.

## Scan and trend

```bash
curl -s -X POST localhost:8080/api/v1/bacnet/scan -H 'Content-Type: application/json' \
  -d '{"device":{"targets":[{"lowLimit":0,"highLimit":4194302}],"autoScan":true},"autoImport":true}'
curl -s 'localhost:8080/api/v1/bacnet/scan?status_filter=ANY'   # wait for all DONE
```

- Points: `POST /api/v1/point/query` `{"layer":"hpl:bacnet:1","pageSize":1000,"pageOffset":0}`.
  Match by `attrs.device_id` + `attrs.object_id` (`ai.1`, `ao.3`, `av.20`, `bo.1`),
  never by display name.
- Set the trend period only on the points you want:
  `POST /api/v1/point/copy` `{"indexLayer":"hpl:bacnet:1","outputLayer":"hpl:bacnet:1","uuids":[...],"period":"300s"}`
  returns `updateCount`.
- `autoImport` gives each **device object** (`d.<instance>`) a `900s` period.
  To trend only your list, set those to `"0s"` and confirm with a period count.
- Samples land on period boundaries. Verify with `GET /api/v1/point/data?from.seconds=&to.seconds=&uuids=`
  after two or three periods. `POST` on `/point/data` is a write; never use it to read.
- No BACnet writes unless the owner asks. Periods, tags and quality rules are fine.

## Console auth and API keys

- Console login: put `CONSOLE_USERNAME`, `CONSOLE_PASSWORD`, `TOKEN_SIGNING_SECRET`
  and `ALLOW_ALL_LOCALHOST=false` in `/opt/nf/.env`, pass them to the `nf` service
  with a `docker-compose.auth.yml` override, then
  `docker compose -f docker-compose.yml -f docker-compose.auth.yml up -d`.
  `/api/v1/platform/info` stays public; data APIs return 401 without a token.
- Write root-owned files with `sudo install -m 600 <tmpfile> <dest>`. Do not pipe a
  sudo password and file content through the same stdin (`echo pw | sudo -S tee`):
  when sudo has cached credentials, `tee` writes the password into the file.
- API key for Open-FDD: console **Settings › Authorization › API Keys**, or
  `POST /api/v1/auth/applications` `{"name":"openfdd-central","scopes":[...readonly...]}`
  (`GET /api/v1/auth/scopes` lists them). The secret is shown once. Save
  `NFURL`, `NF_CLIENT_ID`, `NF_CLIENT_SECRET` to a `chmod 600` env file.
  Tokens: `POST {NFURL}/api/v1/auth/token` (client_credentials) needs
  `TOKEN_SIGNING_SECRET` set on the box.
- The portal URL rejects Python's default `urllib` User-Agent with 403. Send an
  explicit `User-Agent` header from scripts.

## Do not

- Do not `docker compose down -v`, prune NF volumes, or rebuild NF images.
- Do not run heavy `docker build` on small edge boxes. Pull prebuilt images.
- Do not print `nf version` output into shared logs; it includes environment values.
