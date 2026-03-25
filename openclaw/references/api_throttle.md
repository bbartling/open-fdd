# API / model usage throttling (OpenAI Codex, etc.)

OpenClaw agents burn **context and rate limits** on long transcripts and tight loops.

## Five-bullet session status (no log dumps)

When the human asks for a **lab snapshot** (often together with **`issues_log.md`** + **`long_run_lab_pass.md`** + this file), reply with **exactly five bullets**: **what finished**, **what’s running**, **latest log paths**, **pass/fail**, **what’s next** — **no pasted log bodies**. Checklists and the canonical human prompt: **`session_status_summary.md`**.

## Practices

1. **Batch work:** one bootstrap + one test log per “round”; avoid re-explaining the whole repo each message.
2. **Prefer local tools:** `curl`, `docker compose logs`, reading `issues_log.md` over re-summarizing logs into chat.
3. **Cheaper steps first:** `./scripts/bootstrap.sh --verify` before full `--test` when checking “still up”.
4. **Avoid redundant LLM calls:** don’t re-run SPARQL or LLM-assisted import for the same fixture twice in one session without a reason.
5. **Summarize once:** after a long log, write **5 lines** to `issues_log.md` instead of pasting 500 lines into provider chat.
6. **Modes, not always full:** use `--mode collector|model|engine` when the human only needs that slice.
7. **Background jobs:** when `nohup … &` was used, finish with **exit code + log path** in chat and **append `issues_log.md`** for that step; do not assume the human watched the terminal.
8. **Minimal chat replies:** after long runs, reply **pass/fail + log paths + next command** only; put summaries in **`issues_log.md`** (`long_run_lab_pass.md` has a paste block for this).

## Control UI / context window

- If the session shows **high context %**, stop pasting log excerpts into chat — **read files on disk** and write **`issues_log.md`** instead.
- Prefer **foreground** `capture_bootstrap_log.sh` for clarity unless the human explicitly wants background + a follow-up “when done” prompt.

## When limits hit

- Stop; append **blocked** to `issues_log.md` with `next for senior`.
- Human can switch model, wait, or continue in Cursor with file-based context.
