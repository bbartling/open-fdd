---
title: Context and recordkeeping
parent: Concepts
nav_order: 2
---

# Context and recordkeeping

Open-FDD context should be durable, visible, and reusable by both humans and agents.

## Rule

If context affects repeatable operations, store it in versioned docs instead of leaving it in chat-only memory.

## Good context to commit

- Verification strategy and sweep logic.
- BACnet/model assumptions that affect diagnostics.
- Operator playbook updates and recurring workflow improvements.
- Cross-check guidance for frontend/API parity and model-based telemetry.

## Context anti-patterns

- One-machine-only tribal notes with no repo trace.
- Secrets in markdown.
- Raw transcript dumps without distillation.

