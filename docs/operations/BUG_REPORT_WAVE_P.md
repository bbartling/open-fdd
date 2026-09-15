# Wave P — Residual stress + GH tidy tracker

**Parent:** [`BUG_REPORT_WAVE_O.md`](BUG_REPORT_WAVE_O.md) Soft residuals · plan [`.cursor/plans/wave_p_residual_stress_gh_tidy_ce235993.plan.md`](../../.cursor/plans/wave_p_residual_stress_gh_tidy_ce235993.plan.md)

**Authority:** Wave P **owns unfinished Wave O Soft** + local docs/SPA + Kali O2c/P2c product tip. **No Railway re-pin while Kali owns the hub** unless operator OK.

## Tip / GHCR

| Item | Status |
|------|--------|
| O12b Creekside meter (#934) | **MERGED** master `3.5.20` / `aea817fd` |
| GHCR Publish #934 | hub in flight; fieldbus failed once (Docker Hub oauth 500 — re-run) |
| Railway / ACME re-pin | **DEFERRED** (Kali owns hub) |
| Local tip (docs+SPA+O2c) | Branch `fix/wave-p-docs-spa-local` — ship next |

## Soft-OPEN (carry from Wave O)

| ID | Note |
|----|------|
| **wave-o1-tenant-path-migrate** | Hub-root `building=*` still; backup-first `tenants/{tid}/` migrate |
| **wave-o2a-audit-volume-assert** | Gates 31/33/34 HTTP ACL green; `security_audit.jsonl` volume assert not wired |
| **wave-o4-synth59-handoff** | Missing synth59 zip → blocks `fully_qualified` final stress |
| **wave-o5-stage-c** | IdP/MFA/SKU commercial |
| **p2c-mqtt-acl-staging** | ACL notes in `deploy/mqtt/acl` + skill; broker proof = Kali staging |
| **p8-acme-hw / weather / rtu / vav** | ACME catalog expands after Kali unlock + Mint scrape |

## Mint closed locally (this train)

| Item | Evidence |
|------|----------|
| Docs GH Pages blast + Quick Start | `docs/` nav_exclude Operations; QS local+Railway |
| SPA p8* (Mapping/RCx/FDD/scroll/stems) | `frontend/web` on branch |
| Kali V1–V3 pre-auth | JWT router + nginx Fonts/HSTS/`security.txt` |
| MT IDOR matrix + admin/agent least-privilege | `services/central/tests/preauth_disclosure.rs` |
| Agent skills | `openfdd-mt-security`, `openfdd-rcx-fdd-plot-poll` |

## Exit (P9)

Wave P **OPS PINNED** only when: last tip GHCR + Railway re-pin (operator OK) + **ONE** full `run_railway_hub_stress.sh` cited + 0 open PRs + stale `wave-*` remotes deleted + Soft-OPEN ≤ Stage C (+ honest synth59 if still missing).
