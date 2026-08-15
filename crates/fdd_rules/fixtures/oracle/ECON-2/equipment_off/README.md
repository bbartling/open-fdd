# Fixture — `ECON-2` / `equipment_off`

Fan off with damper 0.55 and OAT 70°F. Pandas `econ2()` has no fan in the equation, but `run_rule` applies the `fan_running` gate, so this golden stays no-fault. SQL ECON-2 matches the equation (no fan AND).
