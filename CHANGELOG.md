# Changelog

## Unreleased

## 4.0.1 — 2026-10-20

Workspace patch on master `04673e4f` (4.0.0). `/api/health` reports `4.0.1+<sha>` from the central crate version. PyPI `open-fdd` stays **4.4.9** (no publish). `archive/` is unchanged. No Timescale backup and no Parquet or DataFusion product path.

- **#1305** — Updates and central startup apply forward-only schema and leave existing historian rows in place. A full wipe needs a new `OPENFDD_RESET_DB` token plus `OPENFDD_ALLOW_DESTRUCTIVE_DB=1`. That token is recorded and will not purge again.
- **#1306** — Product ingest is the Normal Framework portal and CSV only. BACnet, Modbus, Haystack wire, fieldbus, the MQTT broker and client, and the compiled Parquet micro-batch writer stay under `archive/ot-edge/unmaintained`. They are not workspace members, CI jobs, or GHCR images. `/api/health` reports portal provider count plus CSV ingest. Retired with that cut: the BACnet/MQTT CI workflow, Wave C isolated workflow, standalone MQTTS smoke, MQTT/BACnet guard gates, the broker ACL / field-exposure security checks, and the OT compose-selection checker. `openfdd_health_check.sh` stays for the portal.
- **#1307** — NF portal and CSV crates deny `unwrap`, `expect`, lock-across-await, and the related Clippy restriction lints. The SPA treats hooks, keys, `any`, and direct DOM access as ESLint errors.
- **#1308** — Remove 3.x OT-edge, ACME, and Railway stress tooling that is not on the 4.0 portal path. Field-container source and `archive/` were left in place for #1306.
- **#1309** — An empty Timescale database copies the Building 50 starter pack once and does not delete rows. NF hourly ingest accepts a short validation window. The provider panel shows the last pull. Starter rules apply to stamped equipment, trend overlays carry `confirmed_fault`, and motor weekly hours count status. The central image does not build the archived MQTT provisioner.
