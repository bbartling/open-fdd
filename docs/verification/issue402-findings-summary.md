# Issue #402 findings summary (3.2.2 testbench)

**Report ID:** `rpt-issue402-322-bench`  
**GitHub:** [bbartling/open-fdd#402](https://github.com/bbartling/open-fdd/issues/402)

## Remediation status (3.2.3-prep branch)

| ID | Finding | Status in repo |
|----|---------|----------------|
| B-01 | GHCR 3.2.2 publish | Operational — use `openfdd_ghcr_watch_and_deploy.sh` |
| B-02 | uid 10001 workspace permissions | Fixed — bootstrap + validate + `openfdd_rust_ensure_container_workspace` |
| B-03 | Live BACnet 5007 not exercised | Field — `OPENFDD_SMOKE_DEVICE_INSTANCE=5007` smoke |
| H-01 | Haystack read-only | Fixed — `POST /api/haystack/write` (Basic auth / nHaystack) |
| H-02 | Parity not wired | Fixed — `openfdd_haystack_bacnet_parity.sh` |
| H-03 | Haystack gateway unhealthy | Docs + prep validate checks `local.nhaystack.toml` |
| H-04 | Rust PDF partial | Fixed — B-02 + `openfdd_issue402_rust_pdf.sh` |
| H-05 | rusty-bacnet PR #23 | Deferred — optional crates.io bump (see `docs/verification/rusty-bacnet-pr23-eval.md`) |
| M-01 | Demo endpoints | Gated behind `OPENFDD_DEV=1` |
| M-02 | README version stale | Fixed — 3.2.3 |
| M-03 | auth_init compose path | Fixed — resolves `docker-compose.yml` / edge compose |
| M-04 | BACnet remap API missing | Fixed — `PATCH /api/bacnet/driver/device/remap`, `DELETE /api/bacnet/driver/registry` |
| M-05 | Caddy optional | Documented in `docker/compose.edge.rust.yml` profiles |
| L-01 | Smoke simulate dead code | Removed from smoke harness |
| L-02 | simulate route naming | Added alias `POST /api/control/dry-run` |
| L-03 | building_insight stub | Documented stub response |

## Scripts added

- `scripts/openfdd_322_prep_validate.sh`
- `scripts/openfdd_322_ghcr_validation.sh`
- `scripts/openfdd_issue402_rust_pdf.sh`
- `scripts/openfdd_ghcr_watch_and_deploy.sh`
- `scripts/openfdd_driver_poll_1m.sh`
- `scripts/openfdd_haystack_bacnet_parity.sh`

## Field bench only

Live BACnet/Haystack/Modbus phases G–L run on the edge device after GHCR pull. Dev repo changes do not replace field evidence.
