---
title: NF gotchas
parent: NF operations
nav_order: 6
---

# NF gotchas (3.10)

Behaviors found by using NF 3.10 on real boxes, with the workaround for each. They were true on 3.10.9; if a newer
NF changes one, fix this page. None of them is a reason to change the app: the app already avoids them.

## Never do

### `POST /api/v1/bacnet/local` with an existing point uuid overwrites that point

`CreateLocalObject` accepts a `uuid`. Passing a polled BACnet point's uuid (hoping to bind a server object to it)
rewrites that point's name, attrs and data through a new `hpl:bacnet:local` layer record and pushes a 0 sample into
its history. Deleting the local object later leaves the layer record behind.

- **Omit `uuid`**: NF assigns one. Set the value with `PATCH /api/v1/bacnet/local`.
- Repair needs a per-layer rewrite of the point from an intact copy (another layer or a backup), which is why
  the next gotcha hurts.

### Layer-scoped point delete is gone

`DELETE /api/v1/point/points?layers=...` answers `layers is not supported in delete anymore`, and the NF MCP
`delete_points` deletes **every** layer of the point. There is no clean way to drop one stray layer record; take a
backup of the points before you delete, and prefer overwriting a record to deleting it.

## Auth and the portal

### The Normal Online gateway answers 401 to API-key tokens on `/api/v1/bacnet/*`

A client-credentials token with the BACnet read-only scope reads BACnet configuration on the LAN, but through
`<installation-uuid>.normal-online.net` the gateway answers 401 (the point APIs pass). The console's own Clerk token
works there. Use the LAN for BACnet configuration and for [BACnet validation](bacnet-validate.html).

### App pages need the console's Clerk token through the portal

An app's `static/` is served at `/api/v1/apps/static/<app-id>/`, same origin as the console, with
`cache-control: max-age=300`. Through the portal, the page's `fetch` calls must send the console JWT:
`Clerk.session.getToken({template: "ConsoleJWT"})`, with the publishable key from `/api/v1/platform/info`; cookies
alone get 401. Open-FDD's `nf.js` does this when `IAM_NF_CLERK` is reported. After a deploy, reload with `?v=N`
because of the 5-minute cache.

### Intermittent empty-body 403 on `/api/v1/auth/token`

Seen on the LAN and through the portal (a few in 60 under parallel load); NF logs the token as issued. Retry. The
tools in `scripts/nf/tools/` retry 403, 429 and 5xx with back-off.

### Other auth surprises

- `ALLOW_ALL_LOCALHOST` lets true loopback clients skip basic auth, so "is auth on?" tested from the box itself
  proves nothing; test from another machine.
- With no admin configured the API needs no auth at all. Behind a front door
  ([Front door](front-door-caddy.html)) that is deliberate; elsewhere it is not.
- Persisted config under NF's data folder can win over `.env` / compose changes; check the console setting if a
  change "does not take".
- Some info endpoints stay unauthenticated; they are not proof that API auth is enforced.
- Once NF's own login is enabled, an app's hooks need `auth.apiKey.scopes` in the manifest or they get 401.

## TLS

### Built-in TLS (`TAILSCALE_HTTPS=1`) breaks hooks and the portal tunnel

It turns Envoy's single listener into HTTPS, but app runtimes call `NFURL=127.0.0.1:<PORT>` over plain HTTP and the
portal-managed `cloudflared` ingress is `http://localhost:<PORT>`. No setting fixes either. Use a front proxy
instead: [Front door](front-door-caddy.html).

## Secrets in logs

### The cloud backup URL is logged in plain text

On every config refresh NF logs `SetEnv id=BACKUP_URL new_value=... old_value=...` and `Env key=BACKUP_URL value=...`
at INFO, and the backup service logs it again when an upload completes. The URL is a storage SAS URL that includes
a write/delete signature valid for about a year (the secret `TOKEN_SIGNING_SECRET` is masked in the same block;
this is not). Anyone who can read the container logs, or a support bundle that includes them, can write to or
delete that site's cloud backups.

- Do not paste `docker logs`, `nf version` output or environment dumps into tickets or chat without redacting
  `BACKUP_URL`.
- Report it to Normal and ask for masking, or logging only host and path.

Cloud backup itself works: it uploads about daily; contents are configuration, not Redis history or app files.

## BACnet server

- `CreateLocalObject` rejects CharacterString Value, Date Value and DateTime Value (`unsupported object type`).
  Keep text such as site name or last-update time in Haystack tags, not in BACnet objects.
- A multi-state present value must be set as `{"enumerated": N}` (`{"unsigned": N}` is refused) and NF serves it with
  an Enumerated tag; BACnet wants Unsigned, so strict clients (bacpypes3) cannot read it. `state-text`,
  `number-of-states` and `description` read fine.
- A new MSV starts at present value 0, which is out of range for its states; set it before use.

## Ontology and modeling

- NF has many specific point classes (hundreds); list them with `GET /api/v1/equipment/classes?pageSize=1000` and
  pick the closest. If an equipment class is missing (for example a furnace), use the nearest class plus a marker.
- Point markers are **not** derived from `class`; equipment markers are. Set a point's `markers` explicitly.
- Brick is either/or, not additive: enabling it changes the model layer. A bare controller has no class of its own;
  use `controller`. See [Haystack tagging](haystack-tagging.html).

## Polling and data quality (NF QualityRules)

- Imported points **do not poll until a period is set**. Select points for `point/copy` with `indexLayer: "default"`.
- The built-in range detector looks at the point's **retained history** (days), not "out of range now": one past
  excursion keeps the flag until it ages out. There is no rate-of-change or spike detector.
- Quality flags are swept on an interval of minutes, so they lag fast poll periods. Severity belongs to the rule,
  not the point. Use stable rule `id`s and PUT, or you create duplicates.
- Treat NF's quality flags as data quality, not FDD. Open-FDD's rules run in the FDD hook.

## Console

- Object Explorer can white-screen on a bad saved view (`Cannot read properties of undefined (reading 'replace')`).
  The saved views live in one config key, `object_selection_views` (base64 JSON). Valid shape: `grouping` entries
  as `layer*|*field`, and `columnSelection.<layer>` as `{ "order": N, "children": [{ "field", "visible", "order" }] }`,
  not a bare array. The UI cannot delete a view while it is selected (the page crashes first): back the key up, fix
  the array and POST it again, or `DELETE` the whole `object_selection_views` key (this removes all saved views,
  nothing else). Open Object Explorer without `?view=`.
- The built-in Dashboard stores its config as internal JSON in config keys; the shape is not a public contract.
- Points can exist while Object Explorer shows the device group collapsed: it looks like an empty import, it is not.

## Finding things out

- Random restarts on a Raspberry Pi are usually power: check `vcgencmd get_throttled` and use the official supply
  and a short, thick cable.
- Find undocumented REST routes and message fields inside the NF container instead of guessing:

  ```bash
  docker exec <nf-container> grep -n -A3 '/api/v1/apps' /etc/envoy/envoy.yaml.template
  docker exec <nf-container> sh -c 'cd /usr/share/nginx/html/assets && grep -o -h -E "\{name:\"[A-Za-z]+\",options:\{\"google.api.http\":\{[a-z]+:\"/api/v1/bacnet[^\"]*\"" *.js | sort -u'
  ```

## Open-FDD installer / hooks (5.0.8+)

- **Missing app-file GET may be HTTP 500** (`Content-Type: application/grpc`, empty body), not 404. The hand-edit guard treats that signature as missing only for paths that are new relative to the box. Every other 500 still aborts.
- **StartHook args are a string-to-string map.** Coerce structured fields before use: JSON `uuids`, numeric
  `windowHours` / `days` / `maxTriples`, and boolean analytics flags. The shared helper converts declared fields
  only, leaving text fields such as queries, dates and identifiers unchanged; typed unit-test calls remain valid
  (#1559).
- **Windows cp1252:** `nf_app_sync.py` run and verify output must tolerate non-cp1252 Unicode in hook events and
  extracted `ok:false` error text (#1560). Output replaces unencodable characters while preserving run state and
  exit status.
- **Offline coverage:** the browser mock serves synthetic data. Installer tests drive the production console client
  with the observed gRPC error response and hook tests supply NF-shaped argument maps, stored app option values,
  and offset pages beyond the first 500 records. The deploy agent verifies the installed app against real NF.
- **Weather deadlines:** both editions budget 10 seconds for all Sites pages, 45 for the model fallback, 40 for
  two weather fetch attempts, and 30 for three point writes. Lite can spend another 40 seconds on its local
  mirror. The hook deadline is 180 seconds and NF allows 190 seconds for the invocation.
- **Live patching is last resort.** Capture with a read-only file GET first, patch one file, commit on a patch branch (HTML without `?v=` stamps), restart before verify, and do not rewrite push-manifest hashes until the deploying revision contains the fix. See repo-root `AGENTS.md`.
