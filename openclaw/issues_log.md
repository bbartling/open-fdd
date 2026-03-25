# Automated Testing Issues Log

Use this file to record **diagnostic findings only** while testing Open-FDD.

Rules:
- Do not fix product code here unless explicitly requested.
- Capture reproduction steps, mode used, evidence, and likely impact.
- Keep notes concise enough for another agent to pick up fast.
- Prefer one bullet per issue.
- Mention whether it is already tracked in GitHub Issues if known.

Suggested fields for each entry:
- date
- mode tested
- area (bootstrap, BACnet, model, engine, frontend, docs, etc.)
- symptom
- reproduction
- logs/evidence
- suspected cause
- GitHub issue link / follow-up

## 2026-03-21

- **2_sparql_crud_and_frontend_test.py**: Fixed the `UnboundLocalError` raised when `--save-report` was used without `--generate-expected`; the function-level `import json` statements shadowed the module import, so JSON report writes failed. Removed the redundant local imports so the global module binding is used everywhere.
- **3_long_term_bacnet_scrape_test.py**: Added automatic site resolution (falls back to the first site on the API when `OFDD_BACNET_SITE_ID`/`--site` is not provided) so downloads/fault checks target `TestBenchSite` instead of the literal string `default`. Wired the fake fault schedule into both the CSV/fault verification and a new `/faults/active` snapshot check so the script now validates that the BACnet fault schedule actually surfaces through the API in real time.
- **4_hot_reload_test.py**: Extended the rules hot-reload test to (optionally) trigger an FDD job per uploaded rule and wait for the generated fault_id to appear in `/faults/state`. Added site auto-detection, a reusable delete helper so test rules are cleaned up even on failure, and a `--skip-fault-verification` escape hatch.
- **Frontend PlotsPage review**: Verified that the current `frontend/src/components/pages/PlotsPage.tsx` no longer contains `selectedDeviceId`, `deviceOptions`, or equipment-scoped fault overlays referenced in CodeRabbit’s nitpicks. No action taken—the hook currently scopes by site (device filtering was removed in this branch).

## 2026-03-25

- Testing handoff context reconstructed from repo docs because workspace memory files were missing.
- Repo is cloned at `open-fdd`; branch currently `develop/v2.0.7`.
- `openclaw/README.md` says to use `./scripts/bootstrap.sh`, `./scripts/bootstrap.sh --test`, and the bench under `openclaw/bench/`.
- Started `./scripts/bootstrap.sh --test` from repo root after switching to `develop/v2.0.7`.
- Initial test matrix findings:
  - collector: backend pytest missing (`/usr/bin/python3: No module named pytest`)
  - model: frontend lint failed; backend pytest missing; Caddy image unavailable during validate
- Started `./scripts/bootstrap.sh && ./scripts/bootstrap.sh --test` in the repo root; this cloned `diy-bacnet-server` as part of bootstrap before the process was interrupted.
- Need to continue the bootstrap/test loop, gather logs, and capture concrete failures without fixing product code.
- User explicitly wants continuous documentation of bugs and broken behavior in this file.
- Docker inspection is currently blocked from this session by elevated-permission gates, so container/log visibility must be restored via allowed host permissions or a non-elevated path before I can inspect `docker ps` or `docker logs`.
- Installed host Python deps context: `pyproject.toml` already includes `pytest` under `[project.optional-dependencies].dev`, so the right remediation path for host backend test failures is `pip install -e ".[dev]"` from repo root rather than adding code changes.
- Re-ran dependency bootstrap in a venv and started a fresh combined job with captured output at `openclaw/logs/bootstrap-test-2026-03-25_11-12-*.txt` (PID `3364054`), to verify whether missing host pytest was the only blocker before touching application code.
- Latest deep-dive on `openclaw/logs/bootstrap-test-2026-03-25_09-00-30.txt`: the log still spends most of its first ~120 lines on Docker image pulls (`timescale/timescaledb:latest-pg16`, `caddy:2`, `node:22-alpine`), so bootstrap had not failed in the excerpted section; documentation was insufficient only in the sense that the file name/log path was not obvious until we added it here.
- New diagnostic split: frontend/caddy paths are healthy in the containerized matrix, but host backend tests still fail early on missing `pytest` when run directly via `/usr/bin/python3`; the repo docs point to `pip install -e ".[dev]"`, so the next blocker to verify is the host venv environment rather than app code.
- **2026-03-26 correction:** `openclaw/logs/bootstrap-test-2026-03-25_09-00-30.txt` actually shows the full-stack bootstrap completing and frontend/Caddy checks passing; the only confirmed failure in that run is host backend `/usr/bin/python3: No module named pytest`. Earlier notes claiming frontend lint/Caddy issues in that log were incorrect and should be ignored.
- **2026-03-26 rerun status:** host venv now exists and `openclaw` logs are ready; started a fresh `./scripts/bootstrap.sh --test` under `.venv` with log `openclaw/logs/bootstrap-test-2026-03-26_12-18-*.txt` (PID `3396161`) to verify whether backend pytest failure clears before any app-code changes.
