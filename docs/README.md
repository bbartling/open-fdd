# Open-FDD Rust Edge Documentation

Open-FDD is a local-first, on-prem HVAC supervisory fault-detection edge application built around **Rust**, **Apache Arrow**, **DataFusion SQL**, **React**, and **Docker/GHCR**.

## Quick start

| Topic | Document |
| --- | --- |
| Fresh GHCR install | [quick-start/rust-edge-bootstrap.md](quick-start/rust-edge-bootstrap.md) |
| Backup, update, restore | [quick-start/rust-site-lifecycle.md](quick-start/rust-site-lifecycle.md) |
| Raspberry Pi / ARM64 | [quick-start/raspberry-pi-rust-edge.md](quick-start/raspberry-pi-rust-edge.md) |

## Operations

| Topic | Document |
| --- | --- |
| Site update and restore | [operations/rust-update-restore.md](operations/rust-update-restore.md) |
| Production Caddy TLS | [operations/production-caddy.md](operations/production-caddy.md) |
| Auth and credentials | [security/rust-edge-auth.md](security/rust-edge-auth.md) |
| CI and GitHub Actions | [verification/ci-github-actions.md](verification/ci-github-actions.md) |

## Architecture

| Topic | Document |
| --- | --- |
| Drivers, historian, and FDD | [architecture/drivers-and-fdd.md](architecture/drivers-and-fdd.md) |
| Haystack assignment model | [ASSIGNMENT_MODEL.md](ASSIGNMENT_MODEL.md) |
| Agent API surface | [AI_AGENT_API.md](AI_AGENT_API.md) |
| OpenAPI spec | [openapi.yaml](openapi.yaml) |

## Verification checklists

Manual QA procedures live under [verification/](verification/). Use these after bootstrap, driver changes, or releases — they are **not** bench-specific runbooks.

| Check | Document |
| --- | --- |
| BACnet NIC and bind config | [verification/bacnet-nic-setup.md](verification/bacnet-nic-setup.md) |
| BACnet override scan and CSV | [verification/bacnet-overrides.md](verification/bacnet-overrides.md) |
| Modbus live path | [verification/modbus-live.md](verification/modbus-live.md) |
| Default React UI | [verification/ui-smoke.md](verification/ui-smoke.md) |
| Auth, login, and RBAC | [verification/auth-and-login.md](verification/auth-and-login.md) |

## AI agents

See [ai-agent-context.md](ai-agent-context.md) and root [AGENTS.md](../AGENTS.md) for safe operator guidance (no workspace deletion, no `docker compose down -v`, no secret printing).
