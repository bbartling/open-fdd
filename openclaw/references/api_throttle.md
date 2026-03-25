# API / model usage throttling (OpenAI Codex, etc.)

OpenClaw agents burn **context and rate limits** on long transcripts and tight loops.

## Practices

1. **Batch work:** one bootstrap + one test log per “round”; avoid re-explaining the whole repo each message.
2. **Prefer local tools:** `curl`, `docker compose logs`, reading `issues_log.md` over re-summarizing logs into chat.
3. **Cheaper steps first:** `./scripts/bootstrap.sh --verify` before full `--test` when checking “still up”.
4. **Avoid redundant LLM calls:** don’t re-run SPARQL or LLM-assisted import for the same fixture twice in one session without a reason.
5. **Summarize once:** after a long log, write **5 lines** to `issues_log.md` instead of pasting 500 lines into provider chat.
6. **Modes, not always full:** use `--mode collector|model|engine` when the human only needs that slice.

## When limits hit

- Stop; append **blocked** to `issues_log.md` with `next for senior`.
- Human can switch model, wait, or continue in Cursor with file-based context.
