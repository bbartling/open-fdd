---
title: Dashboard overview
parent: Operator Bridge
nav_order: 1
---

# Dashboard overview

## Primary areas

| Area | Purpose |
|------|---------|
| **Home / Building insight** | Check-engine status (green/yellow/red), active fault summary |
| **Trends** | Point history from feather store |
| **Faults** | Rule hits grouped by equipment family |
| **Rule Lab** | Edit, lint, and test Python FDD rules (PyArrow kit zip) |
| **Algorithms** | Supervisory GL36 trim & respond (coming soon) |
| **Model & assignments** | Equipment tree, FDD rule pins, commissioning JSON |
| **BACnet** | Discovery, reads, commission workflows |
| **Settings / health** | Stack status, auth mode |

## Live updates

Dashboard tiles use REST polling and `WS /ws/dashboard` for selected live views (ticket auth via `POST /api/auth/ws-ticket`).

## Roles

Read-only operators see trends and faults; integrators access Rule Lab and model import. See [Auth and roles]({% link operator-bridge/auth-roles.md %}).
