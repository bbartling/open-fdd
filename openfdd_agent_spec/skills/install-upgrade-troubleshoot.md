---
name: install-upgrade-troubleshoot
description: Install, upgrade, remove or diagnose Open-FDD on an existing NF site with nf_app_sync.py (doctor first). Auth layers, deps, weather coords, optional Timescale.
---
# Install, upgrade, troubleshoot

Human guide: `docs/install.md`. Caddy: `deploy/nf-caddy/README.md`. Flags below match the installer;
confirm with `nf_app_sync.py --help`.

1. **Always run `doctor` first** (`nf_app_sync.py --env <env> doctor nf-app/app.json`, or `lite/app.json`). Read what it says before changing anything.
2. **Never print secrets**: no passwords, bcrypt hashes, API secrets, SAS or backup URLs, in answers, logs or commits. Env files stay outside git.
3. **Deploy needs the console login** (`NF_CONSOLE_URL` + `CONSOLE_USERNAME` / `CONSOLE_PASSWORD`). The portal API key (`NF_CLIENT_ID` / `NF_CLIENT_SECRET`) is read-only and cannot deploy.
4. **Which layer rejected a 401** (header `WWW-Authenticate`):

   | Header | Layer | Action |
   |---|---|---|
   | `realm="restricted"` | Caddy | Caddy's `auth.caddy` hash differs. Test NF on loopback; if 200, re-hash (`caddy hash-password`, password on stdin with a trailing newline), validate, restart Caddy (`admin off`: no `reload`). |
   | `realm="nf-"` | NF | The env password is not NF's. Caddy and NF must share one user and password when NF console auth is on. |

   Static app files "open" in Caddy still 401 (`nf-`) if NF's own auth is on; the recommended layout is Caddy owns the login, NF auth off on loopback.
5. **Install / upgrade**: `install <manifest>` (preflight, push, `npm` deps, restart, verify) then `doctor`. Pick the edition by RAM: about 1 GB gets Lite (`open-fdd-lite`), larger gets full (`open-fdd`). Deps are required (`@electric-sql/pglite`, `pg`): a missing-package error means the dependency install did not run.
6. **Remove the prior version**: detect it (`replaces` in `app.json`, other Open-FDD or bench dashboard apps, orphan hook points), run `--remove-old` as a **dry run**, show the list to a human, and add `--yes` only after the human says so. Orphan points: the console has no delete route; NF MCP `delete_points` with `dry_run=true` first. Never reuse an existing point uuid on `POST /api/v1/bacnet/local`. Do not touch HVAC points, BACnet polling or Haystack tags.
7. **Weather**: lat/long come from the app options `latitude` / `longitude`, then NF Sites, then the modeled Haystack site; if all are missing the hook errors. Do not invent coordinates; ask for them.
8. **Timescale is optional** (full edition only): NF stores app options, not hook config. The hooks read the `timescale` option (a JSON string with host) as `ctx.config`; a blanket `run` skips `history` without it; never silently switch engines. Never print the option value.
9. **Self-signed front door**: `--ca-file` or `--pin-server-cert`; never `PYTHONHTTPSVERIFY=0`.
10. **Read the `doctor` category**: `connectivity` (refused, DNS, unreachable, timeout) means the URL or port is wrong or unreachable and credentials were never tested; use the front-door URL (e.g. `https://host`), not NF's own port (it may be loopback only), and do not touch credentials. `tls` means trust the certificate (item 9). `auth` is only a real HTTP 401/403 (item 4).
11. **Frozen FDD** (outputs `stale`, results not updating, `history` empty): run `doctor` and read the **fdd freshness** line. Then read the last `fdd` run (`include_results=true`): the reason is `required roles missing`, `unit unusable` (point has no or unknown unit) or `no input data in window (newest sample at ...)`. Read-only checks: newest sample in the Timescale source (`SELECT max(ts) FROM openfdd.nf_samples`) versus now, and NF latest values of the points. Do not re-tag or restart without a human.
12. **Installer guard (hand-edited files).** `push` / `install` compare the box with the manifest of the last push (`static/version.json` `files`) before writing and STOP (exit 4, nothing written) when a file was edited by hand, listing it. Never answer that with `--force` on your own: run `--save-remote DIR` to keep the box copies, show the list and the diff to a human, get the edit landed in the repo, and use `--force` only when the human says to overwrite. `doctor` (**hand edits**) shows the same list read-only. An install without a manifest (older release) is compared with its installed commit, else the repo copy, and warns.
13. **Paging.** NF `point/query` pages by `pageOffset` + `totalCount`, not by a next-page token. Never write a loop that follows only a token; use the shared pager (`nf-app/hooks/lib/paging.js`, `static/nf.js` `pageAll`, `scripts/nf/nf_paging.py`, `open_fdd/nf/client.py` `page_all`). `model empty` / `model incomplete` from the `fdd` hook means the model was not read completely or has no equipment, not that roles are missing.
14. After any Caddy change: back up, `caddy validate`, restart; update `APP_ID` on an edition swap or rename.

Results are NF points; how a client reads them: `docs/fdd-data-access.md`.
