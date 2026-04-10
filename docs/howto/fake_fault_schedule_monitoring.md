---
title: Monitor the fake fault schedule
parent: How-to guides
nav_order: 17
---

# Monitor the fake fault schedule

This page explains the right way to interpret spikes from the Open-FDD **fake BACnet bench** ([`openclaw/bench/fake_bacnet_devices/README.md`](https://github.com/bbartling/open-fdd/tree/main/afdd_stack/openclaw/bench/fake_bacnet_devices/README.md)).

## Why this matters

On this bench, a value like **SA-T = 180°F** is not automatically a product bug.

The fake BACnet devices intentionally inject deterministic faults so Open-FDD can be verified end to end. That behavior lives in:

- `openclaw/bench/fake_bacnet_devices/fault_schedule.py`
- `openclaw/bench/fake_bacnet_devices/fake_ahu_faults.py`
- `openclaw/bench/fake_bacnet_devices/fake_vav_faults.py`

## The shared UTC fault schedule

The fake AHU and fake VAV both follow the same repeating **UTC minute-of-hour** schedule:

| Minute (UTC) | Mode | Expected behavior |
|---|---|---|
| 0-9 | normal | scheduled points should stay in their rough normal band |
| 10-49 | flatline | scheduled points should hold constant |
| 50-54 | bounds | scheduled points should jump to **180.0°F** |
| 55-59 | normal | scheduled points should return to normal variability |

### Scheduled points

The current fake devices intentionally schedule faults on these points:

- fake AHU: `SA-T`, `RA-T`, `MA-T`
- fake VAV: `ZoneTemp`

That means the 180°F spike should be treated as:

- **expected bench behavior** during UTC minutes **50-54**
- **unexpected drift or misalignment** outside that window

## Recommended monitor

Use the repo helper:

```bash
python openclaw/bench/scripts/monitor_fake_fault_schedule.py
```

What it does:

- loads the same `fault_schedule.py` module used by the fake devices
- determines the current expected mode from UTC minute-of-hour
- reads the scheduled BACnet points directly through the DIY BACnet JSON-RPC API
- explains whether the observed values match the expected schedule

### Example output

```text
UTC time: 2026-03-24T12:52:10+00:00
Scheduled mode: bounds (minute 52 UTC)
Expected windows: normal 0-9, flatline 10-49, bounds 50-54, normal 55-59
- SA-T: PASS value=180.000 | matches scheduled bounds value 180.0 F
- RA-T: PASS value=180.000 | matches scheduled bounds value 180.0 F
- MA-T: PASS value=180.000 | matches scheduled bounds value 180.0 F
- ZoneTemp: PASS value=180.000 | matches scheduled bounds value 180.0 F
```

Configure the DIY BACnet gateway URL in the script or environment if it is not the default bench host.

## How to reason about anomalies

### Case 1: 180°F during UTC minutes 50-54

Treat this as **expected testbench fault injection**, not an unexpected product failure.

Next question:

- did Open-FDD surface the expected `bad_sensor_flag` in the corresponding fault window?

### Case 2: 180°F outside UTC minutes 50-54

Treat this as a likely anomaly in one of:

- fake-device schedule alignment
- fake-device runtime state
- testbench orchestration / timebase drift
- Open-FDD ingest lag or stale-value behavior

### Case 3: flatline window but value keeps changing

During UTC minutes 10-49, scheduled points should stop moving. If they do not, that points more toward:

- fake-device scheduling drift
- device restart / process interruption
- wrong host timezone / no UTC alignment on the Pi

## How this connects to Open-FDD verification

The better verification chain is:

1. use this monitor to confirm the fake BACnet source state
2. use SPARQL to confirm the points are modeled and addressable
3. use Open-FDD fault APIs or frontend fault views to verify the expected fault flags
4. compare the observed fault windows against `fault_schedule.py`

That is much stronger than treating a single spike as mysterious.

## Clone note

If OpenClaw is cloned onto another machine on the same bench, this page plus:

- [`openclaw/bench/fake_bacnet_devices/README.md`](https://github.com/bbartling/open-fdd/tree/main/afdd_stack/openclaw/bench/fake_bacnet_devices/README.md)
- [BACnet-to-fault verification](../bacnet/fault_verification)
- [OpenClaw context bootstrap](../operations/openclaw_context_bootstrap)
- `openclaw/bench/scripts/monitor_fake_fault_schedule.py`

should be enough to explain why the 180°F spike exists and how to monitor it correctly.
