---
title: Write your own rule
parent: Rules
nav_order: 7
---

# Write your own rule

Two paths: an ad hoc pandas rule for your own analysis, or a shipped rule (SQL plus its pandas twin).

## Ad hoc (pandas, `CUSTOM-*`)

`compute(df, params, poll_seconds)` returns a boolean mask aligned to the frame's index (the raw fault). The runner applies the confirm time. Ids must start with `CUSTOM-`; canonical rules are never replaced.

```python
import pandas as pd
from open_fdd.rules import run_rule
from open_fdd.rules.cookbook_catalog import CookbookParam
from open_fdd.rules.custom_boilerplate import make_custom_rule
from open_fdd.rules.custom_rules import CUSTOM_RULES

def sat_high(d, p, poll):
    sat = pd.to_numeric(d["discharge_air_temperature"], errors="coerce")
    on = pd.to_numeric(d["supply_fan_operating_status"], errors="coerce").fillna(0) > 0.05
    return sat.notna() & (sat > float(p.get("sat_hi", 23.9))) & on

CUSTOM_RULES.append(make_custom_rule(
    rule_id="CUSTOM-SAT-HIGH", title="SAT high while fan on", compute=sat_high,
    required_roles=["discharge_air_temperature", "supply_fan_operating_status"], equipment_kinds=["ahu"],
    equation="Fan on AND SAT > sat_hi (°C).",
    extra_params=[CookbookParam("sat_hi", "SAT high", "°C", 12.8, 48.9, 0.5, 23.9)]))

idx = pd.date_range("2026-01-05", periods=48, freq="5min", tz="UTC")
df = pd.DataFrame({"discharge_air_temperature": [20.0] * 24 + [27.0] * 24, "supply_fan_operating_status": 1.0}, index=idx)
r = run_rule("CUSTOM-SAT-HIGH", df, params={"confirm_min": 10}, equipment_type="AHU")
print(r.status, r.fault_hours)   # FAULT 1.83
```

A missing required role gives `SKIPPED`, never a guess. To keep a rule, put it in `open_fdd/rules/custom_rules.py`. More examples: `open_fdd/rules/custom_boilerplate.py`.

## Shipped rule (SQL + pandas twin)

1. Follow [Writing SQL rules](../sql-rules.html).
2. Add the pandas twin: a compute function and a `CookbookRule` entry in `open_fdd/rules/cookbook_catalog.py`.
3. Regenerate and check:

```bash
python3 scripts/nf/build_rule_catalog.py
python3 scripts/nf/build_sql_pack.py
python3 scripts/nf/gen_rule_docs.py
python3 scripts/nf/gen_cookbook.py
python -m pytest tests/parity -q
```

The twin must match the SQL on the [parity](parity.html) dataset, or the difference must be listed there with its reason.
