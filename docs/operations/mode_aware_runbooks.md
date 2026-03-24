---
title: Mode-aware runbooks
parent: Operations
nav_order: 6
---

# Mode-aware runbooks

Use bootstrap mode selection to run only the module you need.

## Engine-only

```bash
./scripts/bootstrap.sh --mode engine
./scripts/bootstrap.sh --mode engine --test
```

## Model-only

```bash
./scripts/bootstrap.sh --mode model
./scripts/bootstrap.sh --mode model --test
```

## Collector + Model

```bash
./scripts/bootstrap.sh --mode collector
./scripts/bootstrap.sh --mode model
```

## Full autonomous stack (OpenClaw + MCP)

```bash
./scripts/bootstrap.sh --mode full --with-mcp-rag
./scripts/bootstrap.sh --mode full --test
```

