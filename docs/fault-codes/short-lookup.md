# Fault code short descriptions

Stable lookup for pie charts, tables, and RCx reports. Titles match `workspace/api/openfdd_bridge/fault_catalog.py`.

| Code | Short description |
|------|-------------------|
| AHU-A | Supply fan performance degradation |
| AHU-B | Simultaneous heating and cooling |
| AHU-C | Supply air temperature sensor fault |
| AHU-D | Mixed-air temperature inconsistent with OAT/RAT |
| AHU-E | Economizer not economizing |
| AHU-F | Damper/valve command vs feedback mismatch |
| AHU-G | PID hunting / excessive control oscillation |
| VAV-A | Reheat active during cooling demand |
| VAV-B | Airflow not meeting setpoint |
| VAV-C | Zone temperature sensor fault |
| VAV-D | Damper command vs airflow mismatch |
| VAV-E | Rogue zone (chronic reheat/overcooling) |
| VAV-F | VAV actuator PID hunting |
| BLD-A | Whole-building energy deviation |
| BLD-B | Outdoor-air temperature sensor fault |
| BLD-C | Equipment running outside occupancy schedule |
| BLD-D | Point data dropout (stale points) |
| RTU-A | Supply fan performance degradation |
| RTU-B | Simultaneous heating and cooling |
| RTU-C | Discharge air temperature sensor fault |
| RTU-D | Damper/valve command vs feedback mismatch |
| RTU-E | Cooling capacity PID hunting |
| CH-G | Pump / variable-speed PID hunting |

Full catalog: [index.md](index.md) and live `GET /api/faults/catalog` on Edge.

Python mirror: `portfolio/central/fault_code_lookup.py` (RCx Central Dash).
