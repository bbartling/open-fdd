# Long-run lab pass (OpenClaw) — backed up with the skill

This file is **versioned in git** (`open-fdd/openclaw/references/` on GitHub). The Control UI chat is **not** durable; this runbook + **`issues_log.md`** are.

## Reality check

- OpenClaw is **not** a daemon that runs “hours with zero input.” Sessions end when the UI closes or limits hit.
- **Multi-hour work** works as **many sessions** (or one long session) where **each run** reads the repo trail first — **no** need for the human to paste the same context every time.
- If the **goal changes**, the human adds a line to **`openclaw/issues_log.md`** or sends a short new instruction.

## Paste-ready prompt (human → OpenClaw)

```text
Long-run lab pass (file-backed — do not ask me to repeat repo context).

Read first (in order):
- openclaw/HANDOFF_PROTOCOL.md
- openclaw/references/testing_layers.md
- openclaw/references/api_throttle.md
- openclaw/SKILL.md
- Latest sections of openclaw/issues_log.md

Source of truth: repo + issues_log + logs under openclaw/logs/. Do not rely on Control UI chat history.

Work queue — execute in order, one step at a time, append openclaw/issues_log.md after EACH step with: runner openclaw, branch, command, log path, result pass|fail|blocked, first_error_line, next for senior if needed.

**Logging (do not hand-roll `ts=` inside `nohup bash -lc '...'` — it often mangles).** From **open-fdd** repo root use either:
- `./openclaw/scripts/capture_bootstrap_log.sh --verify`  (or any other `./scripts/bootstrap.sh` args as trailing args), or
- `./openclaw/scripts/verify_with_log.sh`  (verify only).

Those scripts set `ts`, `tee`, and `.venv` activation internally. For background: `nohup ./openclaw/scripts/verify_with_log.sh >openclaw/logs/nohup-verify.out 2>&1 &` (log file path is still printed inside the script’s main log).

1) If stack is already up: **`./openclaw/scripts/verify_with_log.sh`** (or `capture_bootstrap_log.sh --verify`) — then append `issues_log`.
2) Mode slices (separate runs): **`./openclaw/scripts/capture_bootstrap_log.sh --mode collector`** then model, then engine — log each.
3) React smoke: confirm frontend URL from live bootstrap output; note main routes in issues_log (or run 1_e2e if headed/Selenium available — if not, blocked + what human runs).
4) MCP: curl http://localhost:8000/mcp/manifest with Bearer from stack/.env if auth on — log status + first line of body (no secrets in log).
5) Docs: spot-check published doc links from README; note 404s in issues_log.
6) Bench: openclaw/bench/e2e/README.md — at most ONE heavy script per stretch; throttle per api_throttle.md.

Rules:
- cd open-fdd for all ./scripts/*.
- Do not change product code (open_fdd/, packages/, frontend/src/) unless human explicitly allowed.
- Same command failed twice → stop; issues_log next for senior + log path.
- git commit/push ONLY if human asked in this message.
- API/token limits → issues_log blocked; stop.

Reply only with: step completed, latest log path, next queue item.
```

## Optional git line (add only if human wants logs in repo)

```text
git add openclaw/logs/bootstrap-test-<file>.txt when green; commit/push only if I said to push develop/v2.0.7.
```

## Where this lives in the bundle

| File | Role |
|------|------|
| `openclaw/SKILL.md` | Points here under “Long sessions.” |
| `openclaw/references/long_run_lab_pass.md` | **This** runbook + paste block. |
| `openclaw/issues_log.md` | Per-step results after each command. |
| `openclaw/HANDOFF_PROTOCOL.md` | Cursor ↔ OpenClaw file loop. |

Pull **`develop/v2.0.7`** (or your branch) on any clone to get updates.
