# Long smoke test (legacy runbook name)

> **Note:** Prefer [live FDD validation (development)](../testing/live-fdd-validation.md) with a gitignored local smoke profile. This page retains a historical filename for script compatibility only.

Validates a configured BACnet device and FDD state transitions over an extended run. Use on a live OT LAN with `OPENFDD_BACNET_MODE=live`. Device instance and point list come from your local `*.local.toml` profile — not from product defaults.

## Prerequisites

```bash
# Live BACnet overlay (see docs/verification/bacnet-nic-setup.md)
docker compose -f docker-compose.yml -f docker-compose.bacnet-live.yml up -d --build

# Or production stack already running with live commission.env
./scripts/openfdd_rust_edge_validate.sh
```

## Run (default 6 hours)

```bash
./scripts/bench_5007_long_smoke.sh
# or shorter lab run:
BENCH_SMOKE_HOURS=0.25 BENCH_SMOKE_INTERVAL_SEC=60 ./scripts/bench_5007_long_smoke.sh
```

## What it captures

Each interval (default **5 min**) the script logs to `workspace/logs/bench_5007_long_smoke/`:

| Capture | Purpose |
| --- | --- |
| `capture_*.json` | BACnet driver tree snapshot |
| `fdd_test_*.json` | OA temp SQL rule test-sql result |
| `assignments_*.json` | AI propose-assignments draft |
| `summary.jsonl` | One-line status per interval |

## Pass criteria (after run)

- BACnet device **5007** points remain in driver tree
- `test-sql` returns `ok: true` with DataFusion engine
- `fault_raw` / confirmation counts change when bench values move (live OT)
- No auth or stack health regressions across the run
- `summary.jsonl` has no repeated HTTP failures

## AI modeling during smoke

While the long smoke runs, agents can:

1. `GET /api/model/haystack` — inspect model
2. `POST /api/fdd-wires/propose-assignments` — draft bindings for device 5007 points
3. Test additional rules from [SQL HVAC FDD cookbook](../rule-cookbook/sql-hvac-fdd.md)

See [AI Haystack modeling](../ai-agent/haystack-and-assignments.md).

## Simulated mode note

In **simulated** BACnet mode, point values are synthetic — FDD state may not change with real physics. The script still validates API stability over time. Use **live** mode on the bench LAN for meaningful fault transitions.
