---
name: react-operator-dashboard
description: "Scaffolds a Vite/React operator dashboard that calls the FastAPI bridge. Use when the manifest targets dashboard or when building site management, plots, rules, or agent chat pages."
---

# React operator dashboard

## Starter codebase (maintain here)

Working UI: **`workspace/dashboard/`** (React 19 + Vite 6 + CodeMirror 6).

| Route | Page | Bridge calls |
|-------|------|----------------|
| `/` | Overview | `GET /health` |
| `/rule-lab` | Bake-a-Py editor | `POST /api/playground/lint`, `test-rule`, `run-script` |
| `/fdd` | YAML RuleRunner | `POST /api/rules/run` |
| `/bacnet` | BACnet status / ingest | `GET /config/bacnet`, `POST /ingest/bacnet` |
| `/agent` | AI chat | `GET /openfdd-agent/context`, `POST /openfdd-agent/chat` |
| `/login` | Operator login | `POST /api/auth/login` |

Key files:

- `src/lib/api.ts` — `getBridgeBase()`, Bearer token in `sessionStorage`
- `src/components/PythonCodeEditor.tsx` — CodeMirror Python
- `src/pages/RuleLabPage.tsx` — per-row vs DataFrame script modes

## When to use / When not to use

Use for browser-based operators (Rule Lab, FDD, BACnet, agent tab).

Skip when CLI/notebook-only workflows suffice.

## Prerequisites

- Node 20+, bridge at `http://127.0.0.1:8765`.
- Dev: `cd workspace/dashboard && npm ci && npm run dev` (port 5173, Vite proxy).
- Prod: `scripts/build_operator_dashboard.sh` → static files in `workspace/api/static/app`.

## Core concepts

- **Bridge base** is the only backend origin in the browser (`src/lib/api.ts`).
- **Python execution** is always server-side; buttons call `/api/playground/*`.
- **AI agent** page uses `/openfdd-agent/chat` when Codex is on PATH; otherwise operators use `openfdd-agent-shell` from Cursor/Codex/Claude/OpenClaw.

## Agent maintenance

When adding features:

1. Add route in `src/App.tsx` + page under `src/pages/`.
2. Add bridge endpoint in `workspace/api/openfdd_bridge/routes/`.
3. Document in `docs/howto/operator_dashboard.md`.
4. Run `npm run build` and `pytest tests/workspace_bridge`.

## Verification

```bash
npm run dev
curl -sf http://127.0.0.1:5173/
# After build:
curl -sf http://127.0.0.1:8765/
```

## Gotchas

- CORS / 401 → check bridge running and auth token after login.
- Do not embed Codex credentials in the browser.
- `VITE_DESKTOP_BRIDGE_BASE` or localStorage `ofdd-bridge-base-override` for non-default bridge URL.

See [references/REFERENCE.md](references/REFERENCE.md).
