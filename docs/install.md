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

**Hand-edited files on the box (5.0.6).** Every push records the sha256 of each file it wrote in `static/version.json`
(`files`). The next `push` / `install` compares the box with that record **before writing anything** and stops (exit 4)
when a file was edited by hand, listing the files. `--save-remote DIR` first downloads the edited box copies to `DIR` for
review; `--force` overwrites them. An older install has no record: the box is compared with the commit its
`version.json` names (else with this repo's copy) and a warning says so. `doctor` lists hand-edited files too
(read-only, a warning). Land a hotfix in the repo instead of leaving it on the box, so the next release carries it.

Lite: use `lite/app.json`. Then open `http://<nf-host>:<port>/api/v1/apps/static/open-fdd/` (or `open-fdd-lite`).
NF derives the app id from the **name**, so `application.id` in `app.json` must equal the slug of
`application.name` (CI checks it).

The lower-level commands stay available: `status`, `diff`, `push` (`--skip-hooks`, `--hook ID`), `run`
(`--hook ID`, `--arg KEY=VALUE`), `pull`, `uninstall`, `remove-old`. A plain `run` skips on-request hooks (`sparql`,
`analytics`) unless you pass `--arg`, and `history` skips when TimescaleDB is not configured and no args are given.

**Weather coordinates.** The `weather` hook takes latitude and longitude from the app options `latitude` and
`longitude` (NF console > the app's settings; an unset or 0/0 option does not count), then NF Sites, then the modeled
Haystack site. The run's `coords_source` says which. If none has them it stops with an error naming every place; it never
invents coordinates.

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
| 5 | Weather hook: `no NF site has latitude/longitude` | No coordinates in the app options, NF Sites or on the modeled site | Set the app options `latitude` / `longitude` (NF console > app settings), or lat/long on the NF site or the modeled site. `doctor` (**weather coords**) says which source it found. |
| 6 | `history` / `fdd` hook: `Timescale connection settings not found` | The app option `timescale` is not set (NF stores app options, not a hook config) | Expected without Timescale (a blanket `run` skips `history`). To enable it see "Optional: the TimescaleDB engine". |
| 7 | `sparql` / `analytics` return success with `ok: false` | Started with no args | Give args, or let `run` skip them. |
| 8 | Dashboard static files 401 with `realm="nf-"` although Caddy lets them through | Opening a path in Caddy skips only Caddy's login; NF's own console auth still applies | Caddy README, "Open pages and NF auth". Recommended: NF console auth off on the loopback listener, Caddy owns the login. |
| 9 | Orphan weather points after replacing an older app | Deleting an app keeps its hook-created points; no console delete route (405) | `--remove-old` lists them; delete with MCP `delete_points` (dry run first). |
| 10 | `CERTIFICATE_VERIFY_FAILED` to a self-signed front door | The process does not trust the certificate | `--ca-file <cert.pem>` or `--pin-server-cert`. Never `PYTHONHTTPSVERIFY=0`. |
| 11 | `doctor`: `[FAIL] connectivity: ... connection refused` | Wrong URL or port. Nothing answered, so the login was never tested. NF may listen on loopback only (`ENVOY_BIND_ADDRESS=127.0.0.1`) | Use the front-door URL (e.g. `https://host`) in `NF_CONSOLE_URL`, not NF's own port; check the listener and any VPN or port-forward. Do not rotate credentials for this. `tls` = trust the certificate (row 10); `auth` = a real 401/403 (rows 1, 2, 8). |
| 12 | FDD results frozen: `fdd` hook shows success (5.0.3) or fails (5.0.5+), outputs `fddStatus: stale`, history empty | Inputs do not resolve: `required roles missing`, `unit unusable`, or `no input data in window` (the source has no recent rows) | `doctor` (**fdd freshness**). Read the last `fdd` run with `include_results=true` for per-equip reasons. Compare the newest sample in the Timescale source (`SELECT max(ts) FROM openfdd.nf_samples`) with now, and NF's latest values. See [FDD data access](fdd-data-access.html#checking-that-results-are-fresh). |
| 13 | `install` / `push` stops: `STOPPED: N file(s) on the box differ from what was last pushed (hand-edited on the box)`, exit 4 | A file was edited on the box (a console hotfix) after the last push; overwriting it would lose that edit (5.0.5 did, silently, and broke `fdd`, `history` and `weather`) | Nothing was written. Review the edits: `--save-remote DIR` downloads the box copies. Land the change in the repo, then push; or `--force` to overwrite. `doctor` (**hand edits**) lists them without changing anything. |
| 14 | `fdd` fails `model empty: 0 equipment resolved from the model layer` / `model incomplete`, or a dashboard or script sees fewer sites or points than exist | NF `point/query` pages by `pageOffset` + `totalCount`, **not** by a next-page token. A reader that only follows a token sees the first 500 records; once published results grew the model layer past 500, the SITE fell off page 1 ([#1550](https://github.com/bbartling/open-fdd/issues/1550)) | Fixed in 5.0.6: every reader uses one pager and fails loudly (`paging cap reached`, `read N of totalCount M`, `repeated records already read`) instead of truncating. Upgrade, then `doctor`. |
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
engine**. The engine is chosen by the app settings: the `fdd` hook uses it when the option `engine` is `timescale`,
or when `engine` is unset or `auto` and the option `timescale` is set. `engine = timescale` without a usable
`timescale` setting fails with `Timescale connection settings not found: set the app option "timescale" ...`; it never
falls back to another engine.

**Where the settings live (NF 3.10.x).** NF does **not** store a hook-definition `config` (the stored hook shows
`config: null`) and hands a hook no app environment. What persists is the app's **options** (the app's settings in the
NF console, or `PATCH /api/v1/apps/<id>`); the hook runtime passes their values to the hook as `ctx.config`, scalars
only. So both the `fdd` and the `history` hook read the same options:

| Option | Type | Meaning |
|---|---|---|
| `engine` | string | `auto`, `sqlite`, `pglite` or `timescale` |
| `windowHours` | number | trailing window per `fdd` run (default 24) |
| `timescale` | string, secret | the connection as JSON `{"host","port","database","user","password"}`, or a `postgres://` URL |
| `latitude`, `longitude` | number | weather location (before NF Sites and the modeled site) |
| `site` | string | which NF site the weather hook uses when several have coordinates |

Nested objects are not an option type, so `timescale` is a JSON **string**, for example
`{"host":"127.0.0.1","port":5432,"database":"nf","user":"openfdd_rt","password":"..."}`; the hooks parse it
(`hooks/lib/settings.js`). A value that is set but not valid JSON fails naming the option and never echoes the value (it
holds a password); the password and any URL credentials are removed from every log line and error. A hook-definition
`config` object (a NF that stores one, or a test) is still read. `passwordEnv` inside the connection works only if you
can put that variable into the hook's process environment, which NF 3.10.x does not document; use `password` in the
secret option. `doctor` (**timescale**) parses the option the way the hooks do, so a value the hooks cannot read fails
there too. Options are never written from git: set them on the box. The `history` limits (`maxPoints`, `maxSpanDays`,
`minBucketSec`, `statementTimeoutMs`) are an optional JSON-string option `history`.

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
