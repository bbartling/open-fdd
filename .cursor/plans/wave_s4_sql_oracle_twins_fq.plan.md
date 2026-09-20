> **Wave U child detail** — product Soft-OPEN scheduled **after** the security spine. Do not treat as active master.

---
name: Wave S4 SQL twins FQ closeout
overview: "DataFusion M&V/analytics twin + Metering UI radio + model/ECM stress gate in FQ MEGA. Final Wave S OPS PINNED."
todos:
  - id: s4-sql-twin
    content: Thin SQL surface for oracle covered by S3
    status: pending
  - id: s4-ui-metering
    content: Metering section radio charts for M&V (SPA skill 7b)
    status: pending
  - id: s4-oracle-gate
    content: Stress compare PyPI oracle vs /api on same seed
    status: pending
  - id: s4-model-gate
    content: Include S5 model/ECM gate in FQ run
    status: pending
  - id: s4-mega-fq
    content: GHCR → re-pin → fieldbus → FQ MEGA EXECUTE=1
    status: pending
  - id: s4-closeout
    content: BUG_REPORT + agent_spec OPS pin + evidence matrix fill
    status: pending
isProject: false
---

# Wave S4 — SQL twins + UI + FQ MEGA

**Depends on:** S1 FQ, S2 ADR, S3 oracle ports, S5 model tip smoke (model gate wired).

## Stress

Full FQ MEGA with `OPENFDD_SECURITY_EXECUTE=1` **and** model/ECM qualification gate from S5. Cite this tip only.
