---
name: deploy-to-nf-box
description: Deploy the Open-FDD full app or Lite to an NF box with nf_app_sync.py or the NF MCP.
---
# Deploy to an NF box

Need NF 3.10 or newer and a console login. Keep the env file outside git (`NF_CONSOLE_URL`, `CONSOLE_USERNAME`, `CONSOLE_PASSWORD`).

1. Run the tests first: `node --test nf-app/tests/*.test.mjs lite/tests/*.test.mjs`.
2. Choose the edition. **1 GB boxes (Raspberry Pi 3) get Lite only** (`lite/app.json`). Full (`nf-app/app.json`) is for
   machines with real resources (SQLite engine from about 2 GB, PGlite from 4 GB).
3. `python3 scripts/nf/hooks/nf_app_sync.py --env <env file> diff nf-app/app.json` then
   `... push nf-app/app.json` (`--skip-hooks` for UI only, `--hook fdd` for one hook; `run ... --hook fdd` runs it now).
   Alternative: NF MCP `manage_app` (create, `write_file`, `restart`) and `deploy_hook`; run a hook with its uuid.
4. Verify: page loads at `/api/v1/apps/static/open-fdd/` (or `open-fdd-lite`), no console errors, live values, hooks ran.

Rules: never run builds, npm installs, PGlite or tests on a small box; never write BACnet to field devices without the
owner's approval; static files are cached 5 minutes (use `?v=N`); `application.id` must equal the slug of `application.name`.
After NF login is enabled the manifest needs `auth.apiKey.scopes`. See `docs/install.md`.

Installing, upgrading, removing an old version or debugging a 401: use the `install-upgrade-troubleshoot` skill (run `doctor` first).

Before touching a live box read `nf-gotchas.md` (this folder). Related runbooks in `docs/operations/nf/`: `lite-vs-full.md`,
`front-door-caddy.md` (Caddy; set `APP_ID=open-fdd-lite` on a Lite box so the bare URL opens Lite),
`nf-upgrade-compose.md`, `bacnet-validate.md` (see the `bacnet-validate` skill). Read-only checks of a deployed box:
`scripts/nf/tools/` (`nf_portal_sensors.py`, `nf_sensor_history.py`).

## Live patching (last resort)

Do not hand-edit the box as the normal fix path. If a hotfix is required to unblock verification, follow the **Live patching a box** section in repo-root `AGENTS.md`: save remote copies, patch one path, commit identical bytes in git the same hour, refresh the push manifest, doctor, then open the PR. Coding agents do not deploy releases to NF sites; Grok Bot handles deploys after merge.

