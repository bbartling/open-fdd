# Rust lint hygiene (agents)

Eliminate suppressions; fix the cause. CI uses `-D warnings` — treat warnings as failures.

The review standard (what to flag, and the Clippy denies) is [`RUST_BEST_PRACTICES.md`](RUST_BEST_PRACTICES.md). This file is only how to suppress a lint that must remain.

## 1. Scan and remove

Scan `#[allow(...)]` / `#![allow(...)]` — remove and fix:

| Lint | Fix |
|------|-----|
| `dead_code` | Unused → **DELETE** (Git keeps history). Upcoming-only → `_` prefix. Real public API → ensure `pub` is intentional and used. |
| `unused_variables` / `unused_assignments` | `_` for ignore; `_guard` / `_lock` for RAII holds; else delete. |
| `unused_must_use` | Prefer `?` or `match`/log. Last resort: `let _ = …;` **plus a one-line why**. |
| Reckless `unwrap` / `expect` on production paths | `Result` / `Option` + `?` or combinators. Tests may keep expect with a clear message. |

## 2. Unavoidable suppressions

- Smallest possible scope (item / statement — never module-wide unless unavoidable).
- Prefer `#[expect(...)]` with a **constraint comment** (why the lint must fire / why expect is correct).
- **Never** crate-wide `#![allow(...)]`.

## 3. Scope of sweeps

- Prefer **scoped** sweeps on packages touched by the current patch cycle.
- Do not RAM-melt a full-workspace rewrite on bensbench; CI is source of truth for `-D warnings`.
- Fuel / OpenAPI stub re-exports that are intentional API surface may use `#[allow(unused_imports)]` only when matching established product pattern — prefer wiring real callers.

## Related

- Review standard: [`RUST_BEST_PRACTICES.md`](RUST_BEST_PRACTICES.md)
- React standard: [`REACT_BEST_PRACTICES.md`](REACT_BEST_PRACTICES.md)
- Root [`AGENTS.md`](../../AGENTS.md) § Rust hygiene
- Version bumps: [`VERSIONING.md`](VERSIONING.md)
- Patch-cycle BUG_REPORT: [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../../docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md)
