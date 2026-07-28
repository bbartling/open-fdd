---
title: Milestone D gap register
parent: Migration
nav_order: 30
---

# Milestone D gap register

**Date:** 2026-07-28 · Branch `milestone-d/d1-historian-datafusion-runtime`

Tracks C→D gaps and status after D1–D5 work. Companion matrices:
[`vibe20_integration_matrix.md`](vibe20_integration_matrix.md),
[`MILESTONE_C_ANALYTICS_MATRIX.md`](MILESTONE_C_ANALYTICS_MATRIX.md).

| ID | Gap | Status | Notes |
|----|-----|--------|-------|
| D1 | Historian → DataFusion runtime analytics | **Improved** | Parquet bridge live for runtime; other families still minimal / MemTable residual |
| D1b | Silent pandas Overview fallback | **Improved** | Oracle flag required (`OPENFDD_ANALYTICS_ORACLE=1`) |
| D2 | SQL rule parity mutation CI | **Improved** | Path + keyword harness in CI; logical gate mutations residual |
| D2b | `PROVEN_MULTI_BUILDING` / BUILDING_100 | **Open** | BUILDING_100 = single-building evidence path; multi-building not claimed |
| D3 | Job-native WattLab SoT | **Improved** | Central handoff + UI helper; zip additive |
| D4 | Restricted E+ runner | **Improved (stub)** | Policy + QUEUED persist; no Docker socket / in-process E+ |
| D4b | External runner claim + artifact attach loop | **Open** | `attach_artifact_meta` types exist; worker not wired |
| D5 | Vite `:5173` production hints | **Improved** | Dev-stack hint → Streamlit `:8501`; archive/historical docs kept |
| C8 | Plant / chiller-boiler analytics | **Open** | Not started |
| C11 | Full pandas production retirement + `sha-*` | **Open** | Residual |
| A | `open_fdd.contracts` | **Deferred** | Milestone A residual |
