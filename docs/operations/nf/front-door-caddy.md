---
title: Front door (Caddy)
parent: NF operations
nav_order: 2
---

# Front door: Caddy in front of NF

The files and the route table live in
[`deploy/nf-caddy/`](https://github.com/bbartling/open-fdd/tree/master/deploy/nf-caddy) (its README is the setup
reference). This page adds the reasoning, the safe order of steps, a verify checklist and how clients connect.

## Why a proxy and not NF's own TLS

NF 3.10 has one TLS switch: `TAILSCALE_HTTPS=1` plus a certificate mounted at `/tailscale-certs/server.crt` and
`server.key` (any certificate works, self-signed included). It turns Envoy's **only** listener into HTTPS, and that
breaks two things:

- **App hooks.** The hook runtime gets `NFURL=127.0.0.1:<PORT>` with no scheme and calls NF over plain HTTP.
  Once the listener is HTTPS, `sdk.http` fails.
- **The portal tunnel.** The bundled `cloudflared` runs a portal-managed config whose ingress is
  `http://localhost:<PORT>`. It would answer 502 unless that file is edited by hand.

NF's own login (`CONSOLE_USERNAME` / `CONSOLE_PASSWORD`, or an OIDC provider) is enforced on every request,
including the API calls the app pages make, so it cannot give "pages open, console locked". So NF stays on plain
HTTP bound to loopback (`ENVOY_BIND_ADDRESS=127.0.0.1`, an Envoy setting in NF's environment), and Caddy owns the
LAN side and does the open/locked split.

```
LAN browser / scripts --https:443--> Caddy --http--> NF Envoy 127.0.0.1:<port>
                       http:80 redirects                 ^        ^        ^
                              portal tunnel (cloudflared)  hooks (NFURL)   NF MCP via portal
```

## Steps, in a safe order

1. Back up NF's compose file and `.env` (`cp -p docker-compose.yml docker-compose.yml.bak-<timestamp>`).
2. Prepare Caddy as in the `deploy/nf-caddy` README (`LAN_IP`, `NF_UPSTREAM`, `NF_PORT`, `APP_ID`, an `auth.caddy`
   hash, optional certificate). If Caddy listens on a port NF does not use (HTTPS on 443), start it now and test it
   before closing NF. If Caddy takes NF's own LAN port (plain HTTP on 8090), it cannot start until NF stops
   listening there, so do step 3 first and start Caddy right after.
3. Add `ENVOY_BIND_ADDRESS=127.0.0.1` to NF's environment and recreate NF (`docker compose up -d nf`). Expect a
   few seconds of outage; one BACnet poll may be skipped. Never use `docker compose down -v`.
4. Verify (below), then check the portal and a hook.

To roll back, restore the NF compose backup, `docker compose up -d nf`, then `docker compose down` in the Caddy
folder.

## Adding a route

A page that needs another read-only endpoint: add its path to `@readGet` (GET) or `@readPost` (POST that only
reads) in `routes.caddy`, restart Caddy (`docker compose restart caddy`; the admin API is off so there is no live
reload). **Never open a write method.** Everything not listed falls through to basic auth.

## Verify

Replace `<nf-host>` and the credentials; add `--cacert <cert>` when using the self-signed HTTPS variant.

```bash
H=http://<nf-host>:8090      # or https://<nf-host>
curl -s -o /dev/null -w '%{http_code}\n' $H/api/v1/apps/static/open-fdd/     # 200 (open)
curl -s -o /dev/null -w '%{http_code}\n' $H/                                 # 401 (console is locked)
curl -s -o /dev/null -w '%{http_code}\n' -u admin:<password> $H/api/v1/apps  # 200 (with login)
curl -s -m 5 -o /dev/null -w '%{http_code}\n' http://<nf-host>:8090/         # refused if NF no longer listens on the LAN
```

- Run an app hook once (NF console, or `manage_hooks run` with the hook uuid in the NF MCP): it should succeed,
  because hooks use loopback.
- The portal URL should answer 401 from the gateway when not signed in, not 502.
- A fresh sample arrives from a BACnet point after the NF restart.

## Login problems

Which layer said 401, recovery (re-hash, validate, restart) and why open static routes can still 401 behind NF's own
auth: see the [Caddy README](https://github.com/bbartling/open-fdd/tree/master/deploy/nf-caddy) sections "Which layer
rejected me", "Login recovery" and "Open pages and NF auth".

## Clients

- **Python tools** in [`scripts/nf/tools/`](https://github.com/bbartling/open-fdd/tree/master/scripts/nf/tools):
  set `NF_LAN_URL=https://<nf-host>` and `NF_CA_FILE=<cert>`. The certificate is added to the system CAs, so the
  portal path still verifies.
- **Browsers and Windows PowerShell 5.1:** import the certificate as a trusted root on that PC, for example
  `Import-Certificate -FilePath nf-ca.crt -CertStoreLocation Cert:\CurrentUser\Root`. Do it yourself; it is a
  trust decision.
- **Deploys** (`nf_app_sync.py`) run on the NF host against loopback, or through the Caddy URL with the basic-auth
  user, because `/api/v1/apps*` is locked.

## Details worth knowing

- The self-signed certificate needs the Subject Alternative Names clients use (IP and host names), and the
  `CA:TRUE` and `keyCertSign` extensions in the README command so Windows accepts it as a trusted root.
- The open routes also cover `/favicon.ico`; without it every page load logs a 401.
- Caddy's `bind {$LAN_IP}` keeps it off loopback, so NF's own port stays free for the tunnel and hooks. If the
  host's IP changes, update `LAN_IP` and restart.
- The live-values route is open and uses `flush_interval -1`; Envoy ends a quiet stream with a 504 after about
  15 seconds, which Caddy turns into 204 so browsers log no red errors.
- If the password is lost, write a new bcrypt hash into `auth.caddy` and restart Caddy; NF itself has no login
  in this setup.
- Caddy needs about 1 to 6 MB of RAM at idle; `mem_limit: 64m` is generous even on a 1 GB Pi.
- Remote access does not need this: the Normal Online portal tunnel is dialed out by NF. Keep BACnet (UDP 47808)
  on the LAN; Caddy forwards HTTP only.
