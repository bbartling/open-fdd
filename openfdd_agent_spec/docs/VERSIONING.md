# Versioning

Distinguish these axes — do not collapse them into one “Open-FDD version” claim.

| Axis | Where it lives today | Notes |
| --- | --- | --- |
| Platform / Rust workspace | Root `Cargo.toml` `version` | Stack image semver tags — **4.0.2** |
| Python package | `open_fdd/__init__.py` / `pyproject.toml` | PyPI `open-fdd` **4.4.9** — `open_fdd.version.manifest()` |
| Displayed UI revision | `GET /api/health` → `{CARGO_PKG_VERSION}+sha` | SPA sidebar `4.0.2+shortsha` (7-char). Fallback: web `version.json` `{ version, git, image_tag }` |
| SQL rule registry | `sql_rules/registry.yaml` (+ file tree) | Prefer content hash in future manifest |
| Pandas cookbook / oracle | Docs + `open_fdd.rules` | Tied to package version when shipped |
| WattLab dump schema | vibe19 package / export code | v2/v3 compatibility matrix |
| Capability ledger | `docs/migration/react-rust/capabilities.yaml` | Vibe 21 recovery P1-M0 evidence SoT |
| Shared contracts schema | **Not shipped** | Phase 2 `open_fdd.contracts` |
| Container git SHA | GHCR `sha-<7>` + `:nightly` on master | Immutable verify uses `sha-*`. Extra `:4.0.2-n<run_number>` is a run pointer, not a pin. |
| EnergyPlus version | vibe20 image / runtime | When applicable |
| Unity WebGL artifact | Phase 4 (not shipped) | External ZIP + manifest; never Unity Editor in prod |

## Display vs tags

| What you see | Meaning |
| --- | --- |
| Sidebar / `/api/health` `4.0.2+abc1234` | Running **central** Cargo version + git SHA (`OPENFDD_GIT_SHA`) |
| `:nightly` | Floating master pointer (retargeted every publish) |
| `:sha-<7>` | Immutable image for that commit — pin this on benches |
| `:4.0.2` | Workspace semver alias (often same digest as nightly; not a signed-off stable) |
| `:4.0.2-n42` | Extra publish-run tag from `github.run_number` |

UI prefers health so the pin matches the **running central container**, not a stale web `version.json`.

## Tiny platform rev bumps

On each turnkey stack patch that ships to GHCR nightly, bump workspace patch (`3.5.N` → `3.5.N+1`) in root `VERSION` and Cargo workspace `version` (keep them identical). Sidebar then shows a new `3.5.N+shortsha` after pull. Do **not** bump PyPI `open-fdd` unless the Python package changed.

### Current platform tip (keep honest)

| When | Platform VERSION | Immutable pin | Notes |
| --- | --- | --- | --- |
| 4.0.2 workspace patch (2026-10-20) | **4.0.2** | `sha-<7>` after this bump merges to `master` | NF queue window + health, overview span/health/fault percent. Not an ops pin until GHCR publish is green. PyPI stays **4.4.9**. |
| 4.0.1 workspace patch (2026-10-20) | **4.0.1** | published with 4.0.1 | #1305–#1309 on `04673e4f`. PyPI stays **4.4.9**. |
| 4.0.0 portal (#1302) | **4.0.0** | `sha-fe7e06b` | Prior workspace tip. Central + web only. |

Older Soft-OPEN pins stay in [`MILESTONES.md`](../../MILESTONES.md). Never claim the new tip until GHCR publish is green and the `sha-*` digest resolves. Pin newest-by-created, not the `:nightly` name.

## Agent rules

1. Root README / Pages must not contradict PyPI or Cargo versions.
2. Consumer lower bounds must be truthful (`>=4.1.1` if APIs require 4.1.1).
3. Milestone A Phase 1 should add a **generated** version manifest (JSON) derived
   from canonical files — not hand-copied triples.
4. Container rebuilds should install a pinned/constraints Open-FDD wheel so the
   same source commit does not silently pull a newer PyPI release later.
5. Test channel for stack: `OPENFDD_IMAGE_TAG=nightly`. Qualify with `sha-*`.
6. Do **not** auto-commit `Cargo.toml` on every master push.

## Wheel integrity

```text
build one wheel → test that exact wheel → publish that exact wheel
→ dependent images install the expected released artifact
```
