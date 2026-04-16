---
title: Danger zone
parent: How-to guides
nav_order: 41
nav_exclude: true
---

# Danger zone

Sharp edges when using **`open_fdd`** as a library.

---

## 1. Trust rule YAML like code

Only load rules from **trusted** paths. Expression rules run **`pd.eval`** / restricted **`eval`** over your DataFrame columns—do not merge untrusted YAML into production without review.

---

## 2. Column map mistakes look like “silent” skips

With **`skip_missing_columns=True`** (default), a bad **`column_map`** can cause a rule to be **skipped** with a warning instead of raising. Use **`input_validation='strict'`** and **`skip_missing_columns=False`** in CI when you want failures loud.

---

## 3. Units and scaling

Expressions use raw column values. **0–1 vs 0–100** command scaling is your responsibility unless you call **`normalize_cmd(...)`** in the expression (see [Expression rule cookbook](expression_rule_cookbook#signal-scaling-0--1-fraction-vs-0--100-percent)).

---

## 4. Operational data deletion

Deleting rows in **your** warehouse or database is outside this package. If you deploy a full platform, data-retention and CRUD delete semantics are documented in **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack/tree/main/docs)**.
