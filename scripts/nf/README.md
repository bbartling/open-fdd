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

`NF_POINT_UUIDS` is a comma-separated list of provider point ids. The shipped
shape-only example is [`provider_sites.example.json`](provider_sites.example.json).

Product path is the Rust `DataProvider` NF driver ([Wave-NF plan](../../.cursor/plans/nf_portal_ingest_mega_rev_20261018.plan.md)). This script is the human/agent smoke only. History reads on the product path are `GET /api/v1/point/data`.

## Site files (operator host)

Real site JSON lives **outside git** (for example `~/.config/openfdd/sites/*.json`).
The repo ships only [`provider_sites.example.json`](provider_sites.example.json)
with placeholder hosts and per-site `env:NF_CLIENT_ID_*` / `env:NF_CLIENT_SECRET_*`
names.

Central accepts:

- inline JSON in `OPENFDD_PROVIDER_SITES`
- one file path
- a comma-separated list of site files
- a directory of `*.json` site files (sorted by filename)

Each site resolves its own `env:NAME` credential refs. A missing secret marks
only that site `auth_not_configured`.

Credentials stay in a `chmod 600` env file outside git. How to add a site, the
hourly pull, and the 7-day NF window:
[`openfdd-nf-provider`](../../openfdd_agent_spec/skills/openfdd-nf-provider/SKILL.md).
Edge install, licensing, and trend periods:
[`openfdd-nf-edge-bench`](../../openfdd_agent_spec/skills/openfdd-nf-edge-bench/SKILL.md).

## Freshness check (run after onboarding, and whenever data looks stale)

```bash
python3 scripts/nf/check_portal_fresh.py \
  --env ~/.secrets/nf_site.env \
  --sites ~/.config/openfdd/sites/site_a.json \
  --points ~/.config/openfdd/sites/site_a_probes.json
```

`--points` is a JSON list of `{equipment_id, role}` objects or `EQUIP:ROLE` lines.
Repeat `--sample EQUIP:ROLE` instead of `--points` for a short probe list. The
script always includes every `equip_type: weather` point from the site file.

It reads the **remote portal** only, using a browser-like User-Agent and the
token from the env file's `NFURL` / `NF_CLIENT_ID` / `NF_CLIENT_SECRET`. Secrets
are never printed. Points fail when older than `--max-age-min` (30), null or
non-numeric, or outside a plausible range (temperature, humidity, hot water).
Weather points older than `--warn-age-min` (25) print WARN without failing alone.
Exit 1 lists FAIL reasons; exit 0 prints PASS.
`python3 scripts/nf/check_portal_fresh.py --self-test` checks thresholds offline.
Stdlib only.

## NF hooks (JavaScript on the NF box)

NF code is kept in this repo under [`hooks/`](hooks/README.md). That folder holds the
hook source, a manifest, and `nf_app_sync.py` (push, run now, status, diff, pull back).
Edit the code in the repo and push it. If someone edits it in the NF console, pull it
back before committing. Agents with the NF MCP connector should use `deploy_hook`, `manage_hooks` (`run`, `runs`, `logs`),
`read_values` and `diagnose`. See [`openfdd-nf-edge-bench`](../../openfdd_agent_spec/skills/openfdd-nf-edge-bench/SKILL.md).
