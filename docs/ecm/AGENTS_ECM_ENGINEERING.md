# AGENTS.md — Open-FDD ECM Engineering

## Mission

Use Open-FDD evidence to populate a human-auditable engineering workbook and run
independent Python benchmark calculations.

## Rules

1. Never invent required project inputs when evidence is available or the human can supply them.
2. Prefer BAS trends, meters, TAB, nameplates, manufacturer data and utility records.
3. Never overwrite workbook formula cells.
4. The Excel workbook remains the human calculation record.
5. Python benchmark functions are an independent referee, not hidden workbook math.
6. Preserve provenance for every AI-populated value.
7. Do not blindly stack interacting ECM savings.
8. Use manufacturer performance curves for stronger chiller/tower estimates.
9. Report assumptions, confidence and readiness with savings.
10. Save a new project workbook and give it to the engineer for review.

## Agent example

```python
from open_fdd.ecm_engineering import ECMJob

job = ECMJob("Building 100")
job.set_global(electric_rate=0.143, area_ft2=140000)

job.add_ecm(
    "static_pressure_reset",
    fan_kw=74.6,
    hours=4200,
    baseline_speed=0.82,
    proposed_speed=0.66,
)

path = job.save("Building_100_Open_FDD_ECMs.xlsx")
```
