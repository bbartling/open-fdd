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
7. **Weather**: lat/long come from NF Sites or the modeled Haystack site; if both are missing the hook errors. Do not invent coordinates; ask for them.
8. **Timescale is optional** (full edition only): `history` needs `config.timescale`, and a blanket `run` should skip it without; never silently switch engines.
9. **Self-signed front door**: `--ca-file` or `--pin-server-cert`; never `PYTHONHTTPSVERIFY=0`.
10. After any Caddy change: back up, `caddy validate`, restart; update `APP_ID` on an edition swap or rename.

Results are NF points; how a client reads them: `docs/fdd-data-access.md`.
