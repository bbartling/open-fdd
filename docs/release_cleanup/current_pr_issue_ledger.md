# Open-FDD release cleanup ledger

Updated: 2026-06-25 (anti-hardcoding audit — #385 blocked until clean)

## Current open PRs

| PR | Title | Branch | CI (latest) | Status |
|----|-------|--------|-------------|--------|
| [#385](https://github.com/bbartling/open-fdd/pull/385) | Local validation reporting workflow | `feature/local-validation-reporting-workflow` | Rust tests failing on prior push; re-run after audit fix | **Active — anti-hardcoding cleanup in progress** |
| [#386](https://github.com/bbartling/open-fdd/pull/386) | Dev 5007 RCx validation harness | `feature/dev-5007-rcx-validation-report` | CI in progress | **Blocked until #385 audit passes** — do not merge harness before model-driven cleanup |
| [#382](https://github.com/bbartling/open-fdd/pull/382) | Docs cleanup for Rust-only Open-FDD | `docs/rust-readme-docs-ci-cleanup` | — | Docs-only; independent |

## Last five PRs reviewed

| PR | Title | State | Notes |
|----|-------|-------|-------|
| #383 | Rust Haystack driver | CLOSED (superseded) | Merged into #385 |
| #381 | UI inspection build | CLOSED (superseded) | Merged into #385 |
| #380 | PDF report builder + CSV validation | CLOSED | Precursor to #385 reports |
| #379 | Rust UI auth + Haystack + 5007 smoke hardening | CLOSED | Introduced bench coupling — being removed in #385 audit |
| #378 | Auth login UX / RBAC | CLOSED | Unrelated to bench hardcoding |

## Open issues

| Issue | Title |
|-------|-------|
| [#384](https://github.com/bbartling/open-fdd/issues/384) | Run 6-hour validation after 1-hour report workflow is stable |
| [#374](https://github.com/bbartling/open-fdd/issues/374) | Follow-up: generic Data Export React UI (/exports) |
| [#369](https://github.com/bbartling/open-fdd/issues/369) | Propose WASM sandbox for custom connector transforms |

## Hardcoding audit status

**#385 is blocked** until `./scripts/audit_no_private_bench_hardcoding.sh` passes and production code no longer branches on bench point names.

| Area | Status | Fix |
|------|--------|-----|
| `edge/src/drivers/bacnet.rs` priority-array | **Fixed** | Reads `simulated_priorities` from point/profile metadata; no `ACTUATOR-0` / name heuristics |
| `edge/src/validation/profile.rs` | **Fixed** | `BacnetPointRole` with `object_type`, `writable`, `simulated_priorities`; profile TOML parser |
| `edge/src/model/assignments.rs` | **Fixed** | Generic demo AHU ids (`equip:demo-ahu`, `point:demo-actuator`) |
| `scripts/audit_no_private_bench_hardcoding.sh` | **Expanded** | Forbidden patterns + allowlist + CI wired |
| `edge/src/validation/audit.rs` | **Expanded** | Rust unit tests flag `ACTUATOR-0`, `C06-0-10VDC-O`, private IP |
| Reports | **Fixed** | Title/content from request/model; test proves no bench strings |
| Example profiles | **Fixed** | Placeholders only in `*.local.toml.example` |
| `docker-compose.bacnet-live.yml` | **Fixed** | Requires `.env` for bind/router/discover — no private IP defaults |
| `docs/ai-agent/haystack-and-assignments.md` | **Fixed** | Generic profile-driven mapping |
| Legacy `/api/bench/5007/*` | **Deferred** | Allowed in `main.rs` until follow-up issue |
| Full 1-hour validation run | **Intentionally not run** | Blocked until audit passes |

## Model-driven behavior

- **Validation source of truth:** `OPENFDD_VALIDATION_PROFILE` → gitignored `*.local.toml`
- **Examples:** `local_validation_profile.local.toml.example`, `local_5007_validation.local.toml.example`
- **Priority-array (simulated):** profile point line `|analog-output|true|8:55.0` → `simulated_priorities` on point JSON
- **Reports:** `create_draft` / `from_validation_run` use workspace model + artifact summary — no bench constants
- **Remote UI:** relative `/api/*` default; `openfdd_inspection_build.sh --public-url` + `openfdd_ui_smoke.sh --base-url`

## Tests / checks (this audit pass)

```bash
cargo fmt --all --check
cargo test --workspace -p open_fdd_edge_prototype
bash -n scripts/audit_no_private_bench_hardcoding.sh
./scripts/audit_no_private_bench_hardcoding.sh
```

Full 1-hour validation **not run** — blocked until audit green on #385.

## Deferred

- Remove legacy `/api/bench/5007/*` routes (#384 follow-up)
- Merge #386 dev harness after #385 audit lands on master
