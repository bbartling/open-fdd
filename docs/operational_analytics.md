# Operational analytics (zone temps, poll health, building insight)

The home **Building insight** panel and agent tools use a shared **14-day** feather historian window (`OFDD_ANALYTICS_LOOKBACK_DAYS`, default `14`). Data flows:

```text
BACnet poll → workspace/data/feather_store/
  → data_loader.load_frame_for_run()
  → zone_temp_analytics / device_poll_health / zone_energy_research
  → building_insight (Ollama or deterministic fallback)
```

## Zone temperatures

- **Day / night averages** — Weekday occupied hours from `OFDD_OCCUPIED_START_HOUR` / `OFDD_OCCUPIED_END_HOUR` (default 08–17) in `OFDD_SITE_TIMEZONE`.
- **Recovery °F/min** — Mean zone warm-up slope for up to 30 minutes after each supply-fan **start** (requires fan command/speed on the AHU in the BRICK model).

When the summary shows **~0.00°F/min** recovery and day/night averages are nearly identical (e.g. 69.5°F overnight vs 69.0°F occupied), the edge host does **not** assume a broken HVAC plant first. `zone_energy_research` sets deterministic flags:

| Flag | Meaning |
|------|---------|
| `site_near_zero_recovery` | Median AHU recovery below `OFDD_NEAR_ZERO_RECOVERY_FPM` (default `0.05`) |
| `widespread_minimal_setback` | Many zones with day−night spread &lt; `OFDD_MIN_SETBACK_DELTA_F` (default `1.5°F`) |
| `likely_no_overnight_setback` | Majority of zone sensors show minimal setback |
| `unoccupied_heat_gain` / `unoccupied_heat_loss` | Net °F/h drift during unoccupied hours |
| `poll_stale` / `fdd_active` / `flat_unoccupied_profile` | Cross-check against **device poll health** and FDD bindings |

## LLM building insight

`GET /openfdd-agent/building-insight` passes compact JSON to Ollama including:

- `zone_temps` — averages, recovery, struggling zones
- `zone_research` — flags, `opportunities[]`, and `llm_research_tasks[]`
- `device_poll_health` — offline / flaky / degraded equipment

The system prompt requires the model to:

1. Interpret near-zero recovery honestly (often **missing setback**, not “AHU can’t heat”).
2. Cross-check **stale or FDD zone sensors** before recommending schedule changes.
3. Call out **energy savings** when `opportunities` includes `energy_setback` (wider night setback, schedule review).
4. Reference active **fault_sentences** from the check engine.

If Ollama is down, the deterministic sentence still includes zone + poll summaries; research `opportunities` are exposed on the API for the UI bullet list.

## APIs

| Route | Purpose |
|-------|---------|
| `GET /openfdd-agent/building-insight` | Cached operator sentence + `zone_temps.research` |
| `GET /openfdd-agent/operational-brief` | Full structured payload (zones, devices, research, methodology) |
| `GET /openfdd-agent/zone-temps` | Zone snapshot only |
| `GET /openfdd-agent/device-poll-health` | Poll/FDD health only |

Agent tools: `building.zone_temps`, `building.device_health`, `building.operational_brief`.

## Environment levers

| Variable | Default | Role |
|----------|---------|------|
| `OFDD_ANALYTICS_LOOKBACK_DAYS` | `14` | Historian trim window |
| `OFDD_SITE_TIMEZONE` | `America/Chicago` | Occupied hours + poll local time |
| `OFDD_NEAR_ZERO_RECOVERY_FPM` | `0.05` | “No warm-up” threshold |
| `OFDD_MIN_SETBACK_DELTA_F` | `1.5` | Minimal day/night spread |
| `OFDD_BUILDING_INSIGHT_INTERVAL_S` | `900` | Insight cache TTL |

See also [local_ollama.md](local_ollama.md) for Ollama setup on bensserver vs edge.
