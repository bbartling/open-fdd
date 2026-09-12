---
name: Wave M durable results + residual mega
overview: "ACTIVE - Wave M post-Wave L. Durable persistence + auto-results UX + release orchestrator + enhanced stress (AFDD flood gate 12). Residuals #782/sql-anomaly/lab MT; Stage C late-gated. Ops multi_tenant=false until checklist."
todos:
  - id: m0-hygiene
    content: "M0 - Soft-OPEN scrub + Wave M ACTIVE + plan mirror"
    status: completed
  - id: d1-repro
    content: "D1 - Root-cause report (SHA vs digests; storage; UX leads)"
    status: pending
  - id: d2-durable-state
    content: "D2 - Authoritative persistent state + atomic results"
    status: pending
  - id: d3-compute-vs-read
    content: "D3 - Durable AFDD runs/checkpoints; no browser-driven full recompute"
    status: pending
  - id: d4-ux-session
    content: "D4 - Auto-load results; session-gen cache; 401 race fix"
    status: pending
  - id: d5-release-cmd
    content: "D5 - One release orchestrator + honest backup"
    status: pending
  - id: m1-782-sse
    content: "M1 - #782 Central JWT SSE"
    status: pending
  - id: m2-sql-anomaly
    content: "M2 - sql-anomaly screening (lab-safe)"
    status: pending
  - id: m3-lab-mt
    content: "M3 - Lab multi-tenant enable; prod stays OFF"
    status: pending
  - id: m4-stage-c
    content: "M4 - Stage C IdP/MFA (late gated)"
    status: pending
  - id: m5-enhanced-stress
    content: "M5 - ENHANCED stress gates 00-17 + 1-12; fully_qualified; PINNED"
    status: pending
isProject: false
---

# Wave M - Durable results + residual mega (post-Wave L)

**Cursor SoT:** [`wave_m_residual_mega_0c09093d.plan.md`](../../../../.cursor/plans/wave_m_residual_mega_0c09093d.plan.md)

## Where we are - **ACTIVE**

| Item | State |
|------|--------|
| **Program** | **ACTIVE** - Wave M durable results + residuals |
| **Prior** | Wave L **CLOSED / PINNED** 3.5.6 · ops `sha-e80237c` · stress `20260912T033836Z` |
| **Mode** | `multi_tenant=false` in prod until Stage C checklist |
| **Step** | Track D (D1->D5) then residuals M1-M4; **ONE** enhanced stress at M5 |

### Progress board

```text
[x] M0  Hygiene + Soft-OPEN scrub + plan mirror + Wave M ACTIVE
[ ] D1  Root-cause repro report
[ ] D2  Durable scoped state + atomic results
[ ] D3  Compute vs read (AFDD durable runs)
[ ] D4  UX / session lifecycle
[ ] D5  Release orchestrator + backup honesty
[ ] M1  #782 SSE
[ ] M2  sql-anomaly
[ ] M3  Lab MT enable (prod OFF)
[ ] M4  Stage C (late)
[ ] M5  ENHANCED stress + PIN (gates 1-12 incl. AFDD flood)
```

## Completion

Deploy a qualified update, reopen a job, see correct latest completed analytics/faults without manually rebuilding state in the UI.

## Out of scope

Browser->Mosquitto WS · unbounded live-hub DoS · BUILDING_50 package · zero-downtime promise · K8s without need · Python in product runtime
