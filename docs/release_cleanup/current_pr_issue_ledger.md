# Open-FDD release cleanup ledger

Updated: 2026-06-26 (anti-hardcoding / model-driven validation cleanup)

## Current PRs

| PR | Title | Branch | CI | Decision |
|----|-------|--------|-----|----------|
| [#385](https://github.com/bbartling/open-fdd/pull/385) | Local validation reporting workflow | `feature/local-validation-reporting-workflow` | pending | **Active — anti-hardcoding cleanup** |
| [#383](https://github.com/bbartling/open-fdd/pull/383) | Rust Haystack driver | `feature/haystack-niagara-driver` | merged into #385 | Leave open until CI green |
| [#381](https://github.com/bbartling/open-fdd/pull/381) | UI inspection build | `integration/ui-inspection-build` | Green | Superseded by merge into #385 |

## Anti-hardcoding audit

| File | Value | Allowed? | Fix |
|------|-------|----------|-----|
| `edge/src/validation/profile.rs` | `192.168.204.14` modbus default | **Not allowed** | Removed; empty host, `modbus_enabled=false`; typed section loader |
| `edge/src/drivers/modbus_live.rs` | env fallback to private IP | **Not allowed** | `host_port()` returns `Result`; reads profile first |
| `edge/src/drivers/modbus.rs` | `RPI_POINTS_JSON` @ 192.168.204.14 | **Not allowed** | Profile-driven live points; `not_configured` status |
| `edge/src/drivers/bacnet.rs` | bench5007, 1173/1168/1192, 192.168.204.* | **Not allowed** | Profile-driven simulated device/points; generic demo IDs |
| `edge/src/drivers/bacnet_live.rs` | discover default 5007 | **Not allowed** | Uses validation profile `device_instance` |
| `edge/src/model/smoke_profile.rs` test | 5007, 1173, 192.168.204.14 | **Not allowed** | Generic equip/instance 42 / 1001 |
| `edge/src/historian/store.rs` | equipment default `5007` | **Not allowed** | Uses `active_profile().equipment_id` |
| `edge/src/model/assignments.rs` | equip:5007, analog-input,1192 | **Not allowed** | Generic `equip:demo-ahu` / 100x IDs |
| `docker-compose.yml` | MODBUS/BACnet private defaults | **Not allowed** | Empty env defaults (must configure) |
| `.env.example` | 192.168.204.*, 5007 | **Not allowed** | Placeholders + `OPENFDD_VALIDATION_PROFILE` |
| `scripts/openfdd_csv_append_validation.sh` | CSV equipment 5007 | **Not allowed** | Requires profile/env equipment id |
| `scripts/smoke_live_fdd_validation.sh` | implicit 5007 profile | **Not allowed** | Requires `local_validation_profile.local.toml` |
| `scripts/openfdd_rust_edge_bootstrap.sh` | 192.168.204.* commission env | **Not allowed** | Placeholder commission template |
| `docs/deployment/*.md` | 192.168.204.55 examples | **Not allowed** | Replaced with `<your-lan-ip>` |
| `workspace/smoke-profiles/local/local_haystack_5007_parity.local.toml.example` | 5007, 1173… | **Allowed** | Example only; copy to gitignored `.local.toml` |
| `edge/src/main.rs` | `/api/bench/5007/*` legacy routes | **Allowed (deferred)** | Legacy bench API surface; tracked for removal |
| `scripts/audit_no_private_bench_hardcoding.sh` | CI guard | **Added** | Wired into `.github/workflows/ci.yml` |

## Config / profile behavior

- **Source of truth:** `OPENFDD_VALIDATION_PROFILE` → `workspace/smoke-profiles/local/local_validation_profile.local.toml` (gitignored)
- **Example:** `workspace/smoke-profiles/local/local_validation_profile.local.toml.example`
- **Haystack UI:** Integrations → Haystack → Save configuration → `workspace/haystack/local.nhaystack.toml` (gitignored)
- **Modbus/Haystack missing:** API/UI returns `not_configured` / skipped — not failed
- **Reports:** equipment id, points, SQL from active profile + historian — no bench constants

## Example command

```bash
OPENFDD_VALIDATION_PROFILE=workspace/smoke-profiles/local/local_validation_profile.local.toml \
  ./scripts/openfdd_one_hour_validation_report.sh
```

## Tests run (cleanup step — no full 1-hour validation)

- `cargo test --workspace` — pass
- `cargo fmt --all` — applied
- `npm ci && npm run build` — pass
- `docker compose config` — pass
- `bash -n` on validation/smoke scripts — pass
- `./scripts/audit_no_private_bench_hardcoding.sh` — pass

## Deferred

- **Legacy `/api/bench/5007/*` routes** in `edge/src/main.rs` — remain for backward compat; remove in follow-up issue
- **Full 1-hour validation** — blocked until profile configured locally and user runs orchestrator
- **Issue #384** — 6-hour validation after 1-hour workflow stable
