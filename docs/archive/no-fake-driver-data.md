# No fake driver data (production policy)

Open-FDD edge drivers and APIs must never fabricate field telemetry, BACnet points, or FDD fault rows in production code.

## Driver behavior

- **Unconfigured driver** → `configured: false`, empty `devices` / `sources` / `points`, status `not_configured` or `disabled`.
- **Configured driver** → load from workspace config, env, or imported Haystack/BACnet mapping only.
- **Connection failure** → return the real error; do not substitute canned values.

## Historian and SQL FDD

- DataFusion rules run against persisted historian tables (`telemetry`, `telemetry_pivot`).
- If the historian has no rows, SQL endpoints return a clear error or empty result — not sample Arrow rows.
- `/api/rules/batch` executes saved active rules from `workspace/data/fdd_wires/rules/`.

## Fixtures

- Test fixtures belong under `edge/tests/fixtures/` or `#[cfg(test)]` modules.
- They are not compiled into production runtime paths and must not appear in `edge/src/` production modules.

## CI guard

The anti-hardcoding audit runs in Rust CI:

```bash
./scripts/audit_no_private_bench_hardcoding.sh
cargo test -p open_fdd_edge_prototype production_sources_have_no_forbidden_demo_or_bench_ids
```

Forbidden terms include private bench IPs, `equip:demo-*`, `site:demo`, public test URLs (`httpbin`, `postman-echo`), and legacy smoke/demo API paths.

AppSec workflow (`.github/workflows/appsec.yml`) adds `cargo audit`, gitleaks, trivy, and npm audit on pull requests.
