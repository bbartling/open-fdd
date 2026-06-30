# 3.2.2 release prep checklist (issue #402)

Field validation for **3.2.2** on a Linux edge bench (`~/open-fdd`). See [issue #402](https://github.com/bbartling/open-fdd/issues/402).

## Before GHCR publish (B-01)

- [ ] CI **Publish Rust edge to GHCR** green for tag `3.2.2`
- [ ] `docker manifest inspect ghcr.io/bbartling/openfdd-edge-rust:3.2.2` succeeds
- [ ] Optional: `./scripts/openfdd_ghcr_watch_and_deploy.sh` on edge host

## Bootstrap / permissions (B-02)

- [ ] `./scripts/openfdd_rust_edge_bootstrap.sh --start` (or site update)
- [ ] `workspace/reports/generated` exists and is writable by container uid **10001**
- [ ] `chmod 600 workspace/auth.env.local`; readable by bridge container
- [ ] `./scripts/openfdd_322_prep_validate.sh` passes
- [ ] `POST /api/reports/draft` returns `ok:true` (included in validate script)

## Live driver modes

- [ ] `workspace/data.env.local`: `OPENFDD_BACNET_MODE=live`, `OPENFDD_MODBUS_MODE=live`
- [ ] `./scripts/openfdd_322_ghcr_validation.sh` after pull

## Live OT validation (B-03, phases G–L)

```bash
OPENFDD_SMOKE_DEVICE_INSTANCE=5007 ./scripts/smoke_live_fdd_validation.sh
./scripts/openfdd_haystack_bacnet_parity.sh   # after parity profile configured
./scripts/openfdd_issue402_rust_pdf.sh
```

- [ ] Who-Is sees BACnet device **5007**
- [ ] `summary.jsonl`: `bacnet_device_seen=true`, `bacnet_poll_ok=true`
- [ ] Haystack gateway healthy when `local.nhaystack.toml` configured (H-03)
- [ ] Haystack `SomeRandomPoint` write/read/release (H-01)
- [ ] Modbus `.14` baseline (phase J)
- [ ] FDD 5-minute confirmation on live OT (phase K)

## Artifacts

Store under `workspace/logs/` and `workspace/reports/rpt-issue402-322-bench/`.

## Hard rules

- Never `docker compose down -v`
- Never delete `workspace/`
- No Python for reports — Rust API only
- Do not commit or paste secrets
