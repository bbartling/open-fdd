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
| `:80` `/` | 302 to `/api/v1/apps/static/<APP_ID>/` (`APP_ID` placeholder, default `open-fdd`; `open-fdd-lite` on a Lite box, see "The `/` redirect and app ids") |

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

## Which layer rejected me

A 401 can come from Caddy or from NF. Read the `WWW-Authenticate` response header:

```bash
curl -s -i -o /dev/null -D - <front-door-url>/api/v1/apps | grep -i '^www-authenticate'
```

| Header | Layer | What it means |
|---|---|---|
| `Basic realm="restricted"` | **Caddy** | The user or password does not match `auth.caddy`. The request never reached NF. |
| `Basic realm="nf-"` | **NF** | Caddy let it through (or you called NF directly) and NF's own console auth said no. |
| 200 on NF loopback, 401 `restricted` on the front door | Caddy only | NF's login is fine; only the hash in `auth.caddy` is wrong. |
| 401 `nf-` on loopback and on the front door | NF | The password in your env file is not NF's. NF's real login is in NF's own environment (`CONSOLE_USERNAME` / `CONSOLE_PASSWORD`). |

**Caddy and NF must share one user and password** when NF's console auth is on: Caddy checks the login and then
forwards the `Authorization` header to NF, which checks it again. Change one without the other, or copy an env file
from another box, and every deploy fails.

## Login recovery

Never print the password or the hash. Do these on the box that runs NF and Caddy.

1. Test NF alone, on loopback, with NF's own login (replace the port):

   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' -u "$NF_USER:$NF_PASS" http://127.0.0.1:8090/api/v1/apps
   ```

   `200` means NF's login is right and only Caddy's hash needs replacing. Anything else: fix NF's login first.
2. Make a new hash from that password. The password must arrive on stdin **with a trailing newline**; without it
   `caddy hash-password` exits with `EOF` (verified):

   ```bash
   printf '%s\n' "$NF_PASS" | docker run --rm -i caddy:2.11.7-alpine caddy hash-password
   ```

3. Put it in `auth.caddy` as one line `<user> <hash>` (the file is not in git).
4. Validate (see Operate below).
5. Restart Caddy. With `admin off`, `caddy reload` fails with `dial tcp 127.0.0.1:2019: connection refused`; use
   `docker compose restart caddy` (or `docker restart <container>`).
6. Test `GET /api/v1/apps` through the front door with the same login: `200`.

## The `/` redirect and app ids

The bare URL (`:80`, plain-HTTP profile) redirects to `/api/v1/apps/static/{$APP_ID:open-fdd}/`. `APP_ID` is a
placeholder read from the environment when Caddy starts, with `open-fdd` as the default. Set `APP_ID=open-fdd` (full
edition) or `APP_ID=open-fdd-lite` (Lite) in `.env`. After an app rename or an edition swap: back up the `.env`,
change `APP_ID`, validate, restart Caddy. Never hard-code an app id in a Caddyfile copy. Syntax checked with
`caddy adapt`: unset gives `.../open-fdd/`, `APP_ID=open-fdd-lite` gives `.../open-fdd-lite/`. The HTTPS profile's
`:80` block only redirects to HTTPS; the dashboard URL is the same path on the HTTPS port.

## Open pages and NF auth

The `@appStatic` route is "open" **only in Caddy**. If NF's own console auth is also on
(`CONSOLE_USERNAME` / `CONSOLE_PASSWORD`, `ALLOW_ALL_LOCALHOST=false`), NF still answers 401 with `realm="nf-"` to an
unauthenticated GET of `/api/v1/apps/static/<app>/...`, so unauthenticated LAN users cannot load the dashboard even
though Caddy did not ask for a login. NF's login is enforced on every request, so it cannot make just the static
files public. Pick one:

1. **Recommended: Caddy owns the login, NF's console auth is off.** NF is bound to loopback
   (`ENVOY_BIND_ADDRESS=127.0.0.1`), so the only way in from the network is Caddy. Leave `CONSOLE_USERNAME` /
   `CONSOLE_PASSWORD` unset in NF. The open/locked split in `routes.caddy` then does what it says, and the
   two-password divergence (above) cannot happen. Trade-off: anything with a shell on the NF host can reach NF
   without a login; hooks and the portal tunnel already do.
2. **NF auth stays on: do not offer open pages.** Delete the `handle @appStatic`, `@readGet`, `@readPost` and
   `@liveStream` blocks (see Security posture, "To lock them"). Every request then needs the shared login and the
   browser sends it with each call.
3. Relying on the Normal Online login only (the page then uses a Clerk token through the portal) works through the
   portal, not on the LAN.

## Operate

- Restart after edits: `docker compose restart caddy` (admin API is off, no live reload).
- Validate: `docker run --rm -e LAN_IP=192.0.2.10 -e NF_UPSTREAM=127.0.0.1:8090 -v "$PWD:/etc/caddy:ro" caddy:2.11.7-alpine caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile`
  (needs an `auth.caddy` and, for the TLS file, certs). Check both `Caddyfile` and `Caddyfile.tls`; the scratch
  setup is a dummy `auth.caddy` line and a self-signed cert pair (the HTTPS section's command). In Git Bash on
  Windows prefix `docker run` and `openssl` with `MSYS_NO_PATHCONV=1`.
- Lost login: see Login recovery above (new hash, validate, restart).
- Deploying through this front door with a self-signed certificate: give the installer the certificate for that run
  (`nf_app_sync.py --ca-file <crt>` or `--pin-server-cert`). Never disable verification globally
  (`PYTHONHTTPSVERIFY=0`). The certificate's SAN must match the host in the URL.
- `--remove-old` and orphan hook points: see `docs/install.md`. The console has no point-delete route; use the NF MCP
  `delete_points` (dry run first). Never reuse a point uuid on `POST /api/v1/bacnet/local`.
- NF's Envoy ends each pushed stream batch without the final chunk, so Caddy may log
  "unexpected EOF"; `nf.js` treats that as a normal end when values arrived.

More (why not NF's built-in TLS, adding a route, verify checklist, clients, roll back):
[NF operations: front door](../../docs/operations/nf/front-door-caddy.md).

## Optional read-only `pgweb` sidecar (Full edition only)

Full boxes running TimescaleDB can opt in to a read-only `pgweb` inspector behind TLS and Caddy basic auth. It is
**off by default** and **excluded from Lite**.

- `pgweb` sits on a private bridge network (`pgweb_private`) with no published host ports, runs `--readonly --lock-session`,
  and connects with a fixed `PGWEB_DATABASE_URL` using a dedicated `SELECT`-only role (`pgweb-grants.sql`, which locks
  `default_transaction_read_only = on` and `statement_timeout = '10s'`).
- Caddy serves `/pgweb/*` only on HTTPS (`Caddyfile.tls.pgweb`) behind `basic_auth` (`pgweb.caddy`); anonymous requests
  get `401`, and `:80` redirects to HTTPS.
- Because switching Caddy off `network_mode: host` puts it in a bridge network, set `NF_UPSTREAM=host.docker.internal:8090`
  (or the NF host bridge IP if Envoy binds loopback only).

```bash
psql "$PGURL" -v ON_ERROR_STOP=1 -f pgweb-grants.sql   # after creating openfdd_ro with a strong password
# add PGWEB_DATABASE_URL=postgres://openfdd_ro:<password>@host.docker.internal:5432/nf?sslmode=disable to .env
docker compose -f docker-compose.yml -f docker-compose.pgweb.yml --profile pgweb up -d
```
