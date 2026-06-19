# Local dev status — updated 2026-06-18 (session 2)

Branch: `fix/overnight-auth-rcx-parity-niagara-ux` — targets [PR #333](https://github.com/bbartling/open-fdd/pull/333).

## Completed this session

### Trend plot — History dropdown
- Extended **History** select: 14d, 30d, **Month to date**, **Last month**, YTD, **Custom range** (datetime-local)
- Backend `/api/timeseries/readings` now accepts `start` + `end` (hours up to 8760)
- Shared presets: `workspace/dashboard/src/lib/time-window.ts`

### Building Comfort — offline / bad reads
- Zone day/night averages now **exclude**:
  - Equipment marked **offline** (poll health)
  - Stale columns with very low `valid_ratio`
  - Implausible temps: **0°F** or outside **50–105°F**
- New zone field: `excluded_offline`

### Niagara — save station auth from browser
- **Station password** field on Niagara tab (saved server-side, gitignored)
- `workspace/data/niagara/station_secrets.json` + `resolve_password()` fallback
- No plaintext in `niagara_stations.json`

### public-snapshot 401 noise
- Dashboard stream skips anonymous `public-snapshot` when auth is required and user is not signed in (shows “Sign in…” instead of console 401 spam)

### Local AI / Ollama — disabled
- `workspace/ollama.env.local` → `OFDD_OLLAMA_ENABLED=0`
- `interactive_chat_enabled()` and `should_use_ollama_for_insight()` respect that flag → **AI Agent nav greyed out**
- No Ollama process was running on this host (nothing to delete)

### Bench 5007 — model + FDD rules
- `python scripts/setup_bench_afdd.py` — imported BRICK model (10 points), 4 Arrow rules
- `python scripts/register_bench_sql_arrow_rules.py` — **bench-oa-temp-high-arrow** + **bench-oa-temp-high-sql**
- **BACnet discover** still needs Docker + OT network (`./scripts/setup_local_testbench.sh`) — not available on this VM without sudo/Docker

### Tests
- `./scripts/build_and_test.sh` — **584 passed** (after production asset fix)
- Dashboard vitest — 53 passed

## GitHub auth — action required

`gh` is installed at `~/bin/gh` but **not logged in**. Run in your terminal:

```bash
export PATH="$HOME/bin:$PATH"
gh auth login -h github.com -p https -w
```

Follow the browser link and enter the one-time code. Then:

```bash
cd ~/open-fdd
gh pr view 333
git push -u origin fix/overnight-auth-rcx-parity-niagara-ux   # when ready
```

## Docker — still needs sudo once

```bash
cd ~/open-fdd && ./scripts/local_machine_bootstrap.sh
newgrp docker
./scripts/docker_build.sh && ./scripts/openfdd_stack.sh up
```

## Niagara 502 on test bench

`502 Cannot connect to host 192.168.204.11:80` means this dev VM cannot reach benserver’s Niagara — expected unless you’re on the bench LAN/VPN. Password save fix is for when the bridge **can** reach the station.

## Uncommitted changes

Review with `git diff` / `git status`. Key areas:
- Plot history UI + timeseries API
- Zone temp offline filtering
- Niagara browser password storage
- Ollama disable gate
- Bench rule registration script

## Quick restart (no Docker)

```bash
cd ~/open-fdd && source .venv/bin/activate
set -a && source workspace/auth.env.local && set +a
export OPENFDD_REPO_ROOT=$PWD OPENFDD_WORKSPACE_DIR=$PWD/workspace OFDD_DESKTOP_DATA_DIR=$PWD/workspace/data
export PYTHONPATH=$PWD/workspace/api:$PWD OFDD_OLLAMA_ENABLED=0
uvicorn openfdd_bridge.main:app --host 127.0.0.1 --port 8765
```

Login: integrator credentials in `workspace/auth.env.local`.
