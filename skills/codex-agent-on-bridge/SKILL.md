---
name: codex-agent-on-bridge
description: "Runs OpenAI Codex CLI on the bridge host with bootstrap context for stack URLs and workspace write policy. Use when building AI agent chat or automating operator tasks against a generated bridge."
---

# Codex agent on bridge

## Policy

- Codex runs on the **bridge host** as a child process; credentials stay in `CODEX_HOME`.
- Browser UI calls bridge `/openfdd-agent/chat`, not Codex directly.
- Agent file writes default to `workspace/scratch`.

## Bootstrap JSON

Include `bridge_base`, `mcp_rest_base`, `ui_public_base`, `desktop_data_dir`, `endpoints`, `workspace`, `notes` (see local-dev reference).

Env: `OFDD_AGENT_BOOTSTRAP_FILE`.

## Verification

`GET /local-codex/diagnostics`; `codex login` on host.

## Reference

Legacy: `open_fdd/gateway/openfdd_agent.py`, `openfdd_agent_context.py`, `codex_device_login.py`.
