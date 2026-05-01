---
title: Configuration
nav_order: 12
---

# Configuration

This page describes how to **configure YAML rules** and engine behavior when using the **`open_fdd`** library directly. There is **no** required platform database or HTTP service in this repository.

---

## Rule YAML

Rules are loaded with **`load_rule()`** / **`RuleRunner`** (see [Rules overview](rules/overview)).

Typical fields include:

| Field | Role |
|-------|------|
| **`name`**, **`description`** | Human-readable metadata |
| **`equipment_type`** | Optional filter for which equipment a rule applies to |
| **`type`** | Check type (`bounds`, `flatline`, `expression`, …) |
| **`params`** | Check-specific parameters (thresholds, `rolling_window`, …) |
| **`column_map`** | Mapping from logical point names to DataFrame columns (dict or manifest path) |

Use **`fdd_strict_rules`**-style tightening in **your** caller if you want stricter validation of column maps and dtypes before evaluation (see [Expression rule cookbook](expression_rule_cookbook)).

---

## Column maps

- **Inline dict** — simplest: `{ "SAT": "SupplyAirTemp" }` keys match placeholders in the rule.
- **Manifest YAML** — see [Column map resolvers](column_map_resolvers) for **`ManifestColumnMapResolver`** and composite patterns.

---

## Environment variables

### Rules engine (library)

The **`open-fdd`** wheel does **not** require a fixed `OFDD_*` namespace for **`RuleRunner`**. Your **application** may use env vars to locate rule directories or data files; that is entirely under your control.

### Desktop gateway (`pip install "open-fdd[desktop]"`)

When you run **`open-fdd-gateway`** / **`open-fdd-desktop-bridge`**, optional **`OFDD_*`** variables control storage and TTL sync. Defaults use a per-user writable directory (`%APPDATA%\open-fdd-desktop` on Windows, platform-specific elsewhere) unless overridden. The repo **`scripts/start-local.ps1`** and **`scripts/start-local.sh`** set repo-local paths under **`stack/local-data`**.

| Variable | Role |
|----------|------|
| **`OFDD_DESKTOP_DATA_DIR`** | Root for `model.json`, `feather_store/`, default rules copy, etc. |
| **`OFDD_MODEL_TTL_PATH`** | Destination file for generated BRICK TTL (default: `<desktop_data_dir>/data_model.ttl`). |
| **`OFDD_MODEL_TTL_MIRROR_PATH`** | Optional second TTL write (atomic mirror) for tools that watch another path. |
| **`OFDD_TTL_SYNC_INTERVAL_SECONDS`** | Background TTL sync interval from `model.json`. |
| **`OFDD_BRIDGE_URL`** | Base URL the UI and MCP use to reach the gateway (launchers set this). |

See **[Desktop app](howto/desktop_app)** for launchers, ports, and ingest APIs.

---

## Related topics

- [Rules overview](rules/overview)
- [Engine-only / IoT](howto/engine_only_iot)
- [Getting started](getting_started)
