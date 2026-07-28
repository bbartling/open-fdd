---
title: Milestone D closeout
parent: Migration
nav_order: 33
---

# Milestone D closeout

**Date:** 2026-07-28 · Branch `milestone-d/d5-closeout`

| Pin | Value |
|-----|-------|
| open-fdd (pre-D5 tip) | `7da7c310` (D0–D2 merged; D3/D4 via #593) |
| playground | `d553e31` (`develop`) |
| PyPI | `open-fdd` ≥ 4.1.1 (oracle extras) |

## Executive summary

Milestone D closes **selected C residuals** and starts the EnergyPlus / WattLab
bridge without claiming full Phase 8 production readiness. D0–D5 land as focused
PRs. Full-stack `sha-*` soak, multi-building parity, and a live external E+
worker remain **residuals**.

## What is done

| Slice | Status |
|-------|--------|
| D0 — C→D gap register + cookbook fortress CI | **Done** (#590) |
| D1 — Historian DF + Streamlit central cutover | **Done** (#591) |
| D2 — `rule_parity_mutation_check.py` + multi-building inventory | **Done** (#592) |
| D3 — Job-native WattLab handoff UI + payload tests | **Done** (#593) |
| D3 — Zip remains additive; job-native documented as SoT | **Done** |
| D4 — `RunnerPolicy` validation + `POST .../eplus/runs` QUEUED stub | **Done** (#593) |
| D5 — Vite `:5173` production hint scrub (Streamlit `:8501`) | **Done** |
| D5 — Closeout / acceptance / gap register / BUILD_CHECKPOINTS | **Done** |

## Explicit residuals (not claimed)

- Live external EnergyPlus worker claiming QUEUED runs + full artifact attach UX
- Logical SQL gate mutation tests (fan-on / occupancy / ΔT) beyond path guards
- `PROVEN_MULTI_BUILDING` qualification
- Remaining analytics family DF MemTable + full Streamlit cutover (C3–C9, C8 plant)
- Production pandas path retirement and immutable `sha-*` full-stack acceptance
- Playground GHCR retirement / dead workflow purge beyond Vite hint scrub

## Engine / ownership honesty

- Central does **not** execute EnergyPlus or attach a Docker socket.
- Production UI is **Streamlit** (`services/ui`), not Vite/Caddy.
- Dual cookbooks remain protected; registry 63 vs public ~59 stays honest.

## Related

- [Gap register](MILESTONE_D_GAP_REGISTER.md)
- [Acceptance](MILESTONE_D_ACCEPTANCE.md)
- [Rule parity](MILESTONE_D_RULE_PARITY.md)
- [Job workspaces](../architecture/job-workspaces.md)
