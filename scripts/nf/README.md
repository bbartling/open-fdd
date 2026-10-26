# NF portal checkpoint

Lab probe for a Normal Framework portal. Point selection is explicit UUIDs
(`NF_POINT_UUIDS`), never display names.

```bash
# chmod 600 scripts/nf/.env — never commit
cp scripts/nf/.env.example scripts/nf/.env
# fill NFURL, NF_CLIENT_ID, NF_CLIENT_SECRET, and NF_POINT_UUIDS
python3 -m pip install -r scripts/nf/requirements.txt
python3 scripts/nf/read_sensors.py
```

Or export those variables in the shell (no `.env` file).

`NF_POINT_UUIDS` is a comma-separated list of provider point ids. Example maps
live in `provider_sites.bosspi.example.json` (`provider_point_id`) and
`bosspi_semantic_meta.json` (`point_id`).

Product path is the Rust `DataProvider` NF driver ([Wave-NF plan](../../.cursor/plans/nf_portal_ingest_mega_rev_20261018.plan.md)). This script is the human/agent smoke only. History reads on the product path are `GET /api/v1/point/data`.

## Site files

| File | Site |
| --- | --- |
| `provider_sites.bosspi.json` | Bench Pi, 5 points |
| `provider_sites.bosspi.example.json` | Placeholder template |
| `provider_sites.acme.json` | ACME, 233 points: 230 bare-minimum HVAC BACnet points (NF trend period 300 s) plus 3 Open-Meteo weather variables from the NF hook (20 min) |

Credentials stay in a `chmod 600` env file outside git; the JSON uses
`env:NF_CLIENT_ID` / `env:NF_CLIENT_SECRET`. How to add a site, the hourly pull,
and the 7-day NF window: [`openfdd-nf-provider`](../../openfdd_agent_spec/skills/openfdd-nf-provider/SKILL.md).
Edge install, licensing, and trend periods: [`openfdd-nf-edge-bench`](../../openfdd_agent_spec/skills/openfdd-nf-edge-bench/SKILL.md).

## Freshness check (run after onboarding, and whenever data looks stale)

```bash
python3 scripts/nf/check_acme_portal_fresh.py                       # ACME defaults, ~/.secrets/nf_acme.env
python3 scripts/nf/check_acme_portal_fresh.py --env ~/.secrets/nf_<site>.env \
    --sites scripts/nf/provider_sites.<site>.json --sample rtu_01:supply-air-temp
```

It reads the **remote portal** only, using a browser-like User-Agent and the token from the
env file's `NFURL` / `NF_CLIENT_ID` / `NF_CLIENT_SECRET`. Secrets are never printed. It
checks a BACnet sample (RTU-01 SA/RA/OA, Tracer SC OA, a JCI and a Trane VAV zone temp,
the HW plant supply and return) plus every `equip_type: weather` point. It prints point,
value, units, last timestamp (America/Chicago) and age. A point fails if it is older than
30 min, null or non-numeric, or outside its range (°F −40..130 after a °C→°F conversion
when NF reports Celsius, RH 0..100, HW 32..220, weather dewpoint ≤ dry bulb + 0.5).
The script exits 1 with a FAIL list, or prints PASS. Stdlib only.

## NF hooks (JavaScript on the NF box)

NF code is kept in this repo under [`hooks/`](hooks/README.md). That folder holds the
hook source, a manifest, and `nf_app_sync.py` (push, run now, status, diff, pull back).
Edit the code in the repo and push it. If someone edits it in the NF console, pull it
back before committing. ACME runs `open_meteo_weather.js` every 20 min.
Agents with the NF MCP connector should use `deploy_hook`, `manage_hooks` (`run`, `runs`, `logs`),
`read_values` and `diagnose`. See [`openfdd-nf-edge-bench`](../../openfdd_agent_spec/skills/openfdd-nf-edge-bench/SKILL.md).
