# Tools — Open-FDD bridge & MCP (cheat sheet)

## Bridge REST (8765)

| Goal | Method | Path / notes |
|------|--------|----------------|
| Liveness | GET | `/health` |
| Handoff snippet | GET | `/assistant/readiness` |
| Site profiles pack | POST | `/assistant/apply-site-profiles` — `profiles_yaml` absolute path under repo `examples/` |
| Ingest CSV | POST | `/ingest/csv` or `/ingest/csv/upload` |
| Numeric clean | POST | `/timeseries/clean-metrics` — `commit:false` first |
| Plot frame | GET | `/plots/frame`, `/plots/site-frame` — `include_readiness=true` optional |
| FDD + frame | POST | `/plots/fdd-frame` |
| Saved handoff | POST | `/plots/share` — returns `plots_open_url` |
| Rules | GET/PUT | `/rules`, `/rules/export-json`, `/rules/{file}` |
| Model | GET/POST | `/model/export`, `/model/import` |
| OpenClaw + model | POST | `/assistant/data-model-openclaw` — needs gateway token |

## MCP RAG (8090) — action tools (examples)

See live **`POST /manifest`** on the MCP service. Typical names include:

- `bridge_health`, `bridge_readiness`, `bridge_apply_site_profiles`
- `bridge_timeseries_clean_metrics`, `bridge_rules_list`, `bridge_rules_export_json`, `bridge_rules_put`
- `data_model_export`, `data_model_import`, driver and weather helpers

Authenticate with `Authorization: Bearer <OFDD_MCP_OFDD_API_KEY>` when the server requires it.

## OpenClaw gateway (18789)

- Chat UI and **Codex OAuth** live here; Open-FDD bridge does **not** store ChatGPT tokens.
- HTTP chat API: enable **`chatCompletions`** in gateway config per OpenClaw docs; use gateway bearer token from `openclaw.json`.
