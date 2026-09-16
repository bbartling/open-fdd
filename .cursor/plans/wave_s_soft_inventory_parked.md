---
name: Wave Soft Inventory Parked
overview: Soft-OPEN leftovers after Wave R — track only; no product tip. Includes generic N-building historian small-file scale Soft.
todos:
  - id: stage-c
    content: IdP/MFA/SKU commercial Stage C
    status: pending
  - id: util-interval
    content: UTIL-INTERVAL missing utility_interval Soft
    status: pending
  - id: ingest-reject
    content: ACME ingest_reject count Soft + honesty
    status: pending
  - id: kali
    content: Kali ZAP AF + MQTT ACL staging
    status: pending
  - id: tenant-path
    content: Optional tenants/{tid}/ migrate
    status: pending
  - id: historian-n-building-scale
    content: "N buildings CSV+MQTT: offline H4 now; runtime compaction coordinator + file/GiB budgets Soft later"
    status: pending
  - id: admin-capacity-gauges
    content: "Soft: Admin capacity gauges — volume df + cgroup mem + historian bytes/small-files vs size_gib (not host RAM)"
    status: pending
  - id: railway-capacity-stress
    content: "S5a harness: capacity NDJSON sampler + report during Railway hub stress; gate 24 optional pressure"
    status: completed
isProject: false
---

# Soft-OPEN inventory (parked)

**Parent:** [wave_soft_park_480c17e1.plan.md](wave_soft_park_480c17e1.plan.md)  
**Tracker:** [docs/operations/BUG_REPORT_WAVE_P.md](docs/operations/BUG_REPORT_WAVE_P.md)

Do **not** tip these in the Data Model TTL wave. Exit Soft ceiling remains ≤ Stage C.

| ID | Note |
|----|------|
| stage-c-idp-mfa-sku | Commercial ADR |
| util-interval | Live flood Soft-ignored |
| r6-ingest-reject | Count-only; no dead-letter dump API |
| kali-zap-af / p2c-mqtt-acl | Other box |
| wave-o1-tenant-path-migrate | Optional ops migrate |
| **historian-n-building-scale** | Generic: many tiny Parquet parts × N buildings (CSV and/or MQTT) → DF RAM spike. **Now:** spill + `OPENFDD_QUERY_MEMORY_MB` + offline H4 between query windows; building-scoped jobs. **Later Soft tip:** runtime compaction coordinator (serialize with DF reads), small-file health, tenant/building GiB+retain budgets. No FDD SQL chunking; no site-named special cases. |
| **admin-capacity-gauges** | Hub-admin **capacity** strip (Admin and/or Operations) — not a host vanity dashboard. Prefer: (1) **volume** used/total for `/workspace` (Railway disk / subscription signal), (2) **cgroup** container memory used/limit (not host `/proc/meminfo` — shared nodes lie), (3) historian **bytes + small_file_count** vs Admin `size_gib`/retain. Optional sparkline of last N samples. Wire existing `GET /api/host/stats` + data-management health; fix stats to report cgroup+`df` honestly. Do **not** chart shared-host 300+ GiB RAM as “upgrade Railway.” |
| **railway-capacity-stress** | Harness (S5a): sample health/host/historian during `run_railway_hub_stress.sh`; `$ART/capacity_samples.ndjson` + `capacity_report.json`; optional gate `24_capacity_pressure` building-scoped FDD on max-small-files building. HARD fail on health death / 5xx; SOFT warn on small-file explosion / volume>80%. See parent Soft park § S5 stress. |
