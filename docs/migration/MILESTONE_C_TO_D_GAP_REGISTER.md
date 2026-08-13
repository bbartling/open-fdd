---
title: Milestone C → D gap register
parent: Migration
nav_order: 24
---

# Milestone C → D gap register

**Date:** 2026-07-28  
**Open-FDD tip:** `7fed6fb8`  
**Playground tip:** `d553e31` (`develop`)  
**Roadmap:** [#581](https://github.com/bbartling/open-fdd/issues/581) — C = Phases 6–7; D = Phase 8 + cleanup

Statuses: `VERIFIED` | `PARTIAL` | `NOT_DONE` | `DEFERRED`

## Hygiene

| Check | Status | Evidence |
|-------|--------|----------|
| open-fdd open PRs | VERIFIED | 0 |
| open-fdd remotes | VERIFIED | `master` only |
| playground open PRs | VERIFIED | 0 |
| playground remotes | VERIFIED | `develop` only |
| GHCR tip `sha-7fed6fb8` | PARTIAL | Publish run after #589 — verify digests in closeout when green |

## Milestone A residuals

| Item | Status |
|------|--------|
| `open_fdd.contracts` + generated rule manifest | DEFERRED |
| Remaining vibe20 ECM twins | DEFERRED |
| Playground GHCR retirement | DEFERRED |
| Broader forbidden-import suites | DEFERRED |

## Milestone B

| Item | Status |
|------|--------|
| Jobs FS + central API + stale/findings | VERIFIED (C0 adversarial) |
| RUNNING restart recovery | VERIFIED |
| Browser Playwright jobs soak | NOT_DONE |
| WattLab dump v2/v3 deep compat | PARTIAL |

## Milestone C (must finish before Phase 8)

| Item | Status | Notes |
|------|--------|-------|
| C0 adversarial + README/cookbook honesty | VERIFIED | #587 #588 |
| Typed `/api/analytics/*` envelopes | VERIFIED | #589 |
| Runtime Δt + economizer + UI prefer-central | PARTIAL | Live; pandas weekly fallback may remain |
| Sensor / schedule / mech / RCx / metering / plant | PARTIAL | Minimal compute; UI mostly pandas |
| Engine `datafusion` | NOT_DONE | Honest `central-analytics-v1` today |
| Historian / Feather → analytics | NOT_DONE | Inline samples only |
| Phase 6 exit: React → central only | NOT_DONE | |
| Phase 7 SQL parity evidence levels | PARTIAL | Docs residual |
| Pandas production retirement | NOT_DONE | |
| Filled benches + `sha-*` soak | NOT_DONE | |

## Cookbook / docs fortress

| Item | Status |
|------|--------|
| Dual cookbooks present | VERIFIED |
| Parity matrix + ownership CI | VERIFIED |
| README badge block + PyPI + 59/63 honesty | VERIFIED |
| Floor-size fortress asserts (D0) | VERIFIED after this PR |

## Milestone D scope (after C exit)

1. Finish Phase 6–7 (D1–D2)
2. Phase 8 job-native WattLab (D3)
3. Restricted EnergyPlus runner (D4)
4. Escape-hatch deletion + D closeout (D5)
