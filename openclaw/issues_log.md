# Automated Testing Issues Log

Use this file to record **diagnostic findings only** while testing Open-FDD.

Rules:
- Do not fix product code here unless explicitly requested.
- Capture reproduction steps, mode used, evidence, and likely impact.
- Keep notes concise enough for another agent to pick up fast.
- Prefer one bullet per issue.
- Mention whether it is already tracked in GitHub Issues if known.
- When a human asks OpenClaw for a **session status** read (`issues_log` + `long_run_lab_pass` + `api_throttle`), agents summarize in **5 bullets** per **`openclaw/references/session_status_summary.md`** — **log paths only**, not log bodies in chat.

Suggested fields for each entry:
- date
- mode tested
- area (bootstrap, BACnet, model, engine, frontend, docs, etc.)
- symptom
- reproduction
- logs/evidence
- suspected cause
- GitHub issue link / follow-up
- classification (auth/runtime drift, bench limitation, parity bug, graph/model drift, BACnet bug, product defect)
- auth preflight state (healthy vs drift) when API/model testing is involved

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
- **2026-03-26 execution started:** ran `cd /home/ben/.openclaw/workspace/open-fdd && mkdir -p openclaw/logs && ts=$(date +%F_%H-%M-%S) && . .venv/bin/activate && nohup bash -lc './scripts/bootstrap.sh && ./scripts/bootstrap.sh --test' > "openclaw/logs/bootstrap-test-$ts.txt" 2>&1 & ...` with PID `3399063`; awaiting the resulting `openclaw/logs/bootstrap-test-2026-03-26_12-22-*.txt` transcript before making any code changes.
- **2026-03-26 OpenClaw skill bundle (human + Cursor):** Added `openclaw/SKILL.md` (name `open-fdd-lab`) and `openclaw/references/` (`bootstrap_mcp_frontend.md`, `api_throttle.md`, `security_testing_scope.md`, `frontend_testing.md`, `future_operator_clones.md`, `skill_installation.md`), `openclaw/scripts/` (`capture_bootstrap_log.sh`, README), `openclaw/assets/README.md`. Intent: expert-style lab workflow — full stack + React smoke + MCP manifest checks, throttled Codex usage, mode runs (`collector`/`model`/`engine`), docs link checks, AI data-modeling smoke, security findings filed responsibly to GitHub issues + `issues_log.md`, future HVAC operator clone notes. **Install:** symlink `openclaw` → `~/.openclaw/workspace/skills/open-fdd-lab` or follow `references/skill_installation.md`; run `openclaw doctor` after. **Conversation trail:** this bullet + workspace `memory/` if the human mirrors there.
- **2026-03-26 green run (OpenClaw):** Reported `openclaw/logs/bootstrap-test-2026-03-25_12-22-14.txt` — all checks passed, backend pytest 205 passed, Caddy OK; senior not required for that run.
- **2026-03-26 verify run:** `./openclaw/scripts/verify_with_log.sh` completed successfully; log `openclaw/logs/bootstrap-test-2026-03-25_12-48-55.txt` recorded live services (`openfdd_api`, `openfdd_frontend`, `openfdd_timescale`, etc.), DB OK, BACnet OK, API OK, and weather skipped because `scripts/curl_weather_data.sh` is not executable.
- **2026-03-26 next queued run:** attempted `git pull --ff-only origin develop/v2.0.7 && ./openclaw/scripts/capture_bootstrap_log.sh --mode collector`; background session PID `3416557` is running and should produce a mode-specific log under `openclaw/logs/` for collector coverage.

## 2026-03-27 — CodeRabbit-style PR nits (Cursor verified / applied or skipped)

- **Applied (worth it):** `docs/howto/cloning_and_porting.md` — link `openclaw/README.md` to explicit `../../openclaw/README.md`; varied first checklist bullets. `open_fdd/platform/mcp_rag/app.py` — whitespace-safe empty body for `import_data_model` / `rules_sync_definitions`; Bearer token via single `partition`. `fault_schedule.py` — normalize aware datetimes to UTC. `2_sparql_crud_and_frontend_test.py` — remove useless `f` prefix on static print branch. `fix_dpkg.yml` — fail play when dpkg/apt repair rc ≠ 0. `monitor_fake_fault_schedule.py` — flatline: one sleep between full first-pass and second-pass RPC reads (minute-boundary safe). `1_e2e_frontend_selenium.py` — `_load_stack_env()` only from `main()`; refresh `API_KEY` + frontend default after load; `urlparse` scheme guard in `_api_request`; exception chaining in weather check; `_` for unused `/config` body.
- **Skipped (optional / high risk):** `3_long_term_bacnet_scrape_test.py` — stricter exit codes and phase-window fault matching (behavior change; needs dedicated review). `2_sparql` / `4_hot_reload` massive argparse + `main()` refactors. `test_bench_rule_catalog.md` link-text table churn. `ahu_fc15.yaml` expression formatting only. `_load_expected_json` redundant import (tiny; can do later).

## 2026-03-27 — Session continuity (browser / Control UI)

- **Durable history:** OpenClaw **Control UI chat is not** the long-term record. After closing the browser, rely on **`openclaw/issues_log.md`**, **`openclaw/HANDOFF_PROTOCOL.md`**, **`openclaw/SKILL.md`**, **`openclaw/references/testing_layers.md`**, git history, and workspace **`memory/YYYY-MM-DD.md`** (optional).
- **Git:** OpenClaw had started add/commit/push; repo was **ahead of `origin`** until Cursor pushed **`develop/v2.0.7`** (`b4fc266` feat openclaw lab bundle, then `963e31c` CodeRabbit fixes + `testing_layers.md` + issues_log session notes). Re-pull on other clones if needed.
- **Testing map for humans:** `openclaw/references/testing_layers.md` — documents `scripts/bootstrap.sh` vs `openclaw/bench/*` vs `open_fdd/tests/` and how to classify failures in `issues_log.md` vs GitHub Issues.
- **Long-run OpenClaw prompt (in repo):** `openclaw/references/long_run_lab_pass.md` — canonical multi-session lab queue + paste-ready Control UI prompt; linked from `SKILL.md` and `README.md`. Pull your working branch to sync; not stored only in chat.
- **2026-03-27 verify + logging fix (Cursor):** OpenClaw `--verify` failed when `ts=$(date …)` was embedded in `nohup bash -lc '…'` (mangled path). **Use from `open-fdd` root:** `./openclaw/scripts/verify_with_log.sh` or `./openclaw/scripts/capture_bootstrap_log.sh --verify` — scripts own timestamp + tee + optional `.venv`. Updated `references/long_run_lab_pass.md` + `openclaw/scripts/README.md`; added `verify_with_log.sh`.
- **Legacy automated-testing repo:** canonical lab + path map lives in **`openclaw/references/legacy_automated_testing.md`** (supersedes **bbartling/open-fdd-automated-testing**); add deprecation banner to old README when maintaining that remote.
- **2026-03-27 release 2.0.8 (Cursor):** Bumped **`open-fdd`** to **2.0.8** in root **`pyproject.toml`**, **`frontend/package.json`**, and **`frontend/package-lock.json`**. Bumped **`openfdd-engine`** to **0.1.1** with dependency **`open-fdd>=2.0.8`** in **`packages/openfdd-engine/pyproject.toml`**. PyPI tags when ready: **`open-fdd-v2.0.8`**, **`openfdd-engine-v0.1.1`**.
- **2026-03-27 session status contract (Cursor):** Added **`openclaw/references/session_status_summary.md`** — mandatory **5-bullet** reply (finished / running / log paths / pass-fail / next) when human asks to read `issues_log` + `long_run_lab_pass` + `api_throttle`; **no log bodies** in chat. Wired into **`SKILL.md`**, **`HANDOFF_PROTOCOL.md`**, **`long_run_lab_pass.md`**, **`api_throttle.md`**, and this file’s rules header.

## 2026-03-28 — develop/v2.0.8 branch + version pins

- **Git:** After **`develop/v2.0.7`** merged to **`master`** and the old branch was deleted on GitHub, day-to-day work continues on **`develop/v2.0.8`** (create from updated **`master`**, then push `-u origin`).
- **Version matrix (2.0.8 line):** **`pyproject.toml`** → `open-fdd` **2.0.8**; **`frontend/package.json`** + **`frontend/package-lock.json`** (root package) → **2.0.8**; **`packages/openfdd-engine/pyproject.toml`** → **0.1.1** with **`open-fdd>=2.0.8`**. No extra hardcoded UI version — React reads API **`capabilities.version`**.

## 2026-03-27 - LAN bench auth recovery + issue filing (v2.0.10 scout)

- Found active bench auth file at `C:\Users\ben\Downloads\.env`; `OFDD_API_KEY` present there and usable for direct backend checks.
- Confirmed authenticated SPARQL works on the LAN bench again (`POST /data-model/sparql` returned bindings instead of 401 once the downloaded `.env` was loaded into process env).
- Reverted local product-code wording edits on branch `chore/pr2-wording-parity`; current instruction from Ben is **issue bugs, do not locally fix app code**.
- Filed **GitHub issue #95**: stale Data Model / Data Model Engineering user-facing guidance and ambiguous `223P` vs `s223` wording are still live on the running bench.
- Filed **GitHub issue #96**: OpenClaw bench auth-sensitive scripts should fail fast on missing `OFDD_API_KEY` instead of producing noisy downstream 401/parity cascades.
- Updated OpenClaw tooling/docs (repo-local `openclaw/` only):
  - `bench/e2e/2_sparql_crud_and_frontend_test.py` now runs an auth preflight against `/sites` and exits early with explicit runtime/auth-context messaging.
  - `bench/e2e/4_hot_reload_test.py` now does the same auth preflight before rule/hot-reload work.
  - `openclaw/README.md` and `openclaw/bench/e2e/README.md` now document `OPENCLAW_STACK_ENV` / `OFDD_API_KEY` loading expectations for split setups.
- Morning evidence split remains: stale wording/guidance = real product issue; missing auth in the harness = runtime/tooling drift unless repro persists under a known-good key.

## 2026-03-27 - GitHub contract + issue-state durability update

- Operating contract locked in:
  - **Cursor agents = expert software engineer / product fixer**
  - **OpenClaw = expert tester / live bench validator**
  - GitHub issues + PRs + commit SHAs are the handoff surface.
- OpenClaw tester-only evidence loop for commit **`cf343ca`** completed:
  - **#95** retest passed on live bench; close recommended.
  - **#93** retest passed for the original symptom; close recommended.
  - **#92** tighter retest showed `07_count_triples.sparql` is currently dominated by **graph/runtime churn**, not a stable frontend-only parity defect on the live bench.
- GitHub evidence comments posted:
  - `#95` comment: `https://github.com/bbartling/open-fdd/issues/95#issuecomment-4143074983`
  - `#93` comment: `https://github.com/bbartling/open-fdd/issues/93#issuecomment-4143078830`
  - `#92` initial comment: `https://github.com/bbartling/open-fdd/issues/92#issuecomment-4143074989`
  - `#92` tighter repro follow-up: `https://github.com/bbartling/open-fdd/issues/92#issuecomment-4143131321`
- Bench integrity drift remains an active follow-up topic outside #95/#93/#92:
  - auth healthy from `C:\Users\ben\Downloads\.env`
  - raw BACnet reads healthy
  - graph state has swung between severe churn and partially recovered states
  - recurring symptoms: orphan blank nodes, fluctuating `triple_count`, duplicate partial BACnet refs, and temporarily inconsistent `bacnet_devices` materialization.
- Durable instruction for next session: before opening new product bugs from parity failures, require healthy auth preflight and check whether the graph is currently moving too fast for the query to be a stable parity oracle.
