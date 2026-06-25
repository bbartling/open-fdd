# Open-FDD release cleanup ledger

Generated: 2026-06-18 (cleanup pass on PR #381)

## Open pull requests

| PR | Branch | Base | CI | Mergeable | Decision | Blocking items |
|----|--------|------|-----|-----------|----------|----------------|
| [#381](https://github.com/bbartling/open-fdd/pull/381) | `integration/ui-inspection-build` | master | Green + CodeRabbit | MERGEABLE | **Continue / merge target** — this cleanup PR | Final UI smoke + ledger comment |
| [#380](https://github.com/bbartling/open-fdd/pull/380) | `feature/report-builder-csv-append-delete-validation` | master | Rust CI fail (older) | MERGEABLE | **Close as superseded by #381** | Full CSV append/delete validation deferred |
| [#379](https://github.com/bbartling/open-fdd/pull/379) | `fix/rust-ui-auth-haystack-5007-validation` | master | Green | MERGEABLE | **Close as superseded by #381** | Useful commits already stacked in #381 |

### PR comments posted

- #379: Superseded by #381 — auth/Haystack/UI parity preserved; long validation tracked separately.
- #380: Superseded by #381 — report builder UI preserved; CSV append/delete validation is follow-up.

## Open issues

| Issue | Title | Decision | Cleanup PR action |
|-------|-------|----------|-------------------|
| [#374](https://github.com/bbartling/open-fdd/issues/374) | Generic Data Export React UI | **Partial close** if `/exports` ships; else update | Add Data Export page wired to `/api/export/meta` |
| [#367](https://github.com/bbartling/open-fdd/issues/367) | XLSX export support | **Leave open** | Comment: CSV is supported; XLSX is future work |
| [#369](https://github.com/bbartling/open-fdd/issues/369) | WASM sandbox for connector transforms | **Leave open** | Comment: safe connectors only; no arbitrary upload |

## Fixes in this cleanup pass

- Missing API routes: model equipment, modbus/json-api driver tree + poll status, host stats, favicon
- Navigation: remove Drivers tab; move Live FDD Validation under Ops; add Data Export
- SQL FDD: block run without equipment; hide raw JSON validation by default
- Host stats: structured response instead of unknown endpoint
- Auth/UI smoke scripts updated for new routes

## Intentionally deferred (linked issues)

- XLSX export (#367)
- WASM custom transforms (#369)
- Full CSV append/delete proof (supersedes #380 remainder)
- 1-hour / 6-hour field validation (not in cleanup pass)
