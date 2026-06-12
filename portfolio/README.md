# Open-FDD Portfolio (central desk)

**benserver / analyst workstation** — multi-site rollup, CSV history, and Plotly Dash. Not deployed on edge VMs.

| Path | Role |
|------|------|
| `sites.json` | Site registry (`base_url`, credentials via env or inline) |
| `sites.json.example` | Template |
| `collector/` | Poll `GET /api/building/portfolio-rollup` per site |
| `store/` | CSV append + `FaultIntervalSummary` / `TuningProposal` schema |
| `dash/app.py` | Central portfolio dashboard (`:8050`) |
| `agent/MEMORY.md`, `agent/SKILLS.md` | Agent desk notes for Acme tuning loops |
| `data/` | Runtime CSV + `latest/*.json` (gitignored) |

## Commands

```bash
source infra/ansible/secrets/acme.env.local   # integrator password for Acme
python3 scripts/portfolio_collect.py
python3 scripts/portfolio_collect.py --json
./scripts/run_portfolio_dash.sh               # http://127.0.0.1:8050
```

Edge API: `workspace/api/openfdd_bridge/portfolio_rollup.py` → `GET /api/building/portfolio-rollup`.

Published docs: [docs/portfolio/central-collection.md](../docs/portfolio/central-collection.md), [Central API](../docs/portfolio/central-api.md).

## Central API (validation + RCx)

```bash
pip install -r portfolio/requirements.txt
./scripts/run_central_api.sh    # :8060
curl http://127.0.0.1:8060/api/central/sites
curl -X POST http://127.0.0.1:8060/api/central/validation/run \
  -H 'Content-Type: application/json' \
  -d '{"site_id":"acme","duration_hours":0}'
```
