# Soft-OPEN 371 T2d — avg(Utf8View) disposition (2026-10-11)

**Tip source (`origin/master` / `sha-b146d4c`):** `history_role_numeric_sql` casts historian roles
via `try_cast(trim(CAST(col AS VARCHAR)) AS DOUBLE)` before AVG/STDDEV/SUM. Unit coverage in
`historian.rs` asserts AVG embeds that cast for sat/mat.

**Operator report:** sidebar `3.5.69+45b362a` — pre-cast tip. Treat as **pin mismatch** under
Product smoke Soft-OPEN gate before claiming a tip product regression.

**Next on tip:** re-pin ACME/hub to `sha-b146d4c` (T2b); re-run Overview/FDD/RCx; if avg(Utf8View)
persists on tip, locate residual raw AVG on uncast columns and add regression. Empty motors /
BAS-vs-web remain T2c (package map vs product join).
