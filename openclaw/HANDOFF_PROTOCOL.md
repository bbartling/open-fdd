# Cursor ↔ OpenClaw handoff protocol (Open-FDD lab)

OpenClaw (dashboard at your LAN gateway) and Cursor (this IDE chat) **do not talk to each other**. You are the **router**. The **shared ground truth** is this git tree, especially:

- `openclaw/issues_log.md` — append-only diagnosis + status (use dated sections).
- `openclaw/logs/bootstrap-test-*.txt` — full command transcripts.
- Optional: `memory/YYYY-MM-DD.md` at **workspace** root for human-facing notes.

## File-only loop (no HTTP between Cursor and OpenClaw)

You do **not** need any HTTP (or other network API) **between** Cursor and OpenClaw. Both can read/write the **same files on disk** (your workspace under `~/.openclaw/workspace/`). That is the feedback channel.

**What “continuous” means here:** not a live duplex stream, but **repeatable rounds**:

1. **OpenClaw round:** read latest `issues_log.md` + `HANDOFF_PROTOCOL.md` → run commands → write `openclaw/logs/<run>.txt` → **append** to `issues_log.md` (`runner: openclaw`, `log: …`, `next for senior:` if needed).
2. **Human tick:** save files (commit optional).
3. **Cursor round:** you paste *“read `openclaw/issues_log.md` (latest date) and the log path it cites…”* → Cursor triages → **append** under the same date: `runner: cursor`, `resolved by cursor:` or `open questions:` with minimal fix notes (and code changes in repo).
4. **Repeat:** next OpenClaw session starts by reading `issues_log.md` again; it sees what Cursor resolved and what to run next.

So the loop is **mailbox-style**: `issues_log.md` is the inbox/outbox; log files are attachments. No agent calls the other over HTTP.

**Optional automation (still file-centric):** `git pull` / `git push` between machines; `inotifywait` + script; or cron running shell tests that only write logs + append `issues_log.md`. The “wire” remains files, not Cursor↔OpenClaw HTTP.

**Note:** OpenClaw still uses normal HTTPS to model providers, and the Control UI uses your gateway URL—that’s unrelated to Cursor↔OpenClaw coupling.

## Roles (intentional)

| Who | Role |
|-----|------|
| **You (human)** | Run gateway, paste prompts, commit/push, decide when to escalate |
| **Cursor / “senior”** | Architecture, code fixes, script changes, doc structure, triage of hard failures |
| **OpenClaw / “junior”** | Execute repeatable commands, capture logs, file issues, small safe edits you allow |

## Issues log format (for fast pickup)

Append under today’s `## YYYY-MM-DD` header, one block per run:

```markdown
- **runner:** openclaw | cursor | human
- **branch:** …
- **command:** …
- **log:** `openclaw/logs/<file>.txt`
- **result:** pass | fail | blocked
- **summary:** one line
- **next for senior:** optional — only if blocked or needs code change
```

**Cursor** resolves or strikes through `next for senior` items in a follow-up commit when fixed (or replies in chat with PR-style summary).

## OpenClaw standing prompt (paste in Control UI)

Use path discipline: workspace root has `AGENTS.md` / `SOUL.md`; **all shell work from `open-fdd/` repo root** after `cd open-fdd`.

1. Read `openclaw/HANDOFF_PROTOCOL.md` and the latest section of `openclaw/issues_log.md`.
2. Ensure `.venv` exists and `pip install -e ".[dev]"` was run; `bootstrap.sh` uses `.venv/bin/python` when present.
3. Run tests in this order unless `issues_log` says otherwise:
   - `./scripts/bootstrap.sh --verify` (light) if stack already up
   - `./scripts/bootstrap.sh --test` (full matrix)
   - Mode slices: `--mode collector`, `--mode model`, `--mode engine` as documented in `openclaw/README.md`
4. Every long run: `mkdir -p openclaw/logs` and tee/nohup to `openclaw/logs/bootstrap-test-$(date +%F_%H-%M-%S).txt`.
5. Append results to `openclaw/issues_log.md`. If failure needs design or product code, write **`next for senior:`** with log path and first error line — do **not** guess large refactors without human OK.
6. For **AI / data-modeling** smoke: when stack is up, follow `docs/openclaw_integration.md` and `openclaw/README.md` (SPARQL bench, MCP manifest at `http://localhost:8000/mcp/manifest` with Bearer from `stack/.env` when auth is on). Document what you hit; don’t post secrets in `issues_log`.

## What “all night” actually means

No LLM runs 18 hours inside Cursor in one session. For **long autonomy**, use **the shell**:

```bash
cd /path/to/open-fdd && mkdir -p openclaw/logs
ts=$(date +%F_%H-%M-%S)
nohup bash -lc '
  cd /path/to/open-fdd &&
  . .venv/bin/activate &&
  ./scripts/bootstrap.sh --test
' > "openclaw/logs/nightly-$ts.txt" 2>&1 &
echo $! > "openclaw/logs/nightly-$ts.pid"
```

Then **OpenClaw or you** summarizes `nightly-*.txt` into `issues_log.md`. Cursor picks up the next morning on **files**, not live coupling.

## Skills / context

Versioned skill: **`openclaw/SKILL.md`** plus **`references/`**, **`scripts/`**, **`assets/`**. Install for OpenClaw via **`references/skill_installation.md`** (symlink into `workspace/skills/open-fdd-lab` or equivalent). Multi-session / “hours of lab” queue: **`references/long_run_lab_pass.md`** (paste block + rules; on GitHub with the repo). Also read **`openclaw/README.md`**. Prefer **git** for versioning (`openclaw/` commits).

## GitHub backup (clone on another machine)

Upstream is **`bbartling/open-fdd`**. If you do **not** have push access, **fork** it on GitHub to your account, then point your clone at the fork and push your branch.

```bash
cd open-fdd
git remote rename origin upstream   # optional; only if you already cloned upstream
git remote add origin https://github.com/YOUR_USER/open-fdd.git
git fetch origin
git push -u origin develop/v2.0.7   # or your working branch name
```

On the new machine:

```bash
git clone https://github.com/YOUR_USER/open-fdd.git
cd open-fdd
git checkout develop/v2.0.7   # or whatever branch you pushed
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
```

**What to commit** so the OpenClaw/Cursor handoff survives a clone: `openclaw/HANDOFF_PROTOCOL.md`, `openclaw/issues_log.md`, `openclaw/README.md`, and any script/doc changes (`scripts/bootstrap.sh`, root `README.md`, etc.). Large `openclaw/logs/*.txt` files are optional—keep if you want evidence in the repo, or delete before push and rely on `issues_log.md` summaries only.

**Not pushed** (see repo `.gitignore`): `openclaw/.skill-workspace-marker`, `openclaw/logs/*.pid`, generated `openclaw/dashboard/progress.json`, most of `openclaw/reports/*.md`. Workspace-level OpenClaw config (`~/.openclaw/openclaw.json`, gateway token) **never** belongs in this repo—clone + new `openclaw onboard` on each host if needed.
