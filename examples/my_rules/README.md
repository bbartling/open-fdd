# my_rules — Your fault rules for your deployment

This folder holds **your** YAML fault rules. Copy it to your desktop (or anywhere), rename it if you like, and customize it for your own BAS data. The repo clone is only for installing open-fdd from source; future versions will be on PyPI.

## Brick-driven workflow

When using `brick_model.ttl` and `run_all_rules_brick.py`:

1. **Validate first**: `python examples/validate_data_model.py`
2. **Run faults**: `python examples/run_all_rules_brick.py`

Rules with `equipment_type: [VAV_AHU]` (or `[AHU, VAV_AHU]`) only run when the Brick model declares that equipment type via `ofdd:equipmentType`.

## Rules in this folder

| Rule | Type | equipment_type |
|------|------|----------------|
| sensor_bounds.yaml | bounds | (all) |
| sensor_flatline.yaml | flatline | (all) |
| ahu_fc1.yaml | expression | VAV_AHU |
| ahu_fc2.yaml | expression | AHU, VAV_AHU |
| ahu_fc3.yaml | expression | AHU, VAV_AHU |
| ahu_fc4.yaml | hunting | AHU, VAV_AHU |

Add your own rules or modify the existing ones to match your equipment and column names.
