# Wave O — Known bugs / patch train tracker

**Ops pin (Wave N, until O8/O9 tip):** `sha-9072e0b` / **3.5.10** · `multi_tenant=true`  
**O8+O9 tip:** master `764bb17e` / **3.5.11** — GHCR Publish in flight (2026-09-14)  
**O7 open:** PR [#926](https://github.com/bbartling/open-fdd/pull/926) · **3.5.12** Overview site cache

Parent plan: `.cursor/plans/wave_o_known_bugs_patch_ce235993.plan.md`  
Prior Soft-OPEN: [`BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md`](BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md)

## Bake order

O8 → O9 → O10 → O7 → O3 → O1 → O6 → O2 → O4 · **O5 Soft-OPEN only** (IdP/MFA)

| Step | Status | Evidence |
|------|--------|----------|
| O8 hub admin | **MERGED** #925 | `/admin` + `/api/admin/*` · gate 33 |
| O9 site data-model ACL | **MERGED** #925 | site export + session `building_id` ACL |
| O10 full HVAC @300s | NEXT after 3.5.11 pin | private catalog ~38 devices; rusty tip gate MS/TP |
| O7 Overview cache | **PR #926** | silent per-`buildingId` cache |
| O3–O4 | queued | after O10 streams |

## Hygiene

- 0 open PRs after each merge (except the active tip PR)
- Delete feature branches; tip Actions green before Railway re-pin
- Product OT = `openfdd-fieldbus` + rusty-bacnet; bacpypes3 diagnose-only
