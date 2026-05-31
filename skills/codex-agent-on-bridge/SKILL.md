---
name: codex-agent-on-bridge
description: "Runs OpenAI Codex CLI on the bridge host with bootstrap context for stack URLs and workspace write policy. Use when building AI agent chat or automating operator tasks against a generated bridge."
---

# Codex agent on bridge

## Policy

- Codex runs on the **bridge host** as a child process; credentials stay in `CODEX_HOME`.
- Browser **AI Agent** tab calls `POST /openfdd-agent/chat` (Ollama), not Codex directly.
- Durable FDD Python: `workspace/data/rules_py/` via Rule Lab or `POST /openfdd-agent/tool` (`rules.save`, **agent** role) — same files humans edit in `/rule-lab`. See [docs/howto/rule_lab_storage.md](../../docs/howto/rule_lab_storage.md).
- Scratch experiments: `workspace/scratch/` only unless promoting via `rules.save` or Rule Lab APIs.

## Bootstrap JSON

Include `bridge_base`, `mcp_rest_base`, `ui_public_base`, `desktop_data_dir`, `endpoints`, `workspace`, `notes` (see local-dev reference).

Env: `OFDD_AGENT_BOOTSTRAP_FILE`.

## Verification

`GET /local-codex/diagnostics`; `codex login` on host.

## Reference

Legacy: `open_fdd/gateway/openfdd_agent.py`, `openfdd_agent_context.py`, `codex_device_login.py`.
