# Open-FDD pandas parity (App 19)

App 19 implements the **[Pandas FDD Cookbook](https://bbartling.github.io/open-fdd/rules/cookbook/pandas-cookbook.html)** offline. Open-FDD edge runs **Rust + DataFusion SQL** — this app is the analyst notebook twin for RCx deliverables.

---

## Parity rules

| Concept | Open-FDD / cookbook | App 19 |
| --- | --- | --- |
| Poll interval | Historian sample period | `manifest.json` → `poll_seconds` |
| Fault confirm | Default **300 s** | `confirm_seconds // poll_seconds` consecutive True |
| Raw vs confirmed | `fault_raw` → `fault_confirmed` | Same column naming in engines |
| Prerequisites | `macro_fan_proven_on`, override suppression | Mirror in pandas before raw mask |
| Rollup | SQL window sums | `mask.sum() * poll_seconds / 60` minutes |
| Point keys | Haystack / Open-FDD sanitized keys | `point_role` + equip folder |

---

## Shared helpers (copy from cookbook)

Implement once per engine module or import from shared util:

```python
def norm_cmd(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    return np.where(s > 1.0, s / 100.0, s)

def confirm_fault(raw, poll_seconds, confirm_seconds=300):
    rows = max(1, int(np.ceil(confirm_seconds / max(poll_seconds, 1))))
    groups = (raw != raw.shift()).cumsum()
    streak = raw.groupby(groups).cumcount() + 1
    return raw.fillna(False) & (streak >= rows)
```

---

## SQL export (optional)

When a rule stabilizes, add SQL twin under `fdd_app/backend/docs/` following `economizer_fdd_rules.sql`:

- Parameterize `@poll_seconds`, `@confirm_samples`
- Cross-check against pandas on same CSV window

Reference: [DataFusion SQL cookbook](https://bbartling.github.io/open-fdd/rules/cookbook/datafusion-sql-cookbook.html)

---

## Taxonomy & metadata

- [Public FDD taxonomy](https://bbartling.github.io/open-fdd/rules/cookbook/public-fdd-taxonomy.html)
- [P0 rule catalog](https://bbartling.github.io/open-fdd/rules/cookbook/p0-rule-catalog.html)
- [Rule documentation template](https://bbartling.github.io/open-fdd/rules/cookbook/rule-documentation-template.html)

When adding a rule, record: rule id, confirm seconds, prerequisites, columns used, page id.

### Implemented rules (economizer engine — reference example)

These rules ship in the template; point columns come from each site's mapping JSON / `columns.csv`.

| Rule / metric | Module | Weather source | Notes |
| --- | --- | --- | --- |
| Economizer OK | `economizer_fdd_engine.py` | Open-Meteo OAT + dew point | DP &lt; 60°F, OAT 35–72°F (tunable) |
| ECON-2 | same | Open-Meteo | OA damper low when econ OK |
| NOT_ECONOMIZING | same | Open-Meteo | Mechanical cooling when econ favorable |
| MECH_COOLING | same | Open-Meteo | CHW active when OAT bins favor free cool |
| Free-cool opportunity | `generate_dashboard.py` | Open-Meteo | AHU + chiller hours rollup |
| Sensor QA (SV-*) | `sensor_qa_engine.py` | BAS + reference | Per-AHU validation |

Analyst tunables for econ rules: `dashboard_params.py` → `economizer_engine_params()`.

---

## Parity testing workflow

1. Slice CSV to one AHU / one week
2. Run pandas engine → fault hour total
3. (Optional) Run Open-FDD SQL on same import
4. Document ± tolerance in test or checkpoint notes

Gap matrix: [Open-FDD gap matrix](https://bbartling.github.io/open-fdd/rules/cookbook/gap-matrix.html)
