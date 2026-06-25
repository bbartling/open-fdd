# Open-FDD release cleanup ledger

Updated: 2026-06-25 (CLI source of truth)

## Current PRs

| PR | Title | Branch | CI | Status | Local UI inspection? |
|----|-------|--------|-----|--------|----------------------|
| [#381](https://github.com/bbartling/open-fdd/pull/381) | UI inspection build: Docker, auth, dashboard tabs | `integration/ui-inspection-build` | Rust/tests green; compose smoke may still run | **Use this branch** for local UI — has inspection scripts, API route fixes, `/exports` page | **Yes — primary branch** |
| [#382](https://github.com/bbartling/open-fdd/pull/382) | Docs cleanup for Rust-only Open-FDD | `docs/rust-readme-docs-ci-cleanup` | Mostly green | Docs/CI only — no runtime fixes | **No** — docs-only from `master`; use #381 for UI |

### Closed PRs (recent)

| PR | Title | Final state |
|----|-------|-------------|
| #379 | Rust auth / UI parity / Haystack / 5007 | Closed — superseded by #381 |
| #380 | PDF report builder + CSV validation | Closed — superseded by #381 |
| #378 | Auth login UX / RBAC | Closed |
| #377 | Operator dashboard UX | Merged to master |

## Current issues

| Issue | Title | Action | Reason |
|-------|-------|--------|--------|
| [#374](https://github.com/bbartling/open-fdd/issues/374) | Generic Data Export React UI | **Keep open** | `/exports` route exists on #381 with CSV downloads; missing last-export status and rich filters — partial MVP |
| [#367](https://github.com/bbartling/open-fdd/issues/367) | XLSX export support | **Keep open** | App is CSV-only; XLSX not implemented |
| [#369](https://github.com/bbartling/open-fdd/issues/369) | WASM sandbox for connector transforms | **Keep open** | Deferred; safe connectors only, no arbitrary transform execution |

## Ben — local dev launch (use PR #381 branch)

```bash
git fetch origin
git checkout integration/ui-inspection-build
git pull --ff-only

OPENFDD_ALLOW_LOCAL_BUILD=1 ./scripts/openfdd_inspection_build.sh --build --smoke
```

Expected:

- UI: http://127.0.0.1:8080
- Credentials: `workspace/bootstrap_credentials.once.txt` (plaintext — not `auth.env.local` hashes)
- Stop: `docker compose -f docker-compose.local.yml down`

Hot reload (optional): `./scripts/openfdd_ui_dev.sh --lan` → http://127.0.0.1:5173

Playwright browser smoke: **not implemented** — API/route smoke only via `openfdd_ui_smoke.sh`.
