---
title: Python recipes (legacy row)
parent: Rule Cookbook
nav_order: 2
---

# Python recipes (legacy row)

> **Open-FDD 3.0 default:** use [Arrow recipes](arrow-recipes) with `apply_faults_arrow`. These `evaluate(row, …)` patterns apply only when the rule is saved with **`backend: legacy_row`**.

Each recipe: **use case → inputs → code → behavior → tuning → false positives**.

---

## 1 — Flatline (1 hour window)

**Use case:** Stuck sensor, failed thermistor, frozen BACnet value.

**Inputs:** `temp` or `rh` in `row`; `rows` history ≥ 1 h span.

```python
from open_fdd.playground.cookbook import cfg_threshold, hour_window_ready, window_rows_1h

def evaluate(row, cfg, prev_row=None, rows=None):
    if not rows:
        return False
    window = window_rows_1h(row, rows)
    if not hour_window_ready(window):
        return False
    vals = [r.get("temp") for r in window if r.get("temp") is not None]
    if len(vals) < 2:
        return False
    spread = max(vals) - min(vals)
    tol = cfg_threshold(cfg, "flatline_tolerance")
    if spread < tol:
        return True, window
    return False
```

| Tuning | Start with `flatline_tolerance` 0.05–0.15 °F for zone temp |
| False positives | Very tight spaces with real stable temp; increase tolerance or require longer window |

**Fault codes:** `VAV-C`, `AHU-C`, `BLD-B` — [Fault Codes](../fault-codes/).

---

## 2 — Spread / delta (1 hour)

**Use case:** Poor delta-T, hunting, capacity issue.

```python
from open_fdd.playground.cookbook import cfg_threshold, hour_window_ready, window_rows_1h

def evaluate(row, cfg, prev_row=None, rows=None):
    window = window_rows_1h(row, rows or [])
    if not hour_window_ready(window):
        return False
    vals = [r["temp"] for r in window if r.get("temp") is not None]
    if len(vals) < 2:
        return False
    return (max(vals) - min(vals)) > cfg_threshold(cfg, "max_spread")
```

| Tuning | `max_spread` 2–6 °F depending on equipment |
| False positives | Morning warm-up, large OAT swing |

---

## 3 — Out-of-bounds (rolling avg)

**Use case:** Comfort or equipment limit violations.

```python
from open_fdd.playground.cookbook import cfg_threshold

def evaluate(row, cfg, prev_row=None, rows=None):
    v = row.get("temp_rolling_avg") or row.get("temp")
    if v is None:
        return False
    return v < cfg_threshold(cfg, "bounds_low") or v > cfg_threshold(cfg, "bounds_high")
```

| Tuning | Set bounds per zone type; use rolling avg to debounce spikes |
| False positives | Unoccupied setback if schedule not gated — see recipe 7 |

---

## 4 — Rate of change (per hour)

**Use case:** Runaway heating/cooling, open door, coil valve stuck open.

```python
def evaluate(row, cfg, prev_row=None, rows=None):
    if not prev_row or prev_row.get("temp") is None or row.get("temp") is None:
        return False
    dt_h = (row["ts_ms"] - prev_row["ts_ms"]) / 3_600_000
    if dt_h <= 0:
        return False
    rate = abs(row["temp"] - prev_row["temp"]) / dt_h
    return rate > float(cfg.get("max_temp_per_hour", 5))
```

| False positives | Single bad sample — pair with rolling avg or consecutive hits |

---

## 5 — Deadband / hysteresis

**Use case:** Chattering alarm near setpoint.

```python
def evaluate(row, cfg, prev_row=None, rows=None):
    sp = float(cfg.get("setpoint", 72))
    band = float(cfg.get("deadband", 2))
    v = row.get("temp")
    if v is None:
        return False
    if prev_row and prev_row.get("_latched"):
        # clear inside tighter band
        return abs(v - sp) > band * 1.5
    return abs(v - sp) > band
```

Store latch in row dict only for retroactive paint; for production use cfg-backed state via consecutive sample recipe.

---

## 6 — Setpoint vs measured

**Use case:** VAV discharge temp far from SAT setpoint.

```python
def evaluate(row, cfg, prev_row=None, rows=None, series=None):
    if not series:
        return False
    sat_sp = series.get("SAT_SP", {}).get("current")
    sat = row.get("temp")
    if sat_sp is None or sat is None:
        return False
    return abs(sat - sat_sp) > float(cfg.get("max_deviation", 3))
```

Requires `series_aliases` in rule config for cross-point rules.

---

## 7 — Occupancy schedule gating

**Use case:** Only evaluate during occupied hours.

```python
def evaluate(row, cfg, prev_row=None, rows=None):
    if not cfg.get("occupied", True):  # set via binding metadata or static cfg
        return False
    # ... inner fault logic ...
    return False
```

Prefer binding-level enable flags or schedule tables in `cfg`.

---

## 8 — Consecutive true samples

**Use case:** Debounce transient spikes.

```python
def evaluate(row, cfg, prev_row=None, rows=None):
    need = int(cfg.get("consecutive", 3))
    if not rows or row["row"] < need - 1:
        return False
    for r in rows[row["row"] - need + 1 : row["row"] + 1]:
        if not _inner(r, cfg):
            return False
    return True

def _inner(r, cfg):
    v = r.get("temp")
    return v is not None and v > float(cfg.get("high", 80))
```

---

## 9 — Mark entire lookback window

Return `(True, window_rows)` so the sweep paints every row in the window (retroactive mode).

---

## 10 — Missing data

```python
def evaluate(row, cfg, prev_row=None, rows=None):
    if row.get("temp") is None or row.get("quality") == "bad":
        return True
    return False
```

Pair with comms fault codes — [Sensor quality](../fault-codes/sensor-quality).

---

## Promotion checklist

- [ ] Lint clean in Rule Lab
- [ ] Tested on ≥ 48 h of real building data
- [ ] Thresholds documented in rule `config`
- [ ] Fault code assigned (`VAV-C`, etc.)
- [ ] False positive review with operator
- [ ] Enabled only after binding to correct `fdd_input`
