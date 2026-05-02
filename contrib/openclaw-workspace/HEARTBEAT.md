# Heartbeat — optional proactive checks

OpenClaw can wake the agent on a schedule. Keep tasks **idempotent** and **read-only** unless the operator explicitly wants automation.

Suggested prompts (edit to your environment):

1. `GET /health` on the bridge; `GET http://127.0.0.1:8090/manifest` on MCP. If MCP is down or `search_docs` fails (missing index), **tell the human** doc/API context is offline — run `python scripts/build_mcp_rag_index.py` from the repo root, restart MCP, and check `start-local` / port **8090**.
2. `GET /assistant/readiness`; if new sites appeared since last run, list them and one recommended Plots link per site (`plots_quicklinks`).
3. For each active site, note whether `GET /plots/frame?...&include_readiness=true` last run showed `recommend_clean_metrics` — do **not** auto-commit clean-metrics without human approval.

Remove sections you do not use so the agent does not churn on stale cron text.
