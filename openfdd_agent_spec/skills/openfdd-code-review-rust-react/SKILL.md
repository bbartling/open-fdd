---
name: openfdd-code-review-rust-react
description: >-
  Review Open-FDD Rust and React changes against the canonical best-practice
  standard. Use when reviewing a PR, writing product Rust or frontend/web code,
  or auditing unwraps, locks, hooks, fetch races, or SPA accessibility.
---

# Open-FDD Rust and React code review

## When to use

- Reviewing a diff that touches `services/central`, product crates, `mcp`, or `frontend/web`
- Writing or refactoring that code
- An audit that asks whether agents follow the Rust and React standard

Authoritative text:

- Rust: [`docs/RUST_BEST_PRACTICES.md`](../../docs/RUST_BEST_PRACTICES.md)
- Rust suppressions: [`docs/RUST_LINT_HYGIENE.md`](../../docs/RUST_LINT_HYGIENE.md)
- React: [`docs/REACT_BEST_PRACTICES.md`](../../docs/REACT_BEST_PRACTICES.md)
- SPA product rules: [`openfdd-react-spa`](../openfdd-react-spa/SKILL.md)

Product code is the NF portal API and CSV ingest. No legacy protocol code (MQTT, BACnet, Haystack, Modbus, fieldbus, edge wire) and no dual-write paths belong in product code. Archived code lives in `archive/` and is not a workspace member. Do not review or restyle `archive/`. `services/central/src/ingest.rs` and `live_historian.rs` are the portal and CSV writer and are in scope.

Storage mandate ([`DATA_CONTRACT.md` § Storage mandate](../../DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)): **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing.** Flag as a blocking finding any diff that adds or extends a Parquet, Arrow, Arrow IPC, Feather or DataFusion dependency, store, cache, or execution path; writes telemetry anywhere but the one Timescale writer; or persists derived results outside PostgreSQL or bounded memory. The `crates/fdd_store` Parquet analytics cache is a known gap (Wave P2): a diff may shrink or remove it, never grow it.

## Review steps

1. Read the two best-practice docs. Do not invent a softer checklist.
2. Run the mechanical gates for the files you touched:
   - `cargo clippy -p <crate> --all-targets -- -D warnings` for each product crate
   - `cd frontend/web && npm run lint` when `frontend/web` changed
3. For anything the lints do not see (SQL built with `format!` from request text, secrets in logs, a fetch effect with no abort and no cleanup, a Plotly page imported eagerly), report it in the same shape as the docs.
4. Every finding has a brief why and a concrete refactor snippet. Lead with the answer.
5. Do not prescribe a crate-wide `#![allow]`. An unavoidable site gets the smallest `#[expect]` or `eslint-disable-next-line` and a one-line reason.

## Output

Use the headers in the two docs:

- Rust: Safety and memory, Performance and async, API design and idiomatic Rust, Style and tooling
- React: Rendering and performance, State and hooks, Architecture and API integration, Modern practices and safety

Put a count table first when the review covers a tree rather than one diff. "None." for an empty section.

## Skill home

`openfdd_agent_spec/skills/` is the only authoring tree. Do not create a parallel copy under `.cursor/skills/`, `.claude/skills/`, `.agents/skills/`, or a home directory. Sync with [`scripts/openfdd_install_agent_skills.sh`](../../../scripts/openfdd_install_agent_skills.sh) (`--sync`, optional `--user`). Orientation: [`openfdd_agent_spec/AGENTS.md`](../../AGENTS.md) and the repo [`AGENTS.md`](../../../AGENTS.md).

## Related skills

- [`openfdd-react-spa`](../openfdd-react-spa/SKILL.md) — product screens and quiet copy
- [`openfdd-architecture`](../openfdd-architecture/SKILL.md) — SPA versus central
- [`openfdd-milestone-a-pr`](../openfdd-milestone-a-pr/SKILL.md) — PR loop
