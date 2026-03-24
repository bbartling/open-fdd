---
title: Big picture gaps and product suggestions
parent: Concepts
nav_order: 4
---

# Big picture gaps and product suggestions

This is a running list of higher-level product, workflow, and documentation gaps discovered while operating Open-FDD and its automated testing stack.

The goal is to capture the things that matter beyond the immediate bug or test run.

## Current themes

### 1. AI-assisted data modeling needs a stronger review-before-import flow

The current workflow makes it easy to jump from discovered BACnet points to imported semantic changes.

Suggested improvement:

- stage proposed site/equipment/point modeling changes
- let the user review them clearly before import
- make the before/after delta obvious

### 2. Graph reset behavior is easy to misunderstand

`POST /data-model/reset` does **not** mean "wipe everything." It means:

- clear BACnet graph/orphans
- repopulate Brick from DB-only

Suggested improvement:

- clarify this distinction more aggressively in UI/docs
- keep repeating that full empty-state requires deleting all sites via CRUD first

### 3. Rule-aware minimal polling is a big value lever

The testing/modeling flow should emphasize that only points needed by active rules should be polled.

This reduces unnecessary BACnet traffic and makes Open-FDD deployments more realistic for live HVAC systems.

Suggested improvement:

- add rule-aware polling recommendations in product/docs
- highlight minimal polling sets for active rules

### 4. The gap between discovery and FDD-ready modeling is still wide

Discovery gets BACnet objects into the graph, but that is still far from:

- Brick semantics
- equipment relationships
- rule applicability
- optimization readiness

Suggested improvement:

- describe maturity stages more explicitly:
  - discovered
  - modeled
  - FDD-ready
  - operations-ready

### 5. Overnight testing still needs stronger generated evidence

The current overnight setup is much better than before, but it should mature into a real evidence pipeline:

- BACnet source evidence
- SPARQL/model evidence
- YAML rule evidence
- fault-result evidence
- docs/link review evidence
- container-log correlation

Suggested improvement:

- generate durable overnight reports by default (see `openclaw/reports/` templates in the repo)

### 6. Container log viewing should become part of the testing story

The container-log feature is not just an admin convenience. It should support:

- frontend/backend mismatch diagnosis
- scraper troubleshooting
- FDD loop troubleshooting
- overnight evidence correlation

Suggested improvement:

- make container-log review part of normal dev-testing and docs

### 7. Open-FDD needs a stronger live-HVAC operations mental model

The platform already contains pieces for:

- discovery
- modeling
- rules
- faults
- charts
- logs
- weather

But the product/docs should frame those around the real user contexts:

- controls engineer
- building operator / facilities manager
- AI agent assisting with diagnostics and optimization

## Security / hardening context to remember

Relevant existing issue on the main Open-FDD repo:

- **#73** — `Phase 2 – Stack Security Hardening (DB, Caddy, Secrets)` — <https://github.com/bbartling/open-fdd/issues/73>

This should remain in the background context for future deployment and production-readiness work.

Also relevant:

- **#44** — `Test Caddy. Integrate and Define Secure Coding Best Practices` — <https://github.com/bbartling/open-fdd/issues/44>

## Why this doc exists

A lot of the most important insight is not just "what failed," but "what is still missing from the big picture."

This file is meant to preserve those bigger observations so future clones, future agents, and future humans can build from them instead of rediscovering them from scratch.
