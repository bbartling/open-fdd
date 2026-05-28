---
name: react-operator-dashboard
description: "Scaffolds a Vite/React operator dashboard that calls the FastAPI bridge. Use when the manifest targets dashboard or when building site management, plots, rules, or agent chat pages."
---

# React operator dashboard

## When to use / When not to use

Use for browser-based operators (site list, CSV import, plots, rule setup, AI agent tab).

Skip when CLI/notebook-only workflows suffice.

## Prerequisites

- Node 20+, Vite, React 19 (or match operator toolchain).
- Running bridge at `http://127.0.0.1:8765` unless overridden.
- Generate UI under `workspace/dashboard/`.

## Quick start

```bash
cd workspace/dashboard
npm create vite@latest . -- --template react-ts
npm install react-router-dom @tanstack/react-query
```

1. Add `src/lib/api.ts` with `getBridgeBase()` (localStorage override → `VITE_DESKTOP_BRIDGE_BASE` → `http://127.0.0.1:8765`).
2. Add routes from the legacy page map (subset per manifest).
3. `npm run dev` on port 5173; bind `0.0.0.0` only for LAN with operator consent.

## Core concepts

- **Bridge base** is the only backend origin in the browser.
- **Site context** loads `GET /sites` once and shares site id across pages.
- **AI agent** page talks to bridge `/openfdd-agent/*` or `/local-codex/*`, not directly to Codex.

## Common patterns

- CRUD helpers for rules: mirror `crud-api.ts` patterns (list, get, put, delete YAML).
- Plots: fetch frame JSON from bridge plot endpoints; render with Plotly or similar.
- Redirect legacy paths `/openfdd-claw-chat` → `/ai-agent`.

## Compose with other skills

- [fastapi-bridge-api](../fastapi-bridge-api/SKILL.md), [local-dev-orchestration](../local-dev-orchestration/SKILL.md), [codex-agent-on-bridge](../codex-agent-on-bridge/SKILL.md)

## Verification

```bash
npm run build
curl -s http://127.0.0.1:5173/
```

## Gotchas

- CORS errors usually mean bridge offline or wrong bridge base URL.
- Do not embed Codex credentials in the browser.

See [references/REFERENCE.md](references/REFERENCE.md).
