---
title: Open-FDD Codex architecture
nav_order: 8
---

# Open-FDD Codex architecture

This page documents the current AI architecture in this repository: **Codex CLI runs on the bridge host** and is orchestrated by the Open-FDD gateway.

## Core runtime

- **Gateway:** `open_fdd.gateway` exposes HTTP routes and builds Codex execution context.
- **Agent endpoint:** `POST /openfdd-agent/chat` handles model routing and tool-oriented prompts.
- **Raw endpoint:** `POST /local-codex/chat` provides a thinner Codex wrapper.
- **UI:** `apps/desktop-ui` calls bridge routes; it does not execute Codex directly.

## Authentication

- Codex CLI authentication is host-local (`codex login` and device login).
- Bridge device auth flow writes credentials under `$CODEX_HOME/auth.json` (default `~/.codex/auth.json`).
- OAuth tokens are persisted on the bridge host and are not returned to browsers.

## Routing policy

- SIMPLE tier defaults to `gpt-5.4-mini` (`OFDD_CODEX_MODEL_SIMPLE`).
- COMPLEX tier defaults to `gpt-5.5` with fallback `gpt-5.4` (`OFDD_CODEX_MODEL_COMPLEX`, `OFDD_CODEX_MODEL_COMPLEX_FALLBACK`).
- Successful SIMPLE turns run a COMPLEX critic pass by default (`OFDD_AGENT_SIMPLE_COMPLEX_CRITIC=0` disables).
- Operators can manually request COMPLEX routing from the AI chat UI.

## Related docs

- [Desktop app](howto/desktop_app)
- [Agent & operator playbook](howto/agent_operator_playbook)
- [Open-FDD + Easy-ASO test bench](howto/openfdd_easy_aso_bench)
