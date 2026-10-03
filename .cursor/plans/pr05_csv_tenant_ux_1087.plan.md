---
name: "PR-05 CSV tenant UX #1087"
overview: "Account-scoped CSV jobs/buildings CRUD + tenant UX; depends on PR-01 isolation."
todos:
  - id: pr05-wait-pr01
    content: "Block start until PR-01 merged (isolation prerequisite)"
    status: pending
  - id: pr05-api-jobs
    content: "Account/tenant-scoped create/list/delete jobs-buildings APIs"
    status: pending
  - id: pr05-cascade
    content: "User delete cascades owned jobs/buildings/artifacts (policy-safe)"
    status: pending
  - id: pr05-spa
    content: "Operations UI tenant dropdown CRUD; remove hard URL links"
    status: pending
  - id: pr05-tests
    content: "Unit/integration tests for ownership + cascade"
    status: pending
  - id: pr05-pr-ci
    content: "Open PR; muse-spark watch; merge; close #1087"
    status: pending
isProject: false
---

# PR-05 — CSV users tenant UX (#1087)

**Parent:** [`patch_all_open_issues_master.plan.md`](patch_all_open_issues_master.plan.md)  
**Depends on:** PR-01  
**Branch:** `feat/csv-tenant-jobs-ux-1087`  
**Closes:** #1087  
**Models:** design=`claude-opus-5-thinking-high` · code=`composer-2.5-fast` · critique=`claude-sonnet-5-5-high` · CI watch=`muse-spark-1.3-high`

## Goal

CSV-first users manage many jobs/buildings under their account+tenant; admin can manage; MQTTS remains admin-setup; Operations UI has no brittle hard-coded URL links.

## Exact homes (research)

- `frontend/web/src/pages/AdminPage.tsx` — comma-separated tenant input (~L244); hard `<a href="/operations?view=sites">` (~L374–375) → replace with in-app nav
- `admin_delete_user` in `routes.rs` (~L872) — today only `store.remove(&username)`; **no cascade**
- Also: `admin_upsert_user` (~798), `admin_delete_tenant` (~949); `tenantApi.ts`; package deletion in `edge/src/csv_ingest/package.rs`

## Scope

- Create / manage / delete jobs-buildings via CSV/ZIP under account+tenant
- Cascade delete user → owned jobs/packages/historian — **dry-run + confirm**; negative test that cascade cannot delete another tenant
- Tenant dropdown CRUD (not comma text)
- Remove hard Operations URL links
- Audit gaps → follow-up issues rather than unbounded PR growth
- MQTTS remains admin-setup

## Local verify

```bash
cargo test -p openfdd-central
cd frontend/web && npm test -- --run && npm run typecheck
bash scripts/nightly-ot-bench/26_wave_l_tenant_budgets.sh
bash scripts/nightly-ot-bench/33_wave_o_admin_datamodel_acl.sh
```

Manual: joel upload → delete job → artifacts gone for that building only; foreign tenant untouched.
