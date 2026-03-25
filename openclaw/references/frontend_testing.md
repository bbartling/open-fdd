# Frontend (React) testing notes

## Human-like smoke

1. Open app root (see `bootstrap_mcp_frontend.md` for URLs).
2. Navigate to **primary** routes (dashboard, faults, plots, data-model / testing pages if present).
3. Note: blank screens, obvious API errors in UI, failed loads.

## Automation in this repo

- **Vitest** runs in CI / `./scripts/bootstrap.sh --test` (container or host npm).
- **Selenium / E2E:** `openclaw/bench/e2e/README.md`, `docs/operations/testing_plan.md`.

## Reporting

Record **route**, **expected vs actual**, and **browser console** one-liners in `issues_log.md`. Attach screenshots to `openclaw/assets/` only if small and non-sensitive.
