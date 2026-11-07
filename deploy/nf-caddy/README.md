# NF front door (Caddy) for the Open-FDD plugin

Small Caddy container in front of Normal Framework (NF) on a LAN: the Open-FDD dashboard and its
read-only API calls are open (an explicit choice, see Security posture), the NF console and every write
sit behind a login; plain HTTP for a trusted LAN, self-signed HTTPS for production.

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
| `GET /api/v1/point/updates/data` (live push stream) | open, `flush_interval -1`, Envoy's quiet-stream 504 becomes 204 (see "Live stream") |
| everything else: NF console, `/api/v1/apps*` (app/hook config), config, every write | **basic auth** |
| `:80` `/` | 302 to `/api/v1/apps/static/<APP_ID>/` (`open-fdd`; set `APP_ID=open-fdd-lite` on a Lite box) |

Rules live in `routes.caddy`, shared by `Caddyfile` (HTTP) and `Caddyfile.tls` (HTTPS).

## Security posture (read this before exposing it)

- **Plain HTTP (`Caddyfile`) is for a trusted LAN or a lab only.** Basic auth over HTTP sends the
  password (base64, not encrypted) on every request, and anyone on the same network segment can
  read it and everything else. **HTTPS (`Caddyfile.tls`) is the production profile**: use it for
  anything beyond a bench, and never publish the HTTP port to the internet or a shared network.
- **The open read routes are an explicit public-read choice.** Anyone who can reach the LAN port can,
  without a login, read: the Open-FDD pages (`GET /api/v1/apps/static/*`, `/favicon.ico`), point
  history and values (`GET /api/v1/point/data`, `POST /api/v1/point/query`, the live stream
  `GET /api/v1/point/updates/data`), `GET /api/v1/platform/info`, and the BACnet server's
  `GET /api/v1/bacnet/{configuration,local,ports,readproperty}`. They cannot change anything, but
  the data (equipment, point names, trends, BACnet configuration) is readable by the whole network.
  `POST /api/v1/auth/token` is open too, but still needs a valid client id/secret.
- **To lock them**, move the routes into the auth block: in `routes.caddy` delete the
  `handle @appStatic`, `handle @readGet`, `handle @readPost` and `handle @liveStream` blocks (and
  keep the final `handle { basic_auth ... }`), so every request needs the login. The pages then
  work only for a signed-in browser (the browser sends the same basic-auth credentials to the
  API calls the page makes); automated clients must send the Authorization header. Restart Caddy.
  To lock only some (for example keep the pages open but not the BACnet reads), delete just those
  paths from the matchers.
- The 504-to-204 rewrite on the live stream is deliberate: see "Live stream" below.

## Access log

`routes.caddy` writes one JSON line per request to `/var/log/caddy/access.log` (the `caddy_logs`
volume): rolled at 5 MiB, 5 files kept, nothing older than 30 days. The `Authorization`,
`Proxy-Authorization`, `Cookie` and `Set-Cookie` headers and the query parameters `token`,
`access_token`, `id_token`, `refresh_token`, `jwt`, `api_key`, `apikey`, `client_secret`, `secret`,
`password`, `sig` and `code` are replaced by `REDACTED` before they are written (Caddy's `filter`
encoder). `/favicon.ico` and the live stream are not logged (the stream reconnects every ~15 s per
open tab). Read it with `docker compose exec caddy tail -n 50 /var/log/caddy/access.log`. If you
add a route that carries a secret under another parameter name, add it to the `query` filter.

## Live stream (why 504 becomes 204)

`GET /api/v1/point/updates/data` is NF's push stream. NF's Envoy closes a stream that has been
quiet for about 15 s with an `upstream request timeout` (HTTP 504). That is its normal idle close,
and `nf.js` simply reopens the stream. Caddy answers an empty 204 for an upstream 504 **on that one
route** so the browser does not log a red error for every routine reconnect. This does not mask a
real outage: if NF is down or unreachable the upstream does not answer at all and Caddy returns 502
(or the connection is refused/reset), the page's reconnects fail and it shows "live" off with a
growing back-off (2 s up to 60 s). What it does hide is an Envoy 504 for another reason on this
route (for example an overloaded NF): it looks the same as an idle close.

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

## HTTPS (the production profile)

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
  (needs an `auth.caddy` and, for the TLS file, certs). Check both `Caddyfile` and `Caddyfile.tls`; the scratch
  setup is a dummy `auth.caddy` line and a self-signed cert pair (the HTTPS section's command). In Git Bash on
  Windows prefix `docker run` and `openssl` with `MSYS_NO_PATHCONV=1`.
- Lost login: write a new hash to `auth.caddy` and restart.
- NF's Envoy ends each pushed stream batch without the final chunk, so Caddy may log
  "unexpected EOF"; `nf.js` treats that as a normal end when values arrived.

More (why not NF's built-in TLS, adding a route, verify checklist, clients, roll back):
[NF operations: front door](../../docs/operations/nf/front-door-caddy.md).
