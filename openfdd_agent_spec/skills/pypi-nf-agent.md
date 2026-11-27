---
name: pypi-nf-agent
description: Use the PyPI package open-fdd (open-fdd-nf, pandas rules, reports) to read a Normal Framework box and run FDD from an agent.
---
# PyPI tools for agents (`pip install "open-fdd[nf]"`)

Full guide: `docs/python-tools.md`. The package is 4.x; the NF app is 5.x (`open-fdd-version --pretty` shows both).

1. **Connect** with env vars, never in code: `NF_URL` (or `NF_LAN_URL` / `NFURL` for the portal, or `NF_CONSOLE_URL`),
   `NF_CLIENT_ID` + `NF_CLIENT_SECRET` (API key) or `NF_CONSOLE_USER` + `NF_CONSOLE_PASSWORD`. The same file
   `nf_app_sync.py` reads (`NF_CONSOLE_URL`, `CONSOLE_USERNAME`, `CONSOLE_PASSWORD`) works. `NF_CA_FILE` or
   `--pin-server-cert` for a self-signed LAN cert. A secrets file goes in `--env FILE` and is never committed.
   The tools only read. `open-fdd-nf rules` uses the hook's single-AHU run proof and the 50 h/week occupancy default.
2. **Look first**: `open-fdd-nf info`, then `open-fdd-nf model --json` to see which point fills each role.
   An equip with few roles is a modeling problem: fix tags/classes/units in NF (MCP), not in the script.
3. **Run**: `open-fdd-nf rules --days 7 --json`. `not-assessed` is not healthy; read `missing_roles` and
   `df.attrs["skipped"]` (a unitless command or a wrong unit is skipped, never guessed).
4. **Data**: `open-fdd-nf pull --equip X --days 7 --out x.csv` (SI). Offline, use the app's CSV export with
   `open_fdd.nf.export.csv_frames` or `open-fdd-report --csv`.
5. **Report**: `open-fdd-report --nf --days 14 --out out [--docx]` (needs `open-fdd[reporting]`); ECM workbooks via `open-fdd-ecm`.
6. **Units are SI** (display °C, Pa, L/s, kW, kWh). Wire tokens are QUDT local names (`DEG_C`, `PA`, …). Roles scaled
   `fraction` in `sql/fdd/input_contract.json` are already 0–1. Do not convert inside rules.
7. Portal (`--via portal`) needs an API key and cannot read `/api/v1/bacnet/*`; use the LAN for BACnet.
8. Never print or paste secrets, `docker logs` or env dumps (NF logs the backup SAS URL in plain text).

9. **Read-only analytics.** The `analytics` hook runs `sql/analytics/*.sql` (in-process SQLite,
   `nf-app/hooks/lib/sql-analytics.js`). Pandas twins live in `open_fdd/analytics/sql_*.py`. CLI:
   `open-fdd-nf analyze weekly-runtime | cooling | economizer | fault-timeline | roles | explain-view`
   `[--site --equip --rule --days --view --json]`. Use those tools instead of re-deriving run hours, cooling bins,
   economizer residuals or fault timelines from raw history. They cannot write. Every row has `siteRef`, `equipRef` and
   `equipUuid`: key on `equipUuid` (two sites can share a display name). `fault-timeline` states are `confirmed` / `ok` /
   `unknown`; `unknown` (no data) is never `ok`. An ambiguous `--equip` is an error listing the candidates: add `--site`
   or pass the uuid. Details: `docs/python-tools.md`.

10. **Offline anomaly and ML** (no NF needed): `pip install "open-fdd[anomaly]"`, then
    `open-fdd-anomaly screen FOLDER --out DIR [--engine sql]` (z-score in portable SQL with `--engine sql`), `open-fdd-ml detect | benchmark | download` (`open-fdd[ml]`). See the `ml-fdd` skill
    and `docs/pypi-agent-tools.md` for every tool.

11. **Model / ontology checks** (read-only): `open-fdd-ontology-audit --from-nf --out r` doctors the app's RDF export
    (standard vs Open-FDD vs site terms, identity, history links). Offline workflow: the `audit-ontology-coverage` skill.

Python: `NFClient.from_env()` -> `load_model` -> `equipment_frames(client, model, start, end)` -> `run_rules(frames)`.
