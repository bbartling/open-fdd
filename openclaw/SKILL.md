---
name: open-fdd-lab
description: Expert-style regression testing for Open-FDD — bootstrap modes, React frontend smoke checks, HTTP MCP tool discovery, AI/data-modeling flows, docs link hygiene, and lab handoff via issues_log (Brick/HVAC context; future live-operator scope).
metadata: {"openclaw":{"homepage":"https://github.com/bbartling/open-fdd/tree/develop/openclaw"}}
user-invocable: true
---

# Open-FDD lab skill (OpenClaw)

You help validate **Open-FDD** on a dev host. Work from the **git repo root** (`open-fdd/`), not the parent OpenClaw workspace root, unless reading `AGENTS.md` / `SOUL.md` / `USER.md`.
Do **not** clone/orchestrate a second Open-FDD stack from this skill; target the existing deployment and use OpenClaw primarily for web app/testing unless the human explicitly asks for AI modeling or virtual-operator workflows.

## What “skill” means in OpenClaw

OpenClaw loads **[AgentSkills](https://agentskills.io)-compatible** folders: each skill is a **directory** whose entry is **`SKILL.md`** (YAML frontmatter + body). Extra material lives beside it (e.g. `references/`, `scripts/`). **Predefined skills** ship **inside the OpenClaw install** (npm bundle or app). **This** skill is **repo-local** under `open-fdd/openclaw/`; wire it into OpenClaw via `workspace/skills/…`, `~/.openclaw/skills`, or `skills.load.extraDirs` (see install section below and OpenClaw’s skills docs). Same shape as Cursor’s create-skill flow—only the **load path** differs.

## Always read first

1. `openclaw/HANDOFF_PROTOCOL.md` — file-based handoff with Cursor/human.
2. `openclaw/references/legacy_automated_testing.md` — **if the task or links mention `open-fdd-automated-testing`**, use this map; canonical lab is **this** repo only.
3. Latest dated section in `openclaw/issues_log.md` — **this is the durable trail when the Control UI chat closes** (plus git).
4. `openclaw/references/testing_layers.md` — **bootstrap vs bench vs pytest**; where to log failures vs product bugs.
5. `openclaw/references/bootstrap_mcp_frontend.md` — modes, MCP, UI checks.
6. `openclaw/references/api_throttle.md` — reduce Codex/model API burn.
7. **`openclaw/references/long_run_lab_pass.md`** — **multi-hour / multi-session queue**, paste-ready prompt, and explicit limits (not infinite autopilot). **Backed up on GitHub** with this repo.
8. **`openclaw/references/session_status_summary.md`** — when the human asks for a **read-only lab snapshot**, follow the **5-bullet** contract (**no log bodies**).

## Session status (5 bullets — required shape)

If the human says to read **`issues_log`**, **`long_run_lab_pass`**, and **`api_throttle`** (or any paraphrase: “where are we?”, “summarize the lab”), you **must**:

1. Read **`openclaw/issues_log.md`** starting at the **newest `##` section** (work backward as needed).
2. Re-skim **`openclaw/references/long_run_lab_pass.md`** and **`openclaw/references/api_throttle.md`** for queue + throttle rules.
3. Reply with **exactly five bullets**, titled: **What finished** · **What’s running** · **Latest log paths** · **Pass / fail / blocked** · **What’s next**.
4. **Never** paste **contents** of log files or long command output — only **paths**, **PIDs** (if stated in `issues_log`), and **one-line** outcomes.

Full checklists and a **copy-paste human prompt** live in **`references/session_status_summary.md`**.

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

With **model** or **full** stack: follow `docs/openclaw_integration.md` (export → LLM → import loop), `docs/modeling/llm_workflow.md`, `docs/modeling/ai_assisted_tagging.md`, SPARQL examples under `openclaw/bench/sparql/`, and operator framing in `config/ai/operator_framework.yaml`. Log ontology/import quirks in `issues_log.md` (area: model).

## Toward live HVAC / building operator

When work shifts from **bench** to **real equipment**, keep using the same file-backed loop (`HANDOFF_PROTOCOL`, `issues_log`, integrity sweep). Add: `docs/operations/openfdd_integrity_sweep.md`, `docs/operations/overnight_review.md`, `docs/howto/cloning_and_porting.md`, and `references/future_operator_clones.md`. **Site-specific truth** lives in the **live knowledge graph**, not in a separate “automated testing” repo.

## GitHub and memory trail

- Canonical remote: **https://github.com/bbartling/open-fdd** — track regressions and doc defects; use **issues** for durable work, **`openclaw/issues_log.md`** for fast lab notes.
- **Commit/push** only when the human asked and tests passed (see `HANDOFF_PROTOCOL.md`). Never force-push.
- For long-term OpenClaw memory, the human may mirror summaries to workspace `memory/YYYY-MM-DD.md`.

## Future: clones on live HVAC sites

Brick graph + equipment type differ per building. Best practices for “clone and go” are **not** finalized — see `references/future_operator_clones.md`. Capture learnings in `issues_log.md` as you go.

## Supporting files

- `references/` — protocols, throttle, security scope, frontend notes, clone roadmap, **`long_run_lab_pass.md`** (multi-session queue), **`session_status_summary.md`** (5-bullet status, no log dumps).
- `scripts/` — small shell helpers (log capture, etc.).
- `assets/` — screenshots, fixtures (git only when small and non-secret).

## Installing this skill in OpenClaw

OpenClaw normally loads skills from `workspace/skills/<name>/SKILL.md`. Options:

1. **Symlink:** `ln -s /path/to/open-fdd/openclaw /path/to/workspace/skills/open-fdd-lab` (if your OpenClaw version follows symlinks), **or**
2. **Copy** `SKILL.md` (and `references/`) into `workspace/skills/open-fdd-lab/`, **or**
3. Set **`skills.load.extraDirs`** in `~/.openclaw/openclaw.json` to include the `openclaw` directory **if** your build discovers a top-level `SKILL.md` there (verify with `openclaw doctor` / docs for your version).

After install, run `openclaw doctor` and fix any skill path warnings.
