# Live FDD validation (development & testing)

Open-FDD supports **live validation against configurable BACnet devices**. Production API routes, UI labels, and default configs use generic terms (`source`, `device`, `equipment`, `validation run`) — not a specific lab bench.

## Supported harness

Use the generic Rust validation harness:

```bash
OPENFDD_SMOKE_PROFILE=local_bacnet_fdd_validation \
OPENFDD_SMOKE_DEVICE_INSTANCE=<your-bacnet-device-instance> \
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

`scripts/bench_5007_long_smoke.sh` is a **deprecated wrapper** — use `smoke_live_fdd_validation.sh` with a local profile instead.

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

Local `*.local.toml` files are gitignored. Set `device_instance`, IPs, and point lists for **your** BACnet/Modbus/JSON sources — not committed defaults.

## API routes

| Route | Purpose |
|-------|---------|
| `GET /api/validation-runs/current/status` | Validation run status |
| `POST /api/validation-runs/current/cycle` | Poll + historian + FDD eval |
| `POST /api/validation-runs/current/inject-scenario` | Safe simulation inject |
| `GET /api/historian/validation/status` | Historian row counts |

Legacy `/api/bench/*` aliases may remain temporarily for backward compatibility.

## Runtime note

Production validation uses the Rust edge only. Historical Python stack notes: [archive/python-era.md](../archive/python-era.md).

## No-hardcoding audit

```bash
./scripts/audit_no_hardcoding.sh
```

## Related docs

- [Smoke profiles](../../workspace/smoke-profiles/README.md) (if present) and gitignored `workspace/smoke-profiles/local/*.local.toml`
- [FDD Wires verification](../verification/fdd-wires.md)
