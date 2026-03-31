---
title: Overnight review
parent: Operations
nav_order: 2
---

# Overnight review

Overnight review is the deeper process window for quality and drift detection. It complements daytime integrity sweeps.

## Window

- Recommended local window: `18:00-06:00`.

## Goals

- Catch regressions that only appear over longer runtime windows.
- Distinguish product defects from auth/env/testbench drift.
- Create durable context updates for future OpenClaw clones.

## Expected outputs

- Environment mode and mode basis.
- High-signal changes in BACnet behavior, graph behavior, and fault outputs.
- Candidate docs/playbook updates when operating process improves.
- If durable bench/operator lessons emerge, capture them in versioned notes under `openclaw/references/` so they can later be curated into broader docs.

## Alerting discipline

- Suppress repeated low-signal notices.
- Escalate only meaningful drift or new high-impact findings.
- Convert durable lessons into versioned docs, not chat-only memory.

