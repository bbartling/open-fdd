# WSL → Linux runtime validation handoff (PR #385)

Updated: 2026-06-26

## WSL audit summary

WSL is the **build and static-check** machine. Live BACnet/Modbus/Haystack validation runs on the **Linux runtime tester** with OT-LAN access.

| Check | WSL result |
|-------|------------|
| `git status` | Clean on `feature/local-validation-reporting-workflow` |
| `gh pr checks 385` | Green (16/16) before handoff commit |
| `./scripts/audit_no_private_bench_hardcoding.sh` | Pass — no production bench strings |
| `cargo fmt --all --check` | Pass |
| `cargo clippy --workspace --all-targets -- -D warnings` | Pass after clippy + protocol cleanup |
| `cargo test --workspace` | Pass (110 integration + unit tests) |
| `npm ci && npm run build` | Pass from `workspace/dashboard/` |
| `docker compose config` | **Skipped** — Docker not installed in this WSL distro; CI covers compose |

## Protocol stack honesty (no smoking mirrors on live paths)

| Driver | Live stack | Simulated / CI path |
|--------|------------|---------------------|
| BACnet | `bacnet-client` / [rusty-bacnet](https://github.com/jscott3201/rusty-bacnet) via `bacnet_live.rs` | `OPENFDD_BACNET_MODE=simulated` — labeled `bacnet-simulated` |
| Modbus | [rusty-modbus-client](https://github.com/jscott3201/rusty-modbus) via `modbus_live.rs` | `OPENFDD_MODBUS_MODE=simulated` — labeled `modbus-simulated` |
| Haystack | `rusty-haystack-client` SCRAM/Basic HTTP | `OPENFDD_HAYSTACK_FIXTURE=1` only — labeled `fixture`; unconfigured returns `not_configured` |
| JSON API | `reqwest` fetch + JSON body point extraction | No synthetic points on HTTP 200 |

Live BACnet override scan **does not** fall back to registry simulated priority data on discovery failure.

## Allowed hardcoding locations (audit allowlist)

Private bench strings appear only in:

- `edge/src/validation/audit.rs` — forbidden-pattern unit tests
- `workspace/smoke-profiles/local/*.local.toml.example` — operator copies to gitignored `*.local.toml`
- `docs/verification/*`, `docs/release_cleanup/*` — documentation
- Comment-only examples in `scripts/openfdd_*_smoke.sh` (comment lines skipped by audit)

## Linux runtime tester — exact next commands

```bash
cd ~/open-fdd
git fetch origin
gh pr checkout 385
git pull --ff-only

OPENFDD_PUBLISH_HOST=0.0.0.0 ./scripts/openfdd_inspection_build.sh --build --smoke --public-url "http://<linux-tester-ip>:8080"

OPENFDD_VALIDATION_PROFILE=workspace/smoke-profiles/local/local_5007_validation.local.toml ./scripts/openfdd_dev_5007_report_validation.sh
```

Replace `<linux-tester-ip>` with the tester’s LAN address (not WSL).

### Prerequisites on Linux tester

1. Copy `workspace/smoke-profiles/local/local_5007_validation.local.toml.example` → `local_5007_validation.local.toml` and fill device IPs/objects.
2. Set live modes in env or compose overlay:
   - `OPENFDD_BACNET_MODE=live`
   - `OPENFDD_MODBUS_MODE=live` (if Modbus bench present)
   - Haystack: configure `OPENFDD_HAYSTACK_BASE` + credentials (do **not** set `OPENFDD_HAYSTACK_FIXTURE=1` on bench)
3. OT-LAN NIC bound per [docs/verification/bacnet-nic-setup.md](../verification/bacnet-nic-setup.md).

## Do not run on WSL

- 1-hour `openfdd_dev_5007_report_validation.sh` against real device 5007
- Live BACnet writes
- GHCR publish / merge (human gate)
