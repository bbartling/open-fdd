# Heartbeat — optional proactive checks

OpenClaw can wake the agent on a schedule. Keep tasks **idempotent** and **read-only** unless the operator explicitly wants automation.

Suggested prompts (edit to your environment):

1. `GET /health` on bridge + MCP; if not OK, summarize likely causes (wrong port, venv not started).
2. `GET /assistant/readiness`; if new sites appeared since last run, list them and one recommended Plots link per site (`plots_quicklinks`).
3. For each active site, note whether `GET /plots/frame?...&include_readiness=true` last run showed `recommend_clean_metrics` — do **not** auto-commit clean-metrics without human approval.

Remove sections you do not use so the agent does not churn on stale cron text.
