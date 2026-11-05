# Install Open-FDD as a Normal Framework plugin

Fresh NF box to Open-FDD in one run. Background: [ADR-014](../architecture/adr-014-open-fdd-as-nf-plugin.md),
[migration plan](../migration/nf-plugin/PLAN.md), app source in [`nf-app/`](../../nf-app/README.md).

## 1. Prerequisites

- A **licensed NF 3.10 or newer** (a free-tier licence is enough) reachable on your LAN.
- A **console login** on that NF (`CONSOLE_USERNAME` / `CONSOLE_PASSWORD`). Deploying needs the local
  console API; the remote portal token is read-only.
- Python 3 on the machine you deploy from (standard library only) and this repo checked out.
- On small boxes (1 GB Pi) run nothing heavy on the box: build, test and deploy from another PC.

## 2. Model the points in NF (Haystack tags)

Open-FDD reads the site, equipment and points from NF's Haystack model; nothing is configured in the app.

- **Site:** a site record with latitude, longitude and timezone (the weather hook reads them from NF).
- **Equipment:** equip instances with markers (`ahu`, `vav`, ...); points carrying `siteRef`, `equipRef`
  (and `deviceRef` for the BACnet device), `class` (for example `zone-air-temp-sensor`), `markers`,
  `kind`, `unit`.
- Trend the points you want to chart or run rules on.

The **FDD tab** shows, per equipment, which rule roles are missing a matching point class, so you can
fix the model in NF and reload. Model in NF (console, or the NF MCP `tag_points` / `manage_equipment`),
never in the app. To support another site, tag it in NF; no app change is needed.

## 3. Push the app

Create an env file **outside git** (placeholders shown):

```
NF_CONSOLE_URL=http://192.0.2.10:8090
CONSOLE_USERNAME=admin
CONSOLE_PASSWORD=change-me
```

```bash
python3 scripts/nf/hooks/nf_app_sync.py --env ~/.secrets/nf_console.env push nf-app/app.json
# UI only, no hooks:   ... push nf-app/app.json --skip-hooks
# compare box vs repo: ... diff nf-app/app.json
```

`push` creates or updates the app (`open-fdd`), uploads the files, deploys the hooks and restarts.
Open `http://<nf-host>:<port>/api/v1/apps/static/open-fdd/`.

## 4. Optional: Caddy front door

Keeps the dashboard open on the LAN but puts the NF console and all writes behind a login (optional
self-signed HTTPS). See [`deploy/nf-caddy/README.md`](../../deploy/nf-caddy/README.md): bind NF's Envoy to
loopback (`ENVOY_BIND_ADDRESS=127.0.0.1`), set `LAN_IP` / `NF_UPSTREAM` / `NF_PORT`, add an `auth.caddy`
hash, `docker compose up -d`. Once NF is behind Caddy, later pushes either run on the NF host against
loopback, or go through the Caddy URL with its basic-auth user (`/api/v1/apps*` is locked).

## 5. Profiles

| Profile | Box | What runs |
|---|---|---|
| **edge-lite** | small, e.g. a 1 GB Raspberry Pi | the app alone; NF's Redis history (about 7 days) |
| **full** | 4 GB RAM or more | same app plus NF's TimescaleDB integration for long history and the SQL FDD pack (**coming in slice 5**) |

## 6. Remote access (Normal Online portal)

Nothing to configure. When `/api/v1/platform/info` reports `IAM_NF_CLERK`, the page loads clerk-js and
sends `Clerk.session.getToken({template:"ConsoleJWT"})` with its API calls.

## 7. Verification checklist

- [ ] `nf_app_sync.py ... diff nf-app/app.json` reports no differences.
- [ ] The dashboard loads at `/api/v1/apps/static/open-fdd/` with no red errors in the browser console.
- [ ] Overview cards show live values; the Charts tab draws history.
- [ ] Points tab lists your tagged points; the FDD tab lists no unexpected missing roles.
- [ ] Model & RDF tab exports Turtle without dangling references.
- [ ] Weather hook ran (global variables update every 20 minutes).
- [ ] With the front door: `/` redirects to the dashboard; the console URL asks for a login.
- [ ] Through the portal, the dashboard loads and shows data.

## 8. Troubleshooting

- **Old page after a deploy:** NF caches app static files for 5 minutes (`max-age=300`).
  `nf_app_sync.py` stamps asset URLs to bust it; otherwise reload with `?v=N`.
- **App not found / wrong id:** NF derives the app id from the **name**; `application.id` must equal the
  slug of `application.name` (CI checks it).
- **Hooks return 401:** with NF login enabled the app needs `auth.apiKey.scopes` in `app.json`.
- **Intermittent empty 403 from `/api/v1/auth/token`:** retry.
- **Low-RAM boxes (1 GB Pi):** run nothing heavy on the box; keep Caddy at `mem_limit: 64m`; check the
  power supply (`vcgencmd get_throttled`) if it restarts unexpectedly.
- **Live values do not update behind a proxy:** the stream route needs `flush_interval -1` (included in
  `deploy/nf-caddy`).

## 9. MCP deploy recipe (NF MCP server)

Alternative to `nf_app_sync.py`, from an MCP client (for example Claude Code) connected to the NF MCP server:

1. `connect` with the site uuid; confirm the site is healthy.
2. `manage_app` `create` with the name `Open-FDD` (id `open-fdd`), Node runtime, scopes from `nf-app/app.json`.
3. `manage_app` `write_file` for each entry in `nf-app/app.json` `files` (NF path, content from the repo).
4. `manage_hooks` / `deploy_hook` for each entry in `hooks` (for example `weather`, every 20 minutes).
5. `manage_app` `restart`; run a hook once with `manage_hooks` `run` (needs the hook **uuid**, not its name).

`write_file` uploads whole files (no patch) and the MCP session can expire mid-task (`connect` again).
Very large files, such as the 1 MB vendored ECharts (`static/vendor/echarts.esm.min.js`), are better pushed
with `nf_app_sync.py`.
