---
title: Secrets and auth
parent: Security
nav_order: 5
---

# Secrets and auth

## Files (gitignored)

| File | Contents |
|------|----------|
| `workspace/auth.env.local` | JWT secret, role passwords |
| `workspace/json_api.env.local` | REST API keys for JSON API `${ENV:VAR}` URLs (e.g. OpenWeather `OPENWEATHER_API_KEY`) |
| `workspace/data.env.local` | Historian + **audit log retention** (`OFDD_LOG_*`, `OFDD_FEATHER_*`) |
| `workspace/ollama.env.local` | Ollama URL, model, RAM tier, GPU mode |
| `workspace/mcp.env.local` | MCP RAG sidecar |
| `workspace/caddy.env.local` | Reverse proxy TLS/HTTP mode |
| `workspace/pentest.env.local` | LAN security scan stack |
| `infra/ansible/secrets/<host>.env.local` | SSH deploy secrets (maintainers) |

Copy from `*.example` templates only. Full inventory: [Workspace env files]({{ "/appendix/workspace-env-files/" | relative_url }}).

## Required variables (production)

| Variable | Purpose |
|----------|---------|
| `OFDD_AUTH_SECRET` | HMAC signing (32+ chars) |
| `OFDD_INTEGRATOR_USER` / `PASSWORD` | Rule Lab, bindings |
| `OFDD_OPERATOR_USER` / `PASSWORD` | Operations |

## GHCR pulls

Use read-only registry credentials on edge if images are private; rotate tokens periodically.

## Backup

Back up `workspace/data/` and auth env in secure operator vault — not in git.

Audit JSONL under `workspace/logs/` may contain client IPs and usernames — treat like security logs. See [Logging and audit]({{ "/ops/logging/" | relative_url }}).
