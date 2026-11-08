---
title: Install
nav_order: 2
---

# Install Open-FDD on an existing NF site

One page: pick an edition, get the files, log in, reach the box, run one command, upgrade, uninstall, and fix what
goes wrong. App source: [`nf-app/`](https://github.com/bbartling/open-fdd/tree/master/nf-app) (full) and
[`lite/`](https://github.com/bbartling/open-fdd/tree/master/lite). Nothing here is site specific; the app reads the
site, equipment and points from NF's Haystack model.

## 1. Pick the edition

| | Full (`nf-app/`, app id `open-fdd`) | Lite (`lite/`, app id `open-fdd-lite`) |
|---|---|---|
| Box | 2 GB or more RAM for the SQLite engine, 4 GB or more for PGlite, larger hosts for TimescaleDB | **about 1 GB (Raspberry Pi 3 class)** |
| Includes | 77 SQL fault rules, RCx charts, CSV, RDF and SPARQL, analytics hook | Dashboard, charts, weather, BACnet mirror |

Rule of thumb: a 1 GB box gets Lite, anything bigger gets full. Never run builds, `npm install` by hand or tests on a
small box; deploy from another machine. More: [Lite or full](operations/nf/lite-vs-full.html).

## 2. Get the files

Clone the repository on any PC (not the NF box):

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
```

A release zip of the same tree works too (unzip and `cd` in). The installer is plain Python 3 (standard library
only), so there is nothing to build. Clone is the simpler path because upgrading is then `git pull`.

## 3. Credentials

Deploying needs the **local NF console login**, not a portal key.

- Console URL: `http://<nf-host>:<port>` (NF listens on 8080 on most installs, 8090 on small ones), or the HTTPS
  front door URL if you run the [Caddy front door](https://github.com/bbartling/open-fdd/tree/master/deploy/nf-caddy).
- Login: the `CONSOLE_USERNAME` / `CONSOLE_PASSWORD` set in NF's own environment. If a Caddy front door is in
  front, it must use **the same** user and password (see Troubleshooting, bug 1).
- The Normal Online portal API key (`NF_CLIENT_ID` / `NF_CLIENT_SECRET`) is **read-only** and cannot push files or
  hooks. It is for reading data (see [Python tools](python-tools.html)).

Put the login in an env file **outside git**:

```
NF_CONSOLE_URL=http://192.0.2.10:8080
CONSOLE_USERNAME=admin
CONSOLE_PASSWORD=change-me
```

## 4. Reach the box

Run the installer from any machine that can reach the NF console. Tailscale is optional.

| Situation | What to do |
|---|---|
| A PC on the site LAN | Use the LAN URL in `NF_CONSOLE_URL`. Simplest. |
| Tailscale already on both ends | Use the tailnet IP or name. Not required. |
| Remote, no VPN | SSH port-forward to NF's loopback port: `ssh -L 18080:127.0.0.1:8080 user@<nf-host>`, then `NF_CONSOLE_URL=http://127.0.0.1:18080`. |
| Self-signed Caddy HTTPS front door | Trust that certificate for this one run with `--ca-file` or `--pin-server-cert`. Never turn verification off globally. |

## 5. Model the points in NF

Open-FDD reads sites, equipment and points from NF's Haystack model; nothing is configured in the app. See
[Modeling](modeling.html). The FDD tab lists the rule inputs that are still missing, so fix the model in NF and
reload.

## 6. The one command

```bash
python3 scripts/nf/hooks/nf_app_sync.py --env ~/.secrets/nf_console.env install nf-app/app.json   #
python3 scripts/nf/hooks/nf_app_sync.py --env ~/.secrets/nf_console.env doctor nf-app/app.json    #
```

`install` runs, in order: a preflight (is this a console login, which layer answers), the push (create or update
the app, upload the files, deploy the hooks), the npm dependency install (`PATCH /api/v1/apps/<id>/dependencies`, then a
restart; per NF's apps API, confirmed by the first verify run) and a verify step that runs each scheduled hook once
(`--skip-hooks`, `--skip-deps`, `--skip-verify-run` skip the respective parts; `--wait SECONDS` and `--resume PID`
control waiting on runs). When the `auto` engine finds no pglite it falls back to the vendored sqlite engine; an
explicit engine is never swapped. `doctor` is read-only: it re-checks the box at any time and says which layer
rejected you if auth fails. Neither prints passwords or hashes.

Lite: use `lite/app.json`. Then open `http://<nf-host>:<port>/api/v1/apps/static/open-fdd/` (or `open-fdd-lite`).
NF derives the app id from the **name**, so `application.id` in `app.json` must equal the slug of
`application.name` (CI checks it).

The lower-level commands stay available: `status`, `diff`, `push` (`--skip-hooks`, `--hook ID`), `run`
(`--hook ID`, `--arg KEY=VALUE`), `pull`, `uninstall`, `remove-old`. A plain `run` skips on-request hooks (`sparql`,
`analytics`) unless you pass `--arg`, and `history` skips when TimescaleDB is not configured and no args are given.

**Weather coordinates.** The `weather` hook takes latitude and longitude from NF Sites, then, when those are
empty, from the modeled Haystack site. If neither has them it stops with a clear error; it never
invents coordinates. Set them on the modeled site in NF.

## 7. Upgrade

Run the same command. `install` replaces the app in place (same id, same hook ids). For a new release:
`git pull`, then `install`, then `doctor`.

Predecessor apps (an older dashboard, or both editions side by side) are removed with `--remove-old`
. It is a **dry run** that lists what it would delete (apps named in `app.json` `replaces`, plus
their orphan hook points) and deletes nothing until you add `--yes`. Read the list first.

```bash
... install nf-app/app.json --remove-old          # lists, deletes nothing  
... install nf-app/app.json --remove-old --yes    # deletes what was listed 
```

After an edition swap or an app rename, update the Caddy `/` redirect (`APP_ID`) and restart Caddy.

**Orphan hook points.** Deleting an app does not delete the global points its hooks created (for example three
web-weather variables whose `attrs.application_id` names the old app). The console API has no documented
point-delete route (`DELETE /api/v1/point/<uuid>` answers 405). The supported path is the NF MCP tool
`delete_points`: run it with `dry_run=true` first, check each uuid's `application_id`, then run it for real.
`--remove-old` (and `uninstall`) only list these points, then print the dry-run instructions; the tool never deletes points. Never reuse an existing point uuid on
`POST /api/v1/bacnet/local`: it overwrites that point.

## 8. Uninstall

```bash
... uninstall nf-app/app.json            #
```

This deletes the app and its hooks. Result points the FDD hook wrote (`fdd` and `fault_timeline` markers) stay in NF
until you delete them with the `delete_points` dry-run flow above. If the dashboard was the box's bare URL, change
the Caddy `APP_ID`.

## 9. Is there a plugin store?

Not one we can confirm. What is documented and used here: NF apps are created and filled through the NF console
API (`/api/v1/apps`, files, hooks, dependencies, restart), which `nf_app_sync.py` drives. The NF MCP `manage_app`
tool can also create an app from a git URL (`git_url`) and run `install_deps`, but that is the MCP surface; we found
no equivalent one-click page in the NF console. A one-click install from the NF console is a future idea, not a
feature. MCP route: `connect`, `manage_app create` (name `Open-FDD`, id `open-fdd`), `write_file` per entry in the
`files` map of `app.json`, `deploy_hook` per hook, `install_deps`, `restart`; `manage_hooks run` needs the hook
**uuid**. `write_file` uploads whole files and the session can expire mid-task; push large files (vendored ECharts)
with `nf_app_sync.py`.

## 10. Troubleshooting

Which layer said no? Read the `WWW-Authenticate` header of the 401: `realm="restricted"` is **Caddy**,
`realm="nf-"` is **NF**. Table and recovery:
[Caddy README](https://github.com/bbartling/open-fdd/tree/master/deploy/nf-caddy#which-layer-rejected-me).

| Bug | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | 401 through the front door, and also on NF loopback with the same login | Caddy and NF passwords diverged (rotated one, copied an env from another box) | Test `GET /api/v1/apps` on NF loopback with NF's own login. If 200, re-hash that password into Caddy's `auth.caddy`, validate, restart. Steps: [login recovery](https://github.com/bbartling/open-fdd/tree/master/deploy/nf-caddy#login-recovery). |
| 2 | Generic 401 with a portal key env (`NF_CLIENT_ID`) | The portal API key is read-only and cannot deploy | Use `NF_CONSOLE_URL` + `CONSOLE_USERNAME` / `CONSOLE_PASSWORD`. The installer says so. |
| 3 | `/` opens an old dashboard | The Caddy `/` redirect names a previous app id | Set `APP_ID=open-fdd` (or `open-fdd-lite`) in Caddy's `.env`, restart Caddy. |
| 4 | `fdd` hook: `Cannot find package '@electric-sql/pglite'` | Push wrote `package.json` but did not install dependencies; the first scheduled run failed | `install` runs the dependency install and restart. By hand: MCP `manage_app install_deps`, then `restart`. |
| 5 | Weather hook: `no NF site has latitude/longitude` | Coordinates only on the modeled site, Sites API empty | The hook reads the modeled site too. Otherwise set lat/long on the modeled site. |
| 6 | `history` hook: `config.timescale is not set` | Timescale not configured (optional, full edition) | Expected without Timescale; a blanket `run` skips it. To enable it see "Optional: the TimescaleDB engine". |
| 7 | `sparql` / `analytics` return success with `ok: false` | Started with no args | Give args, or let `run` skip them. |
| 8 | Dashboard static files 401 with `realm="nf-"` although Caddy lets them through | Opening a path in Caddy skips only Caddy's login; NF's own console auth still applies | Caddy README, "Open pages and NF auth". Recommended: NF console auth off on the loopback listener, Caddy owns the login. |
| 9 | Orphan weather points after replacing an older app | Deleting an app keeps its hook-created points; no console delete route (405) | `--remove-old` lists them; delete with MCP `delete_points` (dry run first). |
| 10 | `CERTIFICATE_VERIFY_FAILED` to a self-signed front door | The process does not trust the certificate | `--ca-file <cert.pem>` or `--pin-server-cert`. Never `PYTHONHTTPSVERIFY=0`. |
| - | Old page after a deploy | NF caches app static files for 5 minutes | Asset URLs are stamped by `nf_app_sync.py`; otherwise reload with `?v=N`. |
| - | Hooks return 401 after NF login is enabled | The app needs `auth.apiKey.scopes` in `app.json` | Already in the shipped manifests; keep it when editing. |
| - | Intermittent empty 403 from `/api/v1/auth/token` | Known NF quirk | Retry. |
| - | Live values stop behind a proxy | The stream route needs `flush_interval -1` | Included in `deploy/nf-caddy`. |
| - | 1 GB Pi restarts | Usually the power supply | `vcgencmd get_throttled`; keep Caddy at `mem_limit: 64m`. |

Other pages: [NF gotchas](operations/nf/nf-gotchas.html), [BACnet validation](operations/nf/bacnet-validate.html),
[Front door](operations/nf/front-door-caddy.html), [Upgrade NF](operations/nf/nf-upgrade-compose.html).

## Optional: Caddy front door

Keeps the dashboard open on the LAN but puts the NF console and every write behind a login, with optional
self-signed HTTPS. See the
[`deploy/nf-caddy` README](https://github.com/bbartling/open-fdd/tree/master/deploy/nf-caddy). In short: set
`ENVOY_BIND_ADDRESS=127.0.0.1` in NF's compose and recreate NF once, copy `.env.example` to `.env`
(`LAN_IP`, `NF_UPSTREAM`, `NF_PORT`, `APP_ID`), create `auth.caddy` from a password hash, `docker compose up -d`.
Later pushes run on the NF host against loopback, or through the Caddy URL with the shared user and password.

## Remote access (Normal Online portal)

Nothing to configure. When `/api/v1/platform/info` reports `IAM_NF_CLERK`, the page loads clerk-js and sends
`Clerk.session.getToken({template:"ConsoleJWT"})` with its API calls, so the same UI works on the LAN and through the
portal. Through the portal, `/api/v1/bacnet/*` is not readable with API-key tokens; the BACnet tab needs the LAN.

## Profiles

| Profile | Box | FDD engine |
|---|---|---|
| edge-lite | 1 GB or more (2 GB recommended) | SQLite-WASM (vendored sql.js, about 60 MB); the pack is translated and matches Postgres on all rules in CI |
| full | 4 GB or more | PGlite (real Postgres in WASM, about 300 MB); `engine: "auto"` picks it when NF reports enough RAM |
| full + TimescaleDB | larger hosts | the Postgres pack runs inside NF's TimescaleDB connector database; results and long-range history stay there, with a size cap (default 100 GB). See [`nf-app/timescale`](https://github.com/bbartling/open-fdd/tree/master/nf-app/timescale) |

## Optional: the TimescaleDB engine

Full edition only. Enabling NF's Timescale/Postgres connector **alone does not switch Open-FDD to the Timescale
engine**. The engine is chosen by hook configuration: the `fdd` hook uses it when its `config` has
`"engine": "timescale"`, or when `engine` is unset or `"auto"` and a `timescale` block is present.
`"engine": "timescale"` without a `timescale` block fails with a clear error; it never falls back to another engine.

Hooks read the connection settings from their own **hook config** (the `config` object of the hook in
`nf-app/app.json` / the hook settings in NF, not from the repo). Both the `fdd` and the `history` hook need the same
`timescale` block. Secrets come from an environment variable named by `passwordEnv`, never from git:

`fdd` hook config:

```json
{ "engine": "timescale", "windowHours": 24,
  "timescale": { "host": "127.0.0.1", "port": 5432, "database": "nf", "user": "openfdd_rt", "passwordEnv": "OPENFDD_PG_PASSWORD" } }
```

`history` hook config:

```json
{ "timescale": { "host": "127.0.0.1", "port": 5432, "database": "nf", "user": "openfdd_rt", "passwordEnv": "OPENFDD_PG_PASSWORD" },
  "history": { "maxPoints": 200000, "statementTimeoutMs": 20000 } }
```

(`history` limits are optional; the values above are the defaults.) Set `OPENFDD_PG_PASSWORD` in the NF app's
environment, not in `app.json`.

Run `nf-app/timescale/install.sql` once as an installer role (it also upgrades an older install), then give the hooks a
runtime role that can only read NF's tables and write schema `openfdd`. Retention only trims Open-FDD's own tables; trimming
NF history is an explicit opt-in. Details, grants and the upgrade path:
[`nf-app/timescale/README.md`](https://github.com/bbartling/open-fdd/tree/master/nf-app/timescale).

## Verify

- [ ] `doctor` reports no problems, or `diff nf-app/app.json` reports no differences.
- [ ] The dashboard loads with no red errors in the browser console.
- [ ] Overview cards show live values; Charts draws history.
- [ ] Points lists your tagged points; the FDD tab lists no unexpected missing roles.
- [ ] Model and RDF exports Turtle without dangling references.
- [ ] The weather hook ran (global variables update every 20 minutes).
- [ ] Through the portal, the dashboard loads and shows data.

Where the results go and how to read them from code: [FDD data access](fdd-data-access.html).
