---
title: Install
nav_order: 2
---

# Install Open-FDD on a Normal Framework box

From a fresh NF box to Open-FDD in one push. App source: [`nf-app/`](https://github.com/bbartling/open-fdd/tree/master/nf-app).
For the small-box edition see [Lite](lite.html).

## 1. Prerequisites

- A **licensed NF 3.10 or newer** (a free-tier license is enough) reachable on your LAN.
- A **console login** on that NF (`CONSOLE_USERNAME` / `CONSOLE_PASSWORD`). Deploying needs the local console API;
  the remote portal token is read-only.
- Python 3 (standard library only) on the machine you deploy from, and this repo checked out.
- On small boxes (1 GB Pi) run nothing heavy on the box: build, test and deploy from another PC.

## 2. Model the points in NF

Open-FDD reads sites, equipment and points from NF's Haystack model. Nothing is configured in the app.
See [Modeling](modeling.html). The FDD tab shows which rule inputs are still missing so you can fix the model
in NF and reload.

## 3. Deploy with `nf_app_sync.py`

Create an env file **outside git** (placeholders shown):

```
NF_CONSOLE_URL=http://192.0.2.10:8090
CONSOLE_USERNAME=admin
CONSOLE_PASSWORD=change-me
```

```bash
python3 scripts/nf/hooks/nf_app_sync.py --env ~/.secrets/nf_console.env push nf-app/app.json
# UI only, no hooks:     ... push nf-app/app.json --skip-hooks
# files + one hook:      ... push nf-app/app.json --hook fdd
# run a hook now:        ... run nf-app/app.json --hook fdd
# compare box vs repo:   ... diff nf-app/app.json
```

`push` creates or updates the app, uploads the files, deploys the hooks and restarts. Open
`http://<nf-host>:<port>/api/v1/apps/static/open-fdd/`. NF derives the app id from the **name**, so
`application.id` in `app.json` must equal the slug of `application.name` (CI checks it).

## 4. Alternative: deploy with the NF MCP server

From an MCP client (for example Claude Code) connected to the NF MCP server:

1. `connect` with the site uuid; confirm the site is healthy.
2. `manage_app` `create` with the name `Open-FDD` (id `open-fdd`), Node runtime, scopes from `nf-app/app.json`.
3. `manage_app` `write_file` for each entry in the `files` map of `nf-app/app.json`.
4. `manage_hooks` / `deploy_hook` for each entry in `hooks` (`weather`, `fdd`, `sparql`).
5. `manage_app` `restart`; run a hook once with `manage_hooks` `run` (it needs the hook **uuid**, not its name).

`write_file` uploads whole files and the MCP session can expire mid-task (`connect` again). Large files, such as
the vendored ECharts, are better pushed with `nf_app_sync.py`.

## 5. Optional: Caddy front door

Keeps the dashboard open on the LAN but puts the NF console and every write behind a login, with optional
self-signed HTTPS. See the
[`deploy/nf-caddy` README](https://github.com/bbartling/open-fdd/tree/master/deploy/nf-caddy). In short:

1. In NF's compose set `ENVOY_BIND_ADDRESS=127.0.0.1` and recreate NF once.
2. Copy `.env.example` to `.env` (`LAN_IP`, `NF_UPSTREAM`, `NF_PORT`) and create `auth.caddy` with a password hash.
3. `docker compose up -d`.

Once NF is behind Caddy, later pushes run on the NF host against loopback, or go through the Caddy URL with its
basic-auth user (`/api/v1/apps*` is locked). Reasoning, safe order, verify checklist and client setup:
[Front door](operations/nf/front-door-caddy.html). Refreshing or upgrading NF itself:
[Upgrade NF](operations/nf/nf-upgrade-compose.html).

## 6. Remote access (Normal Online portal)

Nothing to configure. When `/api/v1/platform/info` reports `IAM_NF_CLERK`, the page loads clerk-js and sends
`Clerk.session.getToken({template:"ConsoleJWT"})` with its API calls, so the same UI works on the LAN and through
the portal. Through the portal, `/api/v1/bacnet/*` is not readable with API-key tokens; the BACnet tab needs the LAN.

## 7. Profiles

| Profile | Box | FDD engine |
|---|---|---|
| edge-lite | 1 GB or more (2 GB recommended) | SQLite-WASM (vendored sql.js, about 60 MB); the pack is translated and matches Postgres on all rules in CI |
| full | 4 GB or more | PGlite (real Postgres in WASM, about 300 MB); `engine: "auto"` picks it when NF reports enough RAM |
| full + TimescaleDB | larger hosts | the Postgres pack runs inside NF's TimescaleDB connector database; results and long-range history stay there, with a size cap (default 100 GB). See [`nf-app/timescale`](https://github.com/bbartling/open-fdd/tree/master/nf-app/timescale) |

Which host gets which edition: [Lite or full](operations/nf/lite-vs-full.html).

## 8. Verify

- [ ] `nf_app_sync.py ... diff nf-app/app.json` reports no differences.
- [ ] The dashboard loads with no red errors in the browser console.
- [ ] Overview cards show live values; Charts draws history.
- [ ] Points lists your tagged points; the FDD tab lists no unexpected missing roles.
- [ ] Model and RDF exports Turtle without dangling references.
- [ ] The weather hook ran (global variables update every 20 minutes).
- [ ] Through the portal, the dashboard loads and shows data.

## 9. Troubleshooting

- **Old page after a deploy:** NF caches app static files for 5 minutes. `nf_app_sync.py` stamps asset URLs; otherwise reload with `?v=N`.
- **App not found / wrong id:** see the id rule in step 3.
- **Hooks return 401:** once NF login is enabled the app needs `auth.apiKey.scopes` in `app.json`.
- **Intermittent empty 403 from `/api/v1/auth/token`:** retry.
- **Live values stop behind a proxy:** the stream route needs `flush_interval -1` (included in `deploy/nf-caddy`).
- **Anything odd in NF itself:** [NF gotchas](operations/nf/nf-gotchas.html).
- **Check values against the BACnet wire:** [BACnet validation](operations/nf/bacnet-validate.html).
- **1 GB Pi restarts:** check the power supply (`vcgencmd get_throttled`); keep Caddy at `mem_limit: 64m`.
