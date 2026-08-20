# Versioning

Distinguish these axes — do not collapse them into one “Open-FDD version” claim.

| Axis | Where it lives today | Notes |
| --- | --- | --- |
| Platform / Rust workspace | Root `Cargo.toml` `version` | Stack image semver tags — **3.3.2** |
| Python package | `open_fdd/__init__.py` / `pyproject.toml` | PyPI `open-fdd` **4.4.2** — `open_fdd.version.manifest()` |
| Displayed UI revision | `GET /api/health` → `{CARGO_PKG_VERSION}+sha` | SPA sidebar `3.3.2+shortsha` (7-char). Fallback: web `version.json` `{ version, git, image_tag }` |
| SQL rule registry | `sql_rules/registry.yaml` (+ file tree) | Prefer content hash in future manifest |
| Pandas cookbook / oracle | Docs + `open_fdd.rules` | Tied to package version when shipped |
| WattLab dump schema | vibe19 package / export code | v2/v3 compatibility matrix |
| Capability ledger | `docs/migration/react-rust/capabilities.yaml` | Vibe 21 recovery P1-M0 evidence SoT |
| Shared contracts schema | **Not shipped** | Phase 2 `open_fdd.contracts` |
| Container git SHA | GHCR `sha-<7>` + `:nightly` on master | Immutable verify uses `sha-*`. Extra `:3.3.2-n<run_number>` is a run pointer, not a pin. |
| EnergyPlus version | vibe20 image / runtime | When applicable |
| Unity WebGL artifact | Phase 4 (not shipped) | External ZIP + manifest; never Unity Editor in prod |

## Display vs tags

| What you see | Meaning |
| --- | --- |
| Sidebar / `/api/health` `3.3.2+abc1234` | Running **central** Cargo version + git SHA (`OPENFDD_GIT_SHA`) |
| `:nightly` | Floating master pointer (retargeted every publish) |
| `:sha-<7>` | Immutable image for that commit — pin this on benches |
| `:3.3.2` | Workspace semver alias (often same digest as nightly; not a signed-off stable) |
| `:3.3.2-n42` | Extra publish-run tag from `github.run_number` |

UI prefers health so the pin matches the **running central container**, not a stale web `version.json`.

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
