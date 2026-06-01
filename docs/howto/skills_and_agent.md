---
title: Skills and agent shell
parent: How-to guides
nav_order: 5
---

# Skills and agent shell

The repository ships the **pandas rules engine** on PyPI. Dashboards, HTTP bridges, ingest drivers, MCP retrieval, and deployment recipes live under **`skills/`** and are built on demand with **`openfdd.toml`** plus the local **agent shell**.

## Install paths

| Goal | Command |
|------|---------|
| Bare import / DataFrame work | `pip install open-fdd` |
| YAML rules + `RuleRunner` | `pip install "open-fdd[engine]"` |
| Maintainer checkout | `pip install -e ".[dev]"` |
| Agent shell (not on PyPI) | `pip install -e packages/openfdd-agent-shell` |

The **`[engine]`** extra adds **PyYAML** and **pydantic** for rule loading and validation. NumPy arrives transitively through **pandas**.

## Manifest

Copy **`openfdd.toml.example`** to **`openfdd.toml`** and set:

- **`[build].targets`** — `api`, `dashboard`, `feather_storage`, …
- **`[build].drivers`** — `csv`, `openmeteo`, `bacnet`, …
- **`[build].auth`** / **`[build].deploy`** — local, Caddy, systemd, Ansible bench
- **`[agent].skills`** — skill folder names under **`skills/`**
- **`[memory]`** — `MEMORY.md` bootstrap path, daily note lookback, truncation budget, and `working-divergence.md` tail for skill/spec drift
- **`[cron]`** — `jobs.json`, runtime state, and run log directories

Generated application code belongs in **`workspace/`** (see **`AGENTS.md`**). Portfolio memory and schedules live beside generated services under the same workspace tree.

**Path safety:** at load time, `Manifest.load` resolves `agent.scratch_dir`, all `[memory]` paths, `[cron]` job/state/run paths, and `[wake]` lock/debounce/wake-log paths to absolute paths and **rejects** any entry that would resolve **outside** `workspace_dir`. Keep custom paths under `workspace/` (for example `workspace/scratch/`, `workspace/cron/`, `workspace/memory/`).

## Agent shell

```bash
openfdd-agent-shell --repo-root .
```

The shell loads **`AGENTS.md`**, workspace **`MEMORY.md`** (plus recent daily notes and the architecture divergence log), selected **`skills/*/SKILL.md`** files, and launches **Codex CLI** with a composed system prompt. Slash commands include **`/skills`**, **`/plan`**, **`/verify`**, **`/engine-check`**, **`/open-workspace`**, **`/memory`**, and **`/cron`**.

When working code under **`workspace/`** diverges from skills because the documented path failed, append to **`workspace/memory/architecture/working-divergence.md`**. Scheduled **`codex_turn`** jobs can set **`payload.wake_mode`** to **`mini`** or **`critique`** to repeat the BAS-style append/triage loop.

Workspace cron CLI:

```bash
openfdd-workspace-cron --repo-root . list
openfdd-workspace-cron --repo-root . tick
```

Scheduled wake (mini + critique, transcript under `workspace/cron/wakes/`):

```bash
openfdd-wake --repo-root . --dry-run
openfdd-agent-shell wake --repo-root . --dry-run
```

Dry-run a single turn:

```bash
openfdd-agent-shell --repo-root . --dry-run --message "scaffold csv ingest only"
```

The interactive REPL stays open after a Codex turn (a successful `run_invocation` does not exit the shell).

### Workspace cron

`openfdd-workspace-cron add` requires **exactly one** schedule flag: `--every-seconds`, `--at` (ISO timestamp), or `--cron` (expression). `--payload-json` must be valid JSON (invalid JSON exits with a clear message, not a traceback).

`Schedule` objects loaded from `jobs.json` are validated: `every` needs `every_seconds > 0`; `cron` needs a non-empty `cron_expr`; `at` needs `at_iso`.

`tick` and `run --dry-run` advance job state like real runs. A **dry-run** execution clears the `running` flag, updates `next_run_at`, and writes a run record so jobs are not stuck re-queued.

Shell commands in cron job payloads are tokenized with `shlex.split` before `subprocess.run` (`shell=False`).

Example `codex_turn` job payload for wake-style turns:

```json
{
  "wake_mode": "mini",
  "invocation": 1,
  "total": 2
}
```

Use `"wake_mode": "critique"` for the critique-only message. Non-numeric `invocation` / `total` values fall back to manifest defaults instead of raising.

### Scheduled wake (mini + critique)

`openfdd-wake` (alias `openfdd-agent-shell wake`) runs up to `wake.mini_invocations` mini Codex turns, then one critique turn. Transcripts live under `workspace/cron/wakes/`.

| Outcome | Behavior |
|---------|----------|
| Codex exit `0` | Debounce timestamp updated; daily note records **wake complete** |
| Codex exit non-zero | Wake marked **failed** in the log; debounce **not** updated; critique skipped if a mini run failed |
| `--dry-run` | Prints `codex exec` lines only; no subprocess |
| Lock busy | `WakeLockError`; another wake may be running |
| Debounce window | Skips run when `min_minutes_between` not elapsed |

Wake lock files use a stale timeout (default six hours) so crashed runs can recover.

### Memory layout

| Path | Role |
|------|------|
| `workspace/MEMORY.md` | Bootstrap facts (truncated to `bootstrap_max_chars`) |
| `workspace/memory/daily/YYYY-MM-DD.md` | Session notes |
| `workspace/memory/<category>/<entity>.md` | Domain notes (`category` is a single safe segment; no `..` or path separators) |
| `workspace/memory/architecture/working-divergence.md` | Skill vs workspace drift log |

`truncate_bootstrap` never returns more characters than the configured maximum (including very small limits).

## BACnet toolshed (repo checkout)

Field BACnet discovery, commissioning CSVs, and polling are in **`bacnet_toolshed/`** (not on PyPI). See **[BACnet toolshed](../bacnet/index)** and `openfdd.toml.example` `[build].drivers` / `driver-bacnet-ingest` skill.

## Rule authoring (operator stack)

Python rules for **Rule Lab** live under **`workspace/data/rules_py/`** with metadata in **`rules_store.json`**. Humans edit in **`/rule-lab`**; the **`agent`** role can write the same files via `POST /openfdd-agent/tool` (`rules.save`). See **[Rule Lab — Python storage](../docs/howto/rule_lab_storage.md)**.

Expression and YAML semantics for the **library** (`pip install "open-fdd[engine]"`) are unchanged. **`RuleRunner.run`** adds **integer** fault flag columns (`0` / `1`), not booleans—treat them as ints in pandas and downstream code. Missing input columns **fail** the run by default; per-rule `skip_missing_columns: true` skips checks for absent columns.

Start with the **[Expression rule cookbook](../expression_rule_cookbook)** and **[Rules overview](../rules/overview)** for YAML/library work.

## Tests (CI)

From the repo root:

```bash
pip install -e ".[dev]"
pip install -e "packages/openfdd-agent-shell[dev]"
pytest open_fdd/tests/engine -q
pytest packages/openfdd-agent-shell -q
```

The **`agent-shell`** job in `.github/workflows/ci.yml` runs the agent-shell suite on Python 3.12.

## Operator dashboard (committed starter)

A full **Rule Lab** stack ships under `workspace/api` and `workspace/dashboard` — see **[Operator dashboard (Rule Lab)](operator_dashboard)**. Agents should extend that code rather than scaffold from zero.

## Bridge and MCP (generated under `workspace/`)

When the agent scaffolds a FastAPI bridge and React dashboard (skills `fastapi-bridge-api`, `react-operator-dashboard`, `codex-agent-on-bridge`), the browser calls **`POST /openfdd-agent/chat`** on the bridge host—not Codex directly. Operator retrieval and route hints: **[Agent & operator playbook](agent_operator_playbook)**.

Historical desktop/MCP how-tos under **`howto/desktop_app.md`** describe the retired monolith; new integrations should follow **`skills/`** and **`workspace/`**.
