---
title: Ollama and analytics
parent: Operator Bridge
nav_order: 6
---

# Ollama and analytics

## What runs without login

The **Building status** home page (`/`) and `GET /openfdd-agent/building-insight` are **public** (same policy as fault status). Anyone on the LAN can read the briefing sentence and underlying numeric levers; only the **AI Agent** chat and stack revision endpoints require sign-in.

## Ollama setup

1. Copy `workspace/ollama.env.example` → `workspace/ollama.env.local`.
2. Pick a model for available RAM (comments in the example file):

| RAM tier | Suggested model |
|----------|-----------------|
| 4 GB Pi | `qwen3:0.6b` |
| 8 GB | `qwen3:1.7b` |
| 16 GB | `qwen3:4b` |
| 32 GB | `qwen3:8b` |
| 64 GB | `qwen3:14b` |

3. Set `OFDD_OLLAMA_BASE_URL` (default `http://127.0.0.1:11434`).
4. Optional: `OFDD_OLLAMA_GPU_MODE` (`cpu` / `auto` / `gpu`), `OFDD_OLLAMA_TIMEOUT_S` for slow CPUs.
5. Bootstrap helper: `./scripts/bootstrap_ollama.sh`.

Bridge reads env via `run_local.sh` / compose. Model resolution: `workspace/api/openfdd_bridge/ollama_profiles.py`.

## Automatic analytics (deterministic, always on)

These pandas calculations run on a refresh interval and feed the home dashboard **whether or not Ollama is up**:

| Lever | Module | Refresh env | What it computes |
|-------|--------|-------------|------------------|
| Zone temperature snapshot | `zone_temp_analytics.py` | `OFDD_ZONE_TEMP_INTERVAL_S` (default 3600s) | Site-wide and per-AHU zone temp averages, spread, out-of-band counts using BRICK `feeds` (AHU→VAV) when modeled; falls back to all `Zone_Air_Temperature*` points |
| Device poll health | `device_poll_health.py` | stack health cycle | BACnet device last-seen / stale poll detection |
| Operational brief | `building_insight.py` → `get_operational_brief` | same as insight | Compact numeric status for integrators |
| Root-cause hints | `root_cause_hints.py` | on insight refresh | Multi-zone fault chains using `brick:feeds` from TTL |

Shared lookback window: `OFDD_ANALYTICS_LOOKBACK_DAYS` (default 14) in `operational_analytics.py`.

API routes (auth optional unless noted):

- `GET /openfdd-agent/building-insight` — sentence + zone snapshot + fault sentences
- `GET /openfdd-agent/zone-temp-analytics`
- `GET /openfdd-agent/device-poll-health`
- `GET /openfdd-agent/ollama/health` — integrator diagnostics

## When Ollama is used

`building_insight.get_building_insight()`:

1. Refreshes zone + device snapshots (pandas).
2. Calls `ollama_client.health()`.
3. If Ollama is reachable and `should_use_ollama_for_insight()` passes, sends a **compact context** (status, zone levers, feeds chains) to the configured model for a one-sentence briefing (`source: "ollama"`).
4. On failure, uses `_fallback_sentence()` (`source: "deterministic"`).

Context assembly: `building_insight._compact_context()`. Prompt template references BRICK feeds and `root_cause_hints`.

## AI Agent (authenticated)

`/agent` page uses `POST /openfdd-agent/chat` with tool access (`agent_tools.py`): BRICK graph, scope bundles, rule binding patches, model health, etc. This is separate from the public home briefing.

## Code map

```
workspace/api/openfdd_bridge/
  building_insight.py      # cached home briefing + Ollama sentence
  zone_temp_analytics.py   # zone temp levers (BRICK feeds)
  device_poll_health.py    # BACnet poll staleness
  operational_analytics.py # lookback window + methodology dict
  root_cause_hints.py      # multi-fault BRICK chain hints
  ollama_client.py         # HTTP client to Ollama
  ollama_profiles.py       # RAM tiers / model names
```

Dashboard consumers: `BuildingStatusPage.tsx`, `StackStatusStrip.tsx` (WebSocket `/ws/dashboard`).
