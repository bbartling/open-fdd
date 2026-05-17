---
title: Context and recordkeeping
parent: Concepts
nav_order: 2
---

# Context and recordkeeping

Open-FDD documentation should be durable, visible, and reusable across contributors.

## Rule

If context affects repeatable operations, store it in versioned docs instead of leaving it in chat-only memory.

## Good context to commit

- Verification strategy and sweep logic.
- BACnet or naming assumptions that affect **`column_map`** and diagnostics.
- Cookbook additions and regression examples for expression rules.

## Context anti-patterns

- One-machine-only tribal notes with no repo trace.
- Secrets in Markdown.
- Raw transcript dumps without distillation.
