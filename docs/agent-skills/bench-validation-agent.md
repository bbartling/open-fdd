# Bench validation agent (local benserver)

**Local bench only. Read-only.**

## Topology

| Item | Value |
|------|-------|
| Open-FDD host | benserver |
| BACnet device | instance **5007**, router `2000:7` (MS/TP) |
| Niagara station | `https://192.168.204.11` |
| Niagara BACnet folder | `slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points` |
| Password env | `OPENFDD_NIAGARA_ADMIN_PASSWORD` (never commit) |

`/stream/health` returns **302** before login (reachability). **200** after SCRAM.

## One-command validation

```bash
export OPENFDD_NIAGARA_ADMIN_PASSWORD='…'
python3 scripts/bootstrap_bench_dual_source.py
python3 scripts/bench_validate_bacnet_vs_niagara.py --write-report
```

## API tools (bridge must be running)

| Action | Endpoint |
|--------|----------|
| Bench health | `GET /api/bench/health` |
| Cross-source validate | `POST /api/bench/validate/bacnet-vs-niagara` |
| Poll status | `GET /api/bench/poll-status` |
| Poll cadence | `GET /api/bench/poll-cadence` |
| Niagara test | `POST /api/niagara/stations/bench9065/test` |
| Niagara discover | `POST /api/niagara/stations/bench9065/discover` |
| Start/stop Niagara poll | `POST …/poll/start` / `…/poll/stop` |
| BACnet driver tree | `GET /api/bacnet/driver/tree` |

## MCP / agent notes

- Browser → Open-FDD API only (no direct Niagara WebSocket from React).
- Preserve Niagara ORDs exactly (`$20`, `$2d`, `$23`). PowerShell: single-quote ORDs.
- Default Niagara discovery excludes `proxyExt` (10 points, not 20).
- Branch: `fix/3.0.34-bugs`; push and watch PR #300 CI + CodeRabbit.

## Overnight

```bash
python3 scripts/run_overnight_bench_smoke.py
```

See [overnight-bench-smoke.md](../overnight-bench-smoke.md) and [bench-bacnet-vs-niagara.md](../bench-bacnet-vs-niagara.md).
