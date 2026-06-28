# Open-FDD Rust Edge Documentation

Open-FDD is a local-first, on-prem HVAC supervisory fault-detection edge application built around **Rust**, **Apache Arrow**, **DataFusion SQL**, **React**, and **Docker/GHCR**.

## Architecture

Open-FDD uses **Apache Arrow** and **Feather** as the native historian and data storage layer, while **DataFusion SQL** serves as the fault detection and analytics engine that operates directly on those Arrow datasets. Telemetry from BACnet, Haystack, Modbus, and JSON APIs is normalized into Arrow-native structures (persisted as Feather files at the edge) instead of a traditional relational database. DataFusion executes SQL-based fault detection rules, reporting logic, and data quality checks directly against that historian.

The stack is migrating to an all-Rust edge runtime: BACnet and Modbus drivers, Haystack gateway, Arrow historian, DataFusion FDD, JWT auth, and the React dashboard. Docker containers (`openfdd-bridge`, `openfdd-commission`, `openfdd-haystack-gateway`) share one workspace volume and form a self-hosted platform without cloud dependency.

Full detail: [architecture/overview.md](architecture/overview.md).

## Quick start

| Topic | Document |
| --- | --- |
| Fresh GHCR install | [quick-start/rust-edge-bootstrap.md](quick-start/rust-edge-bootstrap.md) |
| Backup, update, restore | [quick-start/rust-site-lifecycle.md](quick-start/rust-site-lifecycle.md) |
| Raspberry Pi / ARM64 | [quick-start/raspberry-pi-rust-edge.md](quick-start/raspberry-pi-rust-edge.md) |

## Local development

| Topic | Document |
| --- | --- |
| **Build recipes** (local up, Caddy TLS, auth) | [deployment/local-dev.md](deployment/local-dev.md) |
| UI inspection (no long validation) | [deployment/local_ui_inspection.md](deployment/local_ui_inspection.md) |
| GHCR vs local Dockerfile | [deployment/local_ui_build.md](deployment/local_ui_build.md) |
| Caddy LAN ingress | [deployment/caddy.md](deployment/caddy.md) |
| Windows Docker Desktop | [deployment/windows_docker_desktop.md](deployment/windows_docker_desktop.md) |

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
| Platform overview | [architecture/overview.md](architecture/overview.md) |
| **Open-FDD OS (future concept)** | [../os/README.md](../os/README.md) — HA OS–inspired appliance image; Rust GHCR under the hood |
| Local BACnet server (diagnostics) | [architecture/bacnet-local-server.md](architecture/bacnet-local-server.md) |
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
| FDD Wires and SQL rules | [verification/fdd-wires.md](verification/fdd-wires.md) |
| Live FDD validation (development) | [testing/live-fdd-validation.md](testing/live-fdd-validation.md) |
| Legacy bench 5007 runbook | [verification/bench-5007-long-smoke.md](verification/bench-5007-long-smoke.md) |

## AI agent and FDD cookbooks

| Topic | Document |
| --- | --- |
| AI agent index | [ai-agent/README.md](ai-agent/README.md) |
| Haystack + assignments | [ai-agent/haystack-and-assignments.md](ai-agent/haystack-and-assignments.md) |
| SQL HVAC FDD rules | [rule-cookbook/sql-hvac-fdd.md](rule-cookbook/sql-hvac-fdd.md) |

## AI agents

See [ai-agent-context.md](ai-agent-context.md) and root [AGENTS.md](../AGENTS.md) for safe operator guidance (no workspace deletion, no `docker compose down -v`, no secret printing).
