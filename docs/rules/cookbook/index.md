---
title: Rule Cookbook
parent: DataFusion SQL Rules
nav_order: 0
has_children: true
permalink: /rules/cookbook/
---

# HVAC FDD Rule Cookbook

Production-ready supervisory fault detection for BACnet/Haystack sites. Open-FDD runs **Rust + Apache Arrow + DataFusion SQL** on the edge. Rules bind to **semantic FDD inputs** from your assignment graph — never hardcode device instance numbers or private IPs.

## Two cookbooks — same rules, two runtimes

| Cookbook | Runtime | Use when |
|----------|---------|----------|
| [**DataFusion SQL**](datafusion-sql-cookbook.html) | **Open-FDD edge** | Live historian, `/sql-fdd` tab, API `test-sql`, confirmation engine |
| [**Pandas**](pandas-cookbook.html) | **Outside Open-FDD** | CSV exports, notebooks, RCx studies, parity checks, training |

Every rule in the SQL cookbook has a **matching Pandas section** with the same fault logic. Pandas is maintained for analyst workflows **outside** the GHCR edge image — it is not part of the Open-FDD runtime.

## Default fault delay

All rules assume **`confirmation_seconds: 300`** (5 minutes) before a confirmed fault latches. Adjust per rule in the SQL FDD workbench or API — see the [confirmation section](datafusion-sql-cookbook.html#fault-confirmation-delay-default-5-minutes) in the SQL cookbook.

## Quick start

1. **Assignments** — bind driver points → Haystack → FDD inputs ([modeling guide]({{ site.baseurl }}/modeling/assignments.html))
2. **Plots** — confirm historian rows and column names
3. **SQL FDD Rules** (`/sql-fdd`) — paste SQL, **Format SQL**, **Test** with `confirmation_seconds`, then **Activate** (integrator)
4. **Validation** (`/live-fdd-validation`) — end-to-end BACnet → historian → SQL → fault overlay

## API quick test

```bash
curl -s -X POST http://127.0.0.1:8080/api/fdd-rules/RULE_ID/test-sql \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"sql":"<SELECT ... fault_raw>","confirmation_seconds":300}' | jq '.ok, .engine'
```

## Safety (edge)

- **SELECT only** — DDL/DML rejected
- Every rule must expose **`fault_raw`** (boolean) for the confirmation engine
- Integrator JWT required to **activate** rules
