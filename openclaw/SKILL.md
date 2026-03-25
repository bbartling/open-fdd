---
name: open-fdd-lab
description: Expert-style regression testing for Open-FDD — bootstrap modes, React frontend smoke checks, HTTP MCP tool discovery, AI/data-modeling flows, docs link hygiene, and lab handoff via issues_log (Brick/HVAC context; future live-operator scope).
metadata: {"openclaw":{"homepage":"https://github.com/bbartling/open-fdd/tree/develop/openclaw"}}
user-invocable: true
---

# Open-FDD lab skill (OpenClaw)

You help validate **Open-FDD** on a dev host. Work from the **git repo root** (`open-fdd/`), not the parent OpenClaw workspace root, unless reading `AGENTS.md` / `SOUL.md` / `USER.md`.

## Always read first

1. `openclaw/HANDOFF_PROTOCOL.md` — file-based handoff with Cursor/human.
2. Latest dated section in `openclaw/issues_log.md` — **this is the durable trail when the Control UI chat closes** (plus git).
3. `openclaw/references/testing_layers.md` — **bootstrap vs bench vs pytest**; where to log failures vs product bugs.
4. `openclaw/references/bootstrap_mcp_frontend.md` — modes, MCP, UI checks.
5. `openclaw/references/api_throttle.md` — reduce Codex/model API burn.
6. **`openclaw/references/long_run_lab_pass.md`** — **multi-hour / multi-session queue**, paste-ready prompt, and explicit limits (not infinite autopilot). **Backed up on GitHub** with this repo.

## Long sessions (“hours” of work)

- You are **not** meant to run forever without **issues_log** + **repo** as the plan.
- For a **queued lab pass** (verify → mode slices → React → MCP → docs → bench, one step per `issues_log` entry), follow **`references/long_run_lab_pass.md`** — that file contains the **canonical paste block** for the human and stays in sync with git. Same file has **“After a background … job”** + **throttle/context** notes; pair with **`references/api_throttle.md`**.

## Bootstrap and modes (throttle-friendly)

- **Full stack** (default): `./scripts/bootstrap.sh` — confirm **React** at `http://localhost:5173` (or via Caddy `http://localhost` per bootstrap banner). Do not restart the full stack on every micro-step.
- **Sliced runs** (lighter): `./scripts/bootstrap.sh --mode collector` → `--mode model` → `--mode engine` when the human asks for mode coverage; **space runs** with verification (`./scripts/bootstrap.sh --verify`) between heavy operations.
- **CI matrix:** `./scripts/bootstrap.sh --test` after `.venv` + `pip install -e ".[dev]"` (see `openclaw/README.md`).
- **Logs:** `mkdir -p openclaw/logs` and capture to `openclaw/logs/bootstrap-test-<YYYY-MM-DD_HH-MM-SS>.txt`.

## MCP (HTTP tools)

After API is up: **`http://localhost:8000/mcp/manifest`** with **`Authorization: Bearer <OFDD_API_KEY>`** from `stack/.env` when auth is enabled. Optional RAG sidecar: **`http://localhost:8090/manifest`** if stack was started with `--with-mcp-rag`. Details: repo `docs/openclaw_integration.md`, root `README.md` (OpenClaw section).

## Frontend / “human in the browser”

Exercise the **React** app the way a human would: load main routes, data-model testing flows if present, plots/fault views as documented. Prefer **one focused session** per task to save tokens. If browser automation exists in-repo, see `openclaw/bench/e2e/README.md` and `references/frontend_testing.md`.

## Docs and links

- Crawl **published** docs (GitHub Pages / links in README) for **404s and obvious broken anchors**; record in `issues_log.md` (area: docs).
- Do not hammer external sites; batch link checks.

## Security testing

Follow `openclaw/references/security_testing_scope.md`. **No** destructive or unauthorized probing. Document findings for a **future hardening phase** in `issues_log.md` with suggested GitHub issues on **bbartling/open-fdd**.

## AI-assisted data modeling

With **model** or **full** stack: follow `docs/openclaw_integration.md`, SPARQL examples under `openclaw/bench/sparql/`, and operator config `config/ai/operator_framework.yaml`. Log ontology/import quirks in `issues_log.md` (area: model).

## GitHub and memory trail

- Canonical remote: **https://github.com/bbartling/open-fdd** — track regressions and doc defects; use **issues** for durable work, **`openclaw/issues_log.md`** for fast lab notes.
- **Commit/push** only when the human asked and tests passed (see `HANDOFF_PROTOCOL.md`). Never force-push.
- For long-term OpenClaw memory, the human may mirror summaries to workspace `memory/YYYY-MM-DD.md`.

## Future: clones on live HVAC sites

Brick graph + equipment type differ per building. Best practices for “clone and go” are **not** finalized — see `references/future_operator_clones.md`. Capture learnings in `issues_log.md` as you go.

## Supporting files

- `references/` — protocols, throttle, security scope, frontend notes, clone roadmap, **`long_run_lab_pass.md`** (multi-session queue).
- `scripts/` — small shell helpers (log capture, etc.).
- `assets/` — screenshots, fixtures (git only when small and non-secret).

## Installing this skill in OpenClaw

OpenClaw normally loads skills from `workspace/skills/<name>/SKILL.md`. Options:

1. **Symlink:** `ln -s /path/to/open-fdd/openclaw /path/to/workspace/skills/open-fdd-lab` (if your OpenClaw version follows symlinks), **or**
2. **Copy** `SKILL.md` (and `references/`) into `workspace/skills/open-fdd-lab/`, **or**
3. Set **`skills.load.extraDirs`** in `~/.openclaw/openclaw.json` to include the `openclaw` directory **if** your build discovers a top-level `SKILL.md` there (verify with `openclaw doctor` / docs for your version).

After install, run `openclaw doctor` and fix any skill path warnings.
