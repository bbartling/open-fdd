# Rust best practices (canonical review standard)

This is the review standard for Open-FDD product Rust: the NF portal API and CSV ingest (`services/central` portal and CSV paths, the crates those paths link, and `mcp`). Suppression procedure stays in [`RUST_LINT_HYGIENE.md`](RUST_LINT_HYGIENE.md): no crate-wide `#![allow]`, smallest-scope `#[expect]` with a one-line constraint comment.

Product code does not contain legacy protocol implementations or dual-write paths. MQTT, BACnet, Haystack, Modbus, fieldbus, and the edge wire process are not product code. They live in `archive/` and are not workspace members, not CI build targets, and not compose services. Do not add them back. `services/central/src/ingest.rs` and `live_historian.rs` are the portal and CSV writer. They follow this deny set. There is no module-level allow for a protocol module. Dual-write (a second historian, a Parquet or Feather mirror, or a protocol bridge that writes the same sample twice) is forbidden on the product path. Timescale is the only product historian. The `edge` crate that remains in the workspace is the package and SQL helper central links, not a protocol driver.

Analyze Rust for anti-patterns, safety issues, performance bottlenecks, and non-idiomatic design. For each issue give a brief why and a concrete idiomatic refactor snippet.

Lead with the answer. Use headers and bullets. Do not bury the finding under a preamble.

## 1. Safety and memory

- Unhandled `.unwrap()` / `.expect()` that should use `?`, `match`, or a fallback default.
- Unnecessary `unsafe` or code that bypasses compile-time safety.
- Heavy `.clone()` used to dodge the borrow checker.

Tests (`#[cfg(test)]` and `#[test]`) may use `.unwrap()` / `.expect()`. Production code may not. `clippy.toml` sets `allow-unwrap-in-tests` and `allow-expect-in-tests` (they are separate switches) so the restriction lints stay on for library and binary code while unit tests stay exempt. Integration tests under `tests/` are not `cfg(test)`, so those switches do not cover them. Each `tests/*.rs` binary starts with a file-level allow for `unwrap_used`, `expect_used`, `print_stdout`, `print_stderr`, and `dbg_macro`, with that reason. That allow is not for library or binary production code.

A poisoned `std::sync::Mutex` or `RwLock` on a request or ingest path recovers with `lock().unwrap_or_else(std::sync::PoisonError::into_inner)`. The success path is the same guard. Poison means another thread already panicked while holding the lock; panicking again takes down the caller. Do not hold that guard across `.await`.

```rust
let mut guard = state.ingest_ok.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
*guard += 1;
```

Static header values use `HeaderValue::from_static`. A `HeaderValue` built from a runtime string uses `HeaderValue::from_str` and returns the handler's existing error type. Do not `.parse().unwrap()` on a request path.

## 2. Performance and async

- `std::sync::Mutex` guards held across `.await` (deadlock risk). Use `tokio::sync::Mutex` for a guard that must span an await, or drop the std guard before the await.
- Unnecessary allocations in loops (repeated `String` / `Vec` creation).
- Overused `RefCell` / `Rc` where `&` / `&mut` suffice. `Rc<String>` / `Rc<Vec<_>>` is `clippy::rc_buffer`.

Blocking file or database work does not run on the async executor. Use `tokio::task::spawn_blocking` (central already does this for export downloads). Do not add a new `.await` while a std mutex guard is live.

## 3. API design and idiomatic Rust

- Public functions take `&str` / `&[T]`, not `&String` / `&Vec<T>`.
- Implement std traits (`Display`, `From` / `Into`, `AsRef`, `Default`) instead of ad-hoc methods.
- Ignored `#[must_use]` or an unhandled `Result` / `Option` is a defect. Prefer `?`. Last resort: `let _ = …;` plus a one-line why.

Libraries use `thiserror` (or a small local error enum) for typed errors. `anyhow` stops at binary and composition edges (`main`, job runners, `fdd_rules` registry loading). Do not `unwrap` a `Result` to avoid threading an error type through a request handler.

## 4. Style and tooling

- Complexity that violates Clippy's standard lints (workspace `-D warnings`).
- `println!` / `eprintln!` / `dbg!` are not product logging. Use `tracing`. A process that is about to exit before any subscriber exists may keep one `eprintln!` only with a smallest-scope `#[expect(clippy::print_stderr)]` and a reason.
- `cargo audit` is the dependency advisory gate (`.github/workflows/appsec.yml`). Do not silence an advisory without a tracked exception in that workflow's existing policy.
- Integer casts on untrusted input use `TryFrom` / `try_into` or an explicit range check. `as` stays legal for casts the compiler can see are lossless (for example a `u32` hour that is already `0..=23` into a wider type) and for in-memory lengths that cannot exceed the target. Do not deny every `as` in the workspace; that lint is pedantic and noisy. Do deny a cast that truncates a request field, a CSV cell, or a network length.

## 5. SQL, secrets, panics, channels

- SQL values are sqlx bind parameters (`$1`, `.bind(...)`). Never interpolate a request string into SQL with `format!`.
- Dynamic identifiers (column role, equipment id used as an identifier) are not bind parameters. They pass a validator such as `safe_ident` and are double-quoted. Rule SQL text comes from the shipped `sql/fdd` pack, then a wrapper `SELECT` around that trusted body. That wrapper is not a place to splice user text.
- Timeouts bound every outbound HTTP client. Ingest and live-writer queues are bounded (`sync_channel` capacity, lease limits). An unbounded channel on a network path is a defect.
- Secrets (passwords, JWT, broker passwords, raw `Authorization` values) do not appear in `tracing` fields, `Debug` impls, or error strings returned to the client.
- Request handlers do not panic. A missing invariant in a handler returns the handler's `Result` error. A programming bug outside the request path (closed semaphore that the process never closes, thread-spawn failure with no `Result` channel) may keep a panic only with `#[expect]` and a one-line reason.

## Output shape

```markdown
## Findings

### Safety and memory
- **`path.rs:line` `symbol`** — why this is wrong.
  ```rust
  // idiomatic replacement
  ```

### Performance and async
### API design and idiomatic Rust
### Style and tooling
```

If a section has no findings, write "None." Counts go in a table before the findings when the review is an audit.

## Mechanical enforcement

Product crates opt into `[workspace.lints.clippy]` from the root `Cargo.toml`. `archive/` is excluded from the workspace and is not cleaned by this standard. CI is `cargo clippy --workspace --all-targets -- -D warnings` (Rust 1.95 in GitHub Actions). Do not add a module-level allow to skip protocol code that was deleted. New product modules follow the deny set.

Denied on product crates:

| Lint | Why |
| --- | --- |
| `clippy::unwrap_used` | Production unwrap |
| `clippy::expect_used` | Production expect |
| `clippy::await_holding_lock` | Std lock held across `.await` |
| `clippy::ptr_arg` | `&String` / `&Vec<T>` in public APIs |
| `clippy::redundant_clone` | Clone that does not change ownership |
| `clippy::rc_buffer` | `Rc<String>` / `Rc<Vec<_>>` |
| `clippy::print_stdout` | `print!` / `println!` |
| `clippy::print_stderr` | `eprint!` / `eprintln!` |
| `clippy::dbg_macro` | `dbg!` |

`clippy.toml` sets `allow-unwrap-in-tests`, `allow-expect-in-tests`, `allow-print-in-tests`, and `allow-dbg-in-tests`. That is the test exemption. It is not a crate-wide `#![allow]`.

## Related

- Hygiene and `#[expect]`: [`RUST_LINT_HYGIENE.md`](RUST_LINT_HYGIENE.md)
- Review skill: [`../skills/openfdd-code-review-rust-react/SKILL.md`](../skills/openfdd-code-review-rust-react/SKILL.md)
- React standard: [`REACT_BEST_PRACTICES.md`](REACT_BEST_PRACTICES.md)
- Root [`AGENTS.md`](../../AGENTS.md) § Rust hygiene
