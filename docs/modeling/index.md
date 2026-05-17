---
title: Column maps (optional ontology keys)
nav_order: 7
has_children: false
---

# Column maps and optional ontology keys

**`open_fdd.engine`** does not load Brick TTL or BACnet metadata. You pass **`column_map`** at **`RuleRunner.run`** time.

---

## Typical patterns

1. **Simple dict** — `{"SAT": "RTU_11_DA_T(°F)"}` matches logical names in your YAML `inputs`.
2. **Manifest YAML** — **`ManifestColumnMapResolver`** / **`load_column_map_manifest`**.
3. **Optional ontology fields** — per-input **`brick:`**, **`haystack:`**, **`dbo:`**, **`223p:`** in rule YAML; keys in **`column_map`** must match those strings if you use them.

Example rules under **`examples/AHU/rules/`** often include **`brick:`** for readability. That is a **convention**, not a package requirement.

---

## See also

- [Column map resolvers](../column_map_resolvers)
- [Expression rule cookbook](../expression_rule_cookbook)
- **`examples/column_map_resolver_workshop/`**
