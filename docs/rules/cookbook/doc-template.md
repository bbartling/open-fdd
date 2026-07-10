---
title: Rule documentation template
parent: Rule Cookbook
nav_order: 10
---

# Rule documentation template

Copy this structure for every new rule in **both** [DataFusion SQL](datafusion-sql-cookbook.html) and [Pandas](pandas-cookbook.html) cookbooks.

**Maintainer hard rule:** Never delete or shorten existing cookbook rule sections to “make room.” Expression cookbooks only grow. When adding rules (e.g. PID-HUNT-1), keep FC4, CTRL-2, and all prior content intact.

---

## `{RULE_ID}` — {Title}

### Metadata

| Field | Value |
|-------|-------|
| **id** | `{RULE_ID}` |
| **taxonomy_path** | `{family}.{equipment_class}.{slug}` |
| **equipment_class** | `ahu` \| `vav` \| `plant.chw` \| … |
| **severity** | 1–4 |
| **priority** | P0–P3 |
| **confirmation_seconds** | default 300 (site-adjustable) |

**required_points:** `point_a`, `point_b`  
**optional_points:** `point_c`  
**prerequisites:** `macro.fan_proven_on`, …

### Description

One paragraph — what condition is detected.

### Intent

Why this matters for energy, comfort, or equipment life (public literature reference).

### Assumptions

- Poll interval ~60 s
- Points assigned per Haystack FDD input graph
- …

### Tunables

| Parameter | Default | Unit | Notes |
|-----------|---------|------|-------|
| `threshold_x` | 5.0 | °F | site-adjustable |

### Suppression logic

When the rule must **not** run (override, startup delay, unoccupied, bad sensor).

### False-positive risks

- …

### False-negative risks

- …

### Plots to review

- SAT vs SAT SP over 24 h
- Fan cmd/status overlay
- …

### Detection — DataFusion SQL

```sql
-- confirmation_seconds: 300
SELECT … AS fault_raw FROM telemetry_pivot …
```

### Detection — Pandas

```python
FAULT_CONFIRM_SECONDS = 300
mask = …
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

### Evidence fields

`timestamp`, `equipment_id`, …

### Root cause candidates

- Hypothesis 1 (not a diagnosis)
- Hypothesis 2

### Recommended action

Operator / RCx next step.

### Validation scenarios

| Scenario | Expected `fault_raw` |
|----------|---------------------|
| normal | false |
| obvious_fault | true (after confirm) |
| borderline | false or true per tunable doc |
| missing_point | false |
| bad_sensor | false (gated) |

### Unit tests (offline)

```python
def test_reset1_obvious_fault():
    df = load_fixture("reset1_obvious.jsonl")
    out = run_rule_reset1(df)
    assert out["fault_confirmed"].any()
```

---

## Quick reference — standard metadata YAML

```yaml
id: EXAMPLE-1
title: Example rule
taxonomy_path: control.loop.ahu.example
equipment_class: ahu
required_points: [sat, sat_sp]
optional_points: [occ_mode]
prerequisites: [macro.fan_proven_on]
confirmation_strategy: { seconds: 300 }
thresholds:
  err_max: { default: 5.0, unit: deltaF, site_adjustable: true }
severity: 2
priority: P1
validation_tests: [normal, obvious_fault, borderline, missing_point, bad_sensor]
```

See [rule schema](rule-schema.html) for the full field dictionary.
