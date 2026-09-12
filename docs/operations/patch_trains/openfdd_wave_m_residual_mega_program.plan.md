---
name: Wave M durable results + residual mega
overview: "OPS PINNED 3.5.7 (sha-0bfcd81) - Track D + M1-M3 landed. M5 Mint stress PARTIAL (fully_qualified=false). M4 Stage C late. Soft-OPEN wave-m-m5-mint-bench."
todos:
  - id: m0-hygiene
    content: "M0 - Soft-OPEN scrub + Wave M ACTIVE + plan mirror"
    status: completed
  - id: d1-repro
    content: "D1 - Root-cause report (SHA vs digests; storage; UX leads)"
    status: completed
  - id: d2-durable-state
    content: "D2 - Authoritative persistent state + atomic results"
    status: completed
  - id: d3-compute-vs-read
    content: "D3 - Durable AFDD runs/checkpoints; no browser-driven full recompute"
    status: completed
  - id: d4-ux-session
    content: "D4 - Auto-load results; session-gen cache; 401 race fix"
    status: completed
  - id: d5-release-cmd
    content: "D5 - One release orchestrator + honest backup"
    status: completed
  - id: m1-782-sse
    content: "M1 - #782 Central JWT SSE"
    status: completed
  - id: m2-sql-anomaly
    content: "M2 - sql-anomaly screening (lab-safe)"
    status: completed
  - id: m3-lab-mt
    content: "M3 - Lab multi-tenant enable; prod stays OFF"
    status: completed
  - id: m4-stage-c
    content: "M4 - Stage C IdP/MFA (late gated)"
    status: pending
  - id: m5-enhanced-stress
    content: "M5 - ENHANCED stress gates 00-17 + durable/flood; fully_qualified; PINNED"
    status: pending
isProject: false
---

# Wave M - Durable results + residual mega (post-Wave L)

**Cursor SoT:** [`wave_m_residual_mega_0c09093d.plan.md`](../../../../.cursor/plans/wave_m_residual_mega_0c09093d.plan.md)
**Mint closeout train:** [`wave_m_mint_finish_16d1a0ef.plan.md`](../../../../.cursor/plans/wave_m_mint_finish_16d1a0ef.plan.md)

## Where we are - **OPS PINNED 3.5.7 (M5 PARTIAL)**

| Item | State |
|------|--------|
| **Program** | **OPS PINNED** product 3.5.7 / `sha-0bfcd81` — durable results + SSE + release |
| **Prior** | Wave L **CLOSED / PINNED** 3.5.6 | ops `sha-e80237c` | stress `20260912T033836Z` |
| **Mode** | `multi_tenant=false` in prod until Stage C checklist |
| **M5** | Mint stress `20260912T231928Z` **`fully_qualified=false`** — Soft-OPEN `wave-m-m5-mint-bench` |
| **Gate 18** | durable session **PASS** |

### Progress board

```text
[x] M0  Hygiene + Soft-OPEN scrub + plan mirror + Wave M ACTIVE
[x] D1  Root-cause repro report
[x] D2  Durable scoped state + atomic results
[x] D3  Compute vs read (AFDD durable runs)
[x] D4  UX / session lifecycle
[x] D5  Release orchestrator + backup honesty
[x] M1  #782 SSE
[x] M2  sql-anomaly (lab-safe)
[x] M3  Lab MT enable (prod OFF)
[ ] M4  Stage C (late)
[ ] M5  ENHANCED stress fully_qualified (Mint residual)
```

## Completion

Deploy a qualified update, reopen a job, see correct latest completed analytics/faults without manually rebuilding state in the UI.

**Landed:** #918 / health `3.5.7+0bfcd81b949f` / volume `OPENFDD_RULE_RESULTS_DIR` / release `20260912T211258Z`.

**Not yet:** claim `fully_qualified=true` until fieldbus kit + docker + synth59 + AFDD flood green on Mint or bensbench.

## Out of scope

Browser->Mosquitto WS | unbounded live-hub DoS | BUILDING_50 package | zero-downtime promise | K8s without need | Python in product runtime
