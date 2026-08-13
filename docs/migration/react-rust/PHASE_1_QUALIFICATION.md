# Phase 1 qualification pack (P1-M6-03)

Commit under qualification: record at merge time on `master` (see SESSION_LOG).

## Evidence checklist

| gate | evidence | status |
|---|---|---|
| Rust CI (fmt/clippy/tests) | GitHub Actions `Rust Stack CI` on M5–M6 merges | PASS (required green before each squash-merge) |
| React web (lint/type/unit/build) | `frontend/web` Vitest + `tsc` job in rust-ci | PASS |
| AppSec / Gitleaks / Trivy / Hadolint | AppSec + Stack Security workflows | PASS |
| Cookbook / docs-guard | Cookbook parity + Docs Pages | PASS |
| Hostile upload | `package.rs` unit + UploadPage vitest (M4-02) | PASS |
| Numeric/API parity samples | PARITY_EVIDENCE.md CAP-* rows M4–M5 | PASS (UNKNOWN cleared for shipped caps) |
| No-Python topology | `docker/compose.react.yml` + NO_PYTHON_STACK.md | PASS (config validated in CI) |
| Python exit matrix | PYTHON_EXIT_MATRIX.md — zero UNKNOWN/BLOCKED | PASS (M6-01) |
| React rollback drill | Switch compose from `compose.react.yml` → `compose.central.yml` (ui service); no data rewrite | DOCUMENTED (routing flip is Phase 2) |
| Feature flag | `OPENFDD_REACT_UI=1` → `/api/capabilities.capabilities.react_ui` | PASS |

## Digests

Immutable image digests are produced by GHCR publish workflows on `master` merges.
Operators should pin digests from the successful `Publish Open-FDD stack to GHCR` run for the exit SHA.

## Phase 1 exit gate

- [x] React workflows behind `react_ui` for Jobs→upload→map→FDD→plots→metering→findings→reports→WattLab→auth
- [x] No-Python compose profile exists and validates
- [x] Contracts versioned (`openfdd.api.contract.v1`)
- [x] Parity/security evidence logged
- [x] PYTHON_EXIT_MATRIX closed
- [x] Rollback path documented (React compose.central)
- [x] Phase 2 deletion PRs enumerated only (`PHASE_2_DELETION_CANDIDATES.md`)

**Phase 1 exit: APPROVED for Phase 2 entry (cutover control plane).**
