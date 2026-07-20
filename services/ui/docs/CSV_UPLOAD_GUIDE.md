# CSV upload guide

## Single upload

Sidebar → **Upload CSV** → one equipment ID → wide-format history.

## Multi upload

Sidebar → **Multi CSV upload** → select multiple files.

For each file:

1. App profiles wide vs long format
2. Set equipment ID (defaults from filename)
3. Choose **wide** or **long** normalization
4. Assign site/building IDs in sidebar

Supports:

- One CSV per equipment (wide)
- One wide building CSV with many point columns
- Long/tidy CSV with `equipment_id`, `point_name`, `timestamp`, `value`

## Validation

`validate_dataframe()` reports empty data, missing datetime index, duplicate timestamps.

## Role mapping

After load, use **Role Mapping** or **Site Mapping** tabs to assign cookbook roles.
