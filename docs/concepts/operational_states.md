---
title: Operational states
parent: Concepts
nav_order: 3
---

# Operational states

Open-FDD operations should explicitly identify environment mode before asserting correctness.

## States

- `TEST_BENCH`: deterministic fake-device conditions or lab-only setup.
- `LIVE_HVAC`: production building telemetry and real-world operating behavior.

## Why this matters

The same observed value can be expected in bench mode and suspicious in live mode. Mode-aware interpretation avoids false positives and noisy operations.

