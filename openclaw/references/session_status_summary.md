# Session status summary (5 bullets — no log dumps)

When the human asks for **lab state** without re-pasting repo context, use this contract. It keeps **provider context** small and matches **`api_throttle.md`**.

## Mandatory output shape (exactly 5 bullets)

Reply with **only** these five bullets (titles fixed; content fills in). **Do not** paste **bodies** of `openclaw/logs/*.txt`, `docker compose logs`, or multi-line shell output into chat — **paths + one-line outcomes only**.

1. **What finished** — Completed steps since the last human message (or “none”). Cite **`issues_log.md`** bullets by **date section** + short paraphrase (e.g. “2026-03-27: verify green”).
2. **What’s running** — Foreground/background jobs: **command** (short), **PID** if known, **`nohup`/terminal** if applicable, **“unknown / check host”** if unclear. If nothing: **“Nothing observed running.”**
3. **Latest log paths** — **Full paths** to every `openclaw/logs/bootstrap-test-*.txt` (and `nohup-*.out` if used) mentioned in the **latest `##` sections** of **`issues_log.md`**, newest first. If none cited: **“No log paths in latest sections — see issues_log to add.”**
4. **Pass / fail / blocked** — Per **latest** cited runs: **pass**, **fail**, or **blocked** + **one phrase** each (e.g. “verify: pass”, “collector: running”, “bench: blocked — no Selenium”). If a step has no explicit result in `issues_log`, say **“unclear — see log file.”**
5. **What’s next** — Next **one** concrete action from **`long_run_lab_pass.md`** queue, **`issues_log`** “next for senior”, or explicit human goal; if blocked, say **what unblocks** (human command, permission, merge).

## Human paste prompt (copy as-is)

```text
Read openclaw/issues_log.md (latest ## sections), openclaw/references/long_run_lab_pass.md, and openclaw/references/api_throttle.md.

Summarize in 5 bullets: what finished, what’s running, latest log paths, pass/fail, what’s next. Don’t paste log bodies.
```

Optional add-ons (same message):

```text
Also list any PIDs or nohup jobs you infer from issues_log only (no log file dumps).
If latest sections disagree, say which ## section you treated as canonical and why.
```

## Checklist — before you answer (agent)

- [ ] Read **all** `## YYYY-MM-DD` headers in `openclaw/issues_log.md` from the **newest section backward** until you have enough context (at minimum **the two most recent** dated sections, or everything from “today” if only one).
- [ ] Skim **`long_run_lab_pass.md`** for the **default queue order** and **logging rules** so “what’s next” matches the runbook unless `issues_log` overrides.
- [ ] Skim **`api_throttle.md`** — apply **minimal chat**: no log excerpts, **paths only**.
- [ ] Extract **log paths** with regex/pattern: `openclaw/logs/bootstrap-test-*.txt`, `openclaw/logs/nohup*.out`, absolute paths if written that way — **dedupe**, **sort newest first** by filename timestamp when obvious.
- [ ] **Running:** look for **PID**, **nohup**, **awaiting**, **background**, **started** in latest bullets; if the human’s environment might have jobs not in the file, say **“not visible in issues_log — verify on host.”**
- [ ] **Pass/fail:** map words like **green**, **passed**, **OK**, **fail**, **error**, **blocked**, **skipped** to the bullet-4 line; if missing, **unclear**.
- [ ] **Do not** open and quote log files in the reply; if you read a log for yourself, **do not** paste lines — only **conclusions** + **path**.

## Checklist — what “latest ## sections” means

- [ ] **Newest section first:** start at the **last** `## YYYY-MM-DD` (or `## YYYY-MM-DD — title`) in the file.
- [ ] **Multiple topics under one date:** still one **date section**; summarize **all bullets** under it for “finished” / “running” / “paths”.
- [ ] If the file has **no dated section** (only preamble), say so in bullet 1 and point to **`HANDOFF_PROTOCOL.md`** for how to append dated sections.

## Checklist — edge cases

- [ ] **Contradictory bullets** in the same day → state the **newest bullet wins** or **contradiction** in bullet 4 in one short phrase.
- [ ] **Stale PIDs** → mention “PID from log may be stale; verify on host.”
- [ ] **Secrets** → never paste API keys, Bearer tokens, or `.env` lines; **path to stack/.env** only if needed (“configure auth per README”).
- [ ] **Workspace vs repo root** → log paths must be **repo-relative or absolute as stored**; if OpenClaw cwd is wrong, note **“confirm cwd is open-fdd repo root.”**

## Where this is referenced

- **`openclaw/SKILL.md`** — session status behavior.
- **`openclaw/references/long_run_lab_pass.md`** — paste blocks + queue.
- **`openclaw/references/api_throttle.md`** — why we avoid log dumps.
