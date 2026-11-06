# NF front door (Caddy) for the Open-FDD plugin

Small Caddy container in front of Normal Framework (NF) on a LAN: the Open-FDD dashboard is open,
the NF console and every write sit behind a login, optional self-signed HTTPS.

## How it fits

- NF's Envoy listens on **loopback only**: in NF's compose set `ENVOY_BIND_ADDRESS=127.0.0.1`
  (NF port is `8090` on small installs, `8080` on others; set `NF_UPSTREAM` and `NF_PORT` to match).
  The portal tunnel, app hooks and the NF MCP keep using loopback.
- Caddy (`caddy:2.11.7-alpine`, host network, `mem_limit: 64m`) binds `LAN_IP` only.

| Request | Access |
|---|---|
| `GET /api/v1/apps/static/*` (the Open-FDD pages, files only) and `/favicon.ico` | open |
| `GET /api/v1/point/data`, `/api/v1/platform/info`, `/api/v1/bacnet/{configuration,local,ports,readproperty}` | open |
| `POST /api/v1/point/query`, `/api/v1/auth/token` (reads; the token call still needs a client id/secret) | open |
| `GET /api/v1/point/updates/data` (live push stream) | open, `flush_interval -1`, Envoy's quiet-stream 504 becomes 204 |
| everything else: NF console, `/api/v1/apps*` (app/hook config), config, every write | **basic auth** |
| `:80` `/` | 302 to `/api/v1/apps/static/<APP_ID>/` (`open-fdd`; set `APP_ID=open-fdd-lite` on a Lite box) |

Rules live in `routes.caddy`, shared by `Caddyfile` (HTTP) and `Caddyfile.tls` (HTTPS).
Without TLS the basic-auth password crosses the LAN in the clear; use `Caddyfile.tls` when that matters.

## Setup

```bash
cp .env.example .env                 # set LAN_IP (this box), NF_UPSTREAM, NF_PORT, APP_ID
cp auth.caddy.example auth.caddy     # then replace its line with a real hash:
docker run --rm caddy:2.11.7-alpine caddy hash-password -p 'choose-a-password'
#   auth.caddy = one line:  admin <hash>      (never commit it; it is gitignored)
docker compose up -d
```

Recreate NF once after setting `ENVOY_BIND_ADDRESS=127.0.0.1` so the LAN port is released for Caddy.
Then browse `http://<LAN_IP>/` (redirects to the dashboard).

## HTTPS (optional)

```bash
mkdir -p certs && openssl req -x509 -newkey rsa:2048 -nodes -days 1095 \
  -keyout certs/server.key -out certs/server.crt -subj "/CN=nf" \
  -addext "subjectAltName=IP:192.0.2.10,DNS:nf.local" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign" -addext "extendedKeyUsage=serverAuth"
```

In `docker-compose.yml` mount `./Caddyfile.tls` as `/etc/caddy/Caddyfile` and uncomment the two
cert volumes; import `certs/server.crt` into client trust stores. `certs/` is gitignored.

## Operate

- Restart after edits: `docker compose restart caddy` (admin API is off, no live reload).
- Validate: `docker run --rm -e LAN_IP=192.0.2.10 -e NF_UPSTREAM=127.0.0.1:8090 -v "$PWD:/etc/caddy:ro" caddy:2.11.7-alpine caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile`
  (needs an `auth.caddy` and, for the TLS file, certs).
- Lost login: write a new hash to `auth.caddy` and restart.
- NF's Envoy ends each pushed stream batch without the final chunk, so Caddy may log
  "unexpected EOF"; `nf.js` treats that as a normal end when values arrived.

More (why not NF's built-in TLS, adding a route, verify checklist, clients, roll back):
[NF operations: front door](../../docs/operations/nf/front-door-caddy.md).
