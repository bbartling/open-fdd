# NF application hooks (source of truth)

NF JavaScript hooks for Open-FDD sites live here. **This folder is the source of
truth.** Edit the code here, push it to the NF box with `nf_app_sync.py`, and pull it
back before you commit if anyone edited it in the NF console.

| File | What |
| --- | --- |
| `open_meteo_weather.js` | Hook: Open-Meteo outdoor air dry bulb, RH and dewpoint every 20 min (Madison, WI hard-coded; **change the lat/lon per site**) |
| `open_meteo_weather.app.json` | Manifest: NF application (id, runtime, auth scopes), file map, hook definition (schedule, global variables) |
| `nf_app_sync.py` | Stdlib helper: `status`, `push`, `run`, `diff`, `pull` against the NF local console API |

## Agents: prefer the NF MCP connector

With the Normal Framework MCP (`https://portal.normal-online.net/mcp`) connected:
`connect use_site <installation-uuid>`. Then use `deploy_hook` (pass the file content,
`entry_point: /hooks/open_meteo_weather.js`, `mode: scheduled`, the rrule and the
global variables from the manifest), `manage_hooks run` (run now), `runs` and `logs`,
and `manage_app read_file` to pull. Afterwards, check that the app still has
`auth.apiKey` scopes; see the gotchas below. `nf_app_sync.py` is the console-API
fallback, and the repo files stay the source of truth either way.

## How NF hooks work (NF 3.10.x)

- An NF **application** (Applications SDK, Node runtime) holds files and **hooks**.
  A hook is `module.exports = async ({ globalVariables, sdk }) => {...}`.
  It runs on a schedule (an iCal `rrule`), on point changes, or on request.
- **Global variables** in the hook definition become NF points with
  `pointType: VARIABLE` (attrs `application_id`, `hook_id`, `label`). They have
  stable UUIDs (`GET /api/v1/apps/{app}/hooks/{hook}/data`) and show up in the
  portal API like BACnet points. Every write is stored as a sample, so they need
  no trend `period`. Put their UUIDs in `provider_sites.<site>.json`.
- **Run now:** console **Applications › app › hook › Run**, or
  `POST /api/v1/apps/{app}/hooks/{hook}` with `{}` (StartHook). It returns a
  `pid` and appears in runs as `TRIGGER_REQUEST`. It does not change the schedule.
  `nf_app_sync.py run` does this and prints the run's events.

## Where to view and edit the JS on the box

- Console (Tailscale): `http://<nf-console>:8080/applications/<app-id>/hooks/<hook-id>`.
  For ACME that is `/applications/open-meteo-weather/hooks/open-meteo-weather`.
  The page has a Monaco editor, run history and logs. App files are at
  `/applications/open-meteo-weather`.
- Portal: same path on `https://<installation-uuid>.normal-online.net` after the
  Normal portal login. The API key token is read-only and cannot deploy.
- After a console edit, run `nf_app_sync.py diff` and then `pull`, and commit.
  Otherwise the next `push` overwrites the console edit.

## Deploy or update from the repo

```bash
ENV=~/.secrets/nf_acme_console.env          # CONSOLE_USERNAME, CONSOLE_PASSWORD, NF_CONSOLE_URL
M=scripts/nf/hooks/open_meteo_weather.app.json
python3 scripts/nf/hooks/nf_app_sync.py --env $ENV push $M     # create app if missing, set auth scopes, write files, upsert hook, restart
python3 scripts/nf/hooks/nf_app_sync.py --env $ENV run $M      # run once now and print the result
python3 scripts/nf/hooks/nf_app_sync.py --env $ENV status $M   # schedule, scheduler lastRun, last 5 runs
python3 scripts/nf/hooks/nf_app_sync.py --env $ENV diff $M     # NF vs repo (exit 1 when different)
python3 scripts/nf/hooks/nf_app_sync.py --env $ENV pull $M     # overwrite the repo files with the NF copy
```

The console API calls behind it (HTTP Basic, local console only):

| Step | Call |
| --- | --- |
| Create app | `POST /api/v1/apps` `{"id","name","description","runtime":"RUNTIME_NODE_JS"}` (no git URL needed; NF scaffolds package.json and app.json) |
| Auth scopes | `PATCH /api/v1/apps/{app}` `{"id","auth":{"apiKey":{"scopes":[...]}},"updateMask":["auth"]}` |
| Write file | `POST /api/v1/apps/{app}/files/{path}` with a **JSON string** of base64 as the body (not an object) |
| Read file | `GET /api/v1/apps/{app}/files/{path}` returns `{"data": base64}` |
| Upsert hook | `POST /api/v1/apps/{app}/hooks` with the **hook object itself** as the body |
| Load new code | `PATCH /api/v1/apps/{app}/restart` |
| Run now | `POST /api/v1/apps/{app}/hooks/{hook}` `{}` |
| Runs | `GET /api/v1/apps/{app}/hooks/{hook}/runs?page_size=10&include_results=true&include_logs=true` |
| Scheduler | `GET /api/v1/apps/{app}/hooks/{hook}/runtimes` (`scheduler.lastRun`) |

## Gotchas (learned on ACME, NF 3.10.9)

- **The app needs `auth.apiKey.scopes`.** Without it, every SDK call from the hook
  (`sdk.http`, point writes) gets 401 / `UNAUTHENTICATED`. Scopes: `normalgw.hpl.v1.readwrite`,
  `normalgw.hpl.v2.readwrite`, `normalgw.automation.v1.readonly`. NF then creates an
  auth client named `Application: <app-id>`. Setting the scopes again rotates
  that client; restart the app afterwards (`push` does).
- **`variable.write()` does not await the write.** A failed write still shows the
  run as `STATE_SUCCESS`. The hook writes with an awaited
  `sdk.http.post('/api/v1/point/data', {uuid, values:[{ts, real}]})` and throws on error.
- **New code is not picked up until the app restarts.**
- `GET /api/v1/apps` returns the app's generated client id and secret, and so does
  `GET .../hooks/{hook}/runtimes` (in the runtime `env`). Never print or paste those
  responses. `nf_app_sync.py` drops the `auth` block and prints only the scheduler fields.
  If one leaks, run `push`: setting the scopes again rotates the client.
- The runtime has `fetch`/`https` and outbound internet from the box. Send a
  `User-Agent`. A socket idle timeout is not a run deadline: `open_meteo_weather.js`
  wraps every await in `withDeadline` (`HTTP_TIMEOUT_MS` 20000 per Open-Meteo
  attempt, `HTTP_RETRIES` 1 on errors that are not HTTP 4xx, `WRITE_TIMEOUT_MS`
  10000 per point write, `RUN_DEADLINE_MS` 60000 around `runOnce`). The hook
  exports `magnusDewpointF`, `OPEN_METEO_URL`, and `withDeadline`. Keep
  `invokeTimeout` (60 s) at the whole-run cap.
- `sdk.http` (axios, base `http://127.0.0.1:8080`) rejects with a plain object,
  not an `Error`. Wrap it so failures show in the run result.
- `rrule` is UTC (`DTSTART:...Z`). `FREQ=MINUTELY;INTERVAL=20` fires at :00/:20/:40.

## Verify

1. `nf_app_sync.py run` shows `STATE_SUCCESS` with `write_path: sdk.http AddPointsData`.
2. `nf_app_sync.py status`: later runs show `TRIGGER_SCHEDULE` 20 min apart.
3. `python3 scripts/nf/check_portal_fresh.py --env <file> --sites <site.json>`
   prints PASS on the **remote portal**. Weather points older than `--warn-age-min`
   (default 25, one 20 min hook interval plus margin) print WARN and still pass
   until the 30 min fail.

## Open-Meteo weather hook

- URL: `https://api.open-meteo.com/v1/forecast?latitude=43.0731&longitude=-89.4012&current=temperature_2m,relative_humidity_2m,dew_point_2m&temperature_unit=fahrenheit&timezone=UTC`.
  It is free with no API key, and `current` updates every 15 min.
- Dewpoint: it writes Open-Meteo's `dew_point_2m`. It also computes Magnus
  (b = 17.62, c = 243.12 °C: γ = ln(RH/100) + bT/(c+T), Td = cγ/(b−γ)), logs both
  and the delta, and writes Magnus only when the API omits dewpoint. Observed delta ≈ 0.03 °F.
- Roles `web-outside-air-temp`, `web-outside-air-humidity` and
  `web-outside-air-dewpoint` (equip `weather`) keep hook points apart from the
  site's own OA sensors.
- For a new site: copy the JS and manifest, change `SITE_NAME`/`LATITUDE`/`LONGITUDE`
  and the app id, `push`, then read the variable UUIDs from `/hooks/{hook}/data`
  into that site's operator config JSON (outside git).
