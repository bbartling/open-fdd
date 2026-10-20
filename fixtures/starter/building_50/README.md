# Building 50 starter pack

Canonical BPS seed (`practice/datasets/building_50`). History is the TADCO-derived
role CSVs (5-minute, 2026-03-16 through 2026-07-17, six equipment, 41 points).

The CSVs are stored gzipped. Raw text is about 15 MB; gzip level 9 is about
1.3 MB. A fresh central image can carry the pack and seed Timescale on an empty
database without a 300 MB package zip. Central never overwrites a database that
already has `sample` rows.

The in-image seed writes the same `seed_meta` marker as
`scripts/timescale/auto_seed.py` (`building50_seed` = `ok`). Either path seeing
that marker, or any `sample` row, leaves the historian alone. A wipe is the
one-shot `OPENFDD_RESET_DB` token plus `OPENFDD_ALLOW_DESTRUCTIVE_DB=1`
(`scripts/timescale/purge_historian.py` or central startup). Synthetic stress
data is not part of this pack and is not loaded on boot.

Site id in this product is `BUILDING_50` (BPS used `building-50`). Roles are
stored as SQL names from `sql/fdd/role_map.json` (`duct-static-pressure` →
`duct_static`).
