# Live FDD validation (development & testing)

Open-FDD supports **live validation against configurable BACnet devices**. Production API routes, UI labels, and default configs use generic terms (`source`, `device`, `equipment`, `validation run`) — not a specific lab bench.

## Supported harness

Use the generic Rust validation harness:

```bash
OPENFDD_SMOKE_PROFILE=local_bacnet_fdd_validation \
OPENFDD_SMOKE_DEVICE_INSTANCE=5007 \
OPENFDD_SMOKE_DURATION_HOURS=6 \
OPENFDD_SMOKE_INTERVAL_SECONDS=300 \
OPENFDD_SMOKE_LIVE_FDD=1 \
OPENFDD_SMOKE_REQUIRE_CONFIRMED_FAULT=1 \
OPENFDD_SMOKE_VALIDATE_DOCKER=1 \
OPENFDD_SMOKE_VALIDATE_MODBUS=1 \
OPENFDD_SMOKE_VALIDATE_JSON_API=1 \
OPENFDD_SMOKE_JSON_API_URL="https://httpbin.org/get" \
OPENFDD_SMOKE_NO_DEMO_PASS=1 \
./scripts/smoke_live_fdd_validation.sh
```

`scripts/bench_5007_long_smoke.sh` remains as a **deprecated wrapper** only.

### Short dry-run (simulation, no OT writes)

```bash
OPENFDD_SMOKE_DURATION_HOURS=0.05 \
OPENFDD_SMOKE_INTERVAL_SECONDS=30 \
OPENFDD_SMOKE_SAMPLES=3 \
OPENFDD_SMOKE_SIMULATE=1 \
OPENFDD_SMOKE_REQUIRE_CONFIRMED_FAULT=1 \
./scripts/smoke_live_fdd_validation.sh
```

## Smoke profiles

Copy the example profile and customize for your site:

```bash
cp workspace/smoke-profiles/local/local_bacnet_fdd_validation.local.toml.example \
   workspace/smoke-profiles/local/local_bacnet_fdd_validation.local.toml
```

Local `*.local.toml` files are gitignored. BACnet device **5007** appears only as an **example** local development value — not a product assumption.

## API routes

| Route | Purpose |
|-------|---------|
| `GET /api/validation-runs/current/status` | Validation run status |
| `POST /api/validation-runs/current/cycle` | Poll + historian + FDD eval |
| `POST /api/validation-runs/current/inject-scenario` | Safe simulation inject |
| `GET /api/historian/validation/status` | Historian row counts |

Legacy `/api/bench/5007/*` aliases remain temporarily for backward compatibility.

## Python oracle policy

**Decision (2026-06):** The Python runtime is **formally superseded** on `master` by the Rust edge production line (PRs #362/#363). Regression coverage uses:

- Rust unit/integration tests
- DataFusion SQL + historian golden paths via `inject-scenario`
- CI FDD wires smoke
- Live validation harness (`smoke_live_fdd_validation.sh`)

Historical Python references live in git history and archived PRs; restoring `open_fdd/` is optional on a legacy branch, not required for production.

## Port compatibility

| Stack | Health URL |
|-------|------------|
| Legacy Python edge | `http://127.0.0.1:8765/health` (historical) |
| Rust production edge | `http://127.0.0.1:8080/health` internal, `https://localhost/api/health` via Caddy |

8765 is not reintroduced unless explicitly configured as a dev-only alias.

## No-hardcoding audit

```bash
./scripts/audit_no_hardcoding.sh
```

## Related docs

- [Bench 5007 long smoke (legacy name)](../verification/bench-5007-long-smoke.md) — historical runbook; prefer this page for new work.
