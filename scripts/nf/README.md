# scripts/nf — build and deploy tooling for the NF app

| Script | What |
|---|---|
| `build_rule_catalog.py` | `sql/fdd` registry + role map + NF classes → `nf-app/static/fdd-catalog.json` (`--check` in CI) |
| `build_sql_pack.py` | Render the 77 SQL rules (SI) → `nf-app/rules/pack-postgres.json`, translate → `pack-sqlite.json` (`--check` in CI) |
| `gen_rule_docs.py` | Catalog → `docs/fdd-rules.md` (`--check` in the docs build) |
| `measure_engines.mjs` | Memory/time of the FDD engines: `node scripts/nf/measure_engines.mjs sqlite 1 7` |
| `hooks/nf_app_sync.py` | Deploy an app manifest to an NF console: `status`, `push`, `run`, `diff`, `pull` |
| `tools/` | Read-only, tag-driven checks of a live NF: `nf_portal_sensors.py` (LAN vs portal), `nf_sensor_history.py`, `nf_bacnet_validate.py` (bacpypes3, run on a PC); see [`tools/README.md`](tools/README.md) |

Deploy (env file outside git — see [`../../.env.example`](../../.env.example)):

```bash
python3 scripts/nf/hooks/nf_app_sync.py --env ~/.secrets/nf_site_console.env push nf-app/app.json   # full edition
python3 scripts/nf/hooks/nf_app_sync.py --env ~/.secrets/nf_site_console.env push lite/app.json     # Open-FDD Lite
python3 scripts/nf/hooks/nf_app_sync.py --env ~/.secrets/nf_site_console.env run  nf-app/app.json --hook fdd
```

`push` records the installed revision twice — `static/version.json` (shown in the app header as
"v5.0.0 · <commit>") and the NF app setting `version` (shown in the NF console, and by `status`) —
stamps js/css URLs with a content hash (NF caches app files for 5 minutes), checks that the
manifest id equals NF's slug of the app name, and restarts the app runtimes. `--hook ID` limits
push/run to selected hooks; `--skip-hooks` pushes files only. Agents can also deploy through the
NF MCP connector (`manage_app`, `deploy_hook`) — see [docs/install.md](../../docs/install.md).
