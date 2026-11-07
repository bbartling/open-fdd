---
name: pypi-nf-agent
description: Use the PyPI package open-fdd (open-fdd-nf, pandas rules, reports) to read a Normal Framework box and run FDD from an agent.
---
# PyPI tools for agents (`pip install "open-fdd[nf]"`)

Full guide: `docs/python-tools.md`. The package is 4.x; the NF app is 5.x (`open-fdd-version --pretty` shows both).

1. **Connect** with env vars, never in code: `NF_URL` (or `NF_LAN_URL` / `NFURL` for the portal), `NF_CLIENT_ID` +
   `NF_CLIENT_SECRET` (API key) or `NF_CONSOLE_USER` + `NF_CONSOLE_PASSWORD`, `NF_CA_FILE` for a self-signed LAN cert.
   A secrets file goes in `--env FILE` and is never committed. The tools only read.
2. **Look first**: `open-fdd-nf info`, then `open-fdd-nf model --json` to see which point fills each role.
   An equip with few roles is a modeling problem: fix tags/classes/units in NF (MCP), not in the script.
3. **Run**: `open-fdd-nf rules --days 7 --json`. `not-assessed` is not healthy; read `missing_roles` and
   `df.attrs["skipped"]` (a unitless command or a wrong unit is skipped, never guessed).
4. **Data**: `open-fdd-nf pull --equip X --days 7 --out x.csv` (SI). Offline, use the app's CSV export with
   `open_fdd.nf.export.csv_frames` or `open-fdd-report --csv`.
5. **Report**: `open-fdd-report --nf --days 14 --out out [--docx]` (needs `open-fdd[reporting]`); ECM workbooks via `open-fdd-ecm`.
6. **Units are SI** (degC, Pa, L/s, kW, kWh; commands 0-1). Do not convert inside rules.
7. Portal (`--via portal`) needs an API key and cannot read `/api/v1/bacnet/*`; use the LAN for BACnet.
8. Never print or paste secrets, `docker logs` or env dumps (NF logs the backup SAS URL in plain text).

Python: `NFClient.from_env()` -> `load_model` -> `equipment_frames(client, model, start, end)` -> `run_rules(frames)`.
