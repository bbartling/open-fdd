---
title: Wave-NF delivery gates
nav_exclude: true
---

# Wave-NF 4.0 phased delivery gates

Machine-readable status: [`wave_nf_status.json`](wave_nf_status.json).
Check: `python3 scripts/nf/check_wave_nf_status.py`.

Labels mean different things. **Implemented** is code on this branch.
**Tested** is recorded gate evidence. **Deployed** is a published sha pinned
on the hub. **Qualified** is the N12 matrix plus a bounded read-only NF
SoftOPEN pilot. This file does not mark any item deployed or qualified.

Offline fixture acceptance (`cargo test -p openfdd-central fixture_acceptance`)
parses local GetData JSON and upserts the Timescale `SampleRow` projection.
It does not open a portal client. The bounded real read-only NF SoftOPEN
pilot stays **SoftOPEN defer —**.

## Phase 0 — Foundations

Entry: product boundary written down (central, web, Timescale, optional MCP).
Exit: N0 labels exist and M0 records Wave-NF without treating an ADR as qualification.
Now: ADR-011 is accepted direction (M2). N0 and the MILESTONES section are still open.

## Phase 1 — Archive

Entry: OT freeze is a real tree, or an unqualified snapshot that says what is missing.
Exit: digest prune keeps the snapshot; an isolated restore boot is proven; fieldbus leaves the default workspace only at the split gate.
Now: `archive/ot-edge/unqualified-cdaa4f15/` is on the branch and the snapshot verifier runs in CI. Restore boot and workspace removal stay **SoftOPEN defer —**.

## Phase 2 — Security

Entry: tenant filter, fail-closed secrets, no OAuth redirects, byte and time bounds, typed errors.
Exit: those checks are tested, plus DNS-at-connect pinning and hot credential reload.
Now: N2 on this branch is implemented and covered by unit tests. DNS pinning and hot reload stay **SoftOPEN defer —**.

## Phase 3 — Model

Entry: a source-neutral committed revision. Roles come from explicit `provider_point_id` or SPARQL bindings.
Exit: ingest plans are scoped. Display names do not invent roles.
Now: the committed model and scoped SPARQL ingest plans are unit-tested. Cross-replica invalidation, a durable multi-process model store, and in-flight SPARQL cancel stay **SoftOPEN defer —**. The Model UI stays **SoftOPEN defer —**.

## Phase 4 — Provider contract

Entry: one history capability. Ace stays visibly NotImplemented.
Exit: drivers implement that capability; NF history remains `GET /api/v1/point/data`.
Now: the NF driver and Ace stub exist. History fetch is still the concrete driver, not the shared trait. Live portal calls are outside CI.

## Phase 5 — Durable ingest

Entry: per-device completed-hour jobs, receipts, checkpoints, catch-up.
Exit: source timestamps, units, and quality survive into the historian row; partial pages are not success; gaps are explicit.
Now: N5 and N6 code is tested, including the offline fixture matrix. Sample upsert and the job receipt are still separate writes. The coverage ledger UI stays **SoftOPEN defer —**. NF update-log HTTP 403 means reconciliation is bounded, not gapless.

## Phase 6 — Scale

Entry: one shared Postgres queue with leases and fencing. No Kubernetes requirement.
Exit: 2–4 workers pass fencing, then an optional capped autoscaler only after that proof.
Now: claim uses `SKIP LOCKED` and a fencing token. The fixture suite runs 2–4 workers against the in-memory queue. Replica processes and the autoscaler stay **SoftOPEN defer —**.

## Phase 7 — Weather

Entry: Open-Meteo adapter behind the same provider contract.
Exit: a contractor conformance fixture, still with no live NF call mixed in.
Now: **SoftOPEN defer —**.

## Phase 8 — API and MCP

Entry: scoped reads for jobs, receipts, and gaps.
Exit: OT tool discovery is off the normal 4.0 path, and legacy OT Grok tips are retired only with that cut.
Now: MCP exposes provider health and sites. Jobs, receipts, gaps, and tip retirement stay **SoftOPEN defer —**.

## Phase 9 — SPA

Entry: Operations opens on Providers.
Exit: Sites, Model, and the window ledger match the committed model. Analytics stay source-neutral.
Now: the Providers panel is the default. The rest of N11 stays **SoftOPEN defer —**.

## Phase 10 — Evidence

Entry: offline fixtures before any portal traffic.
Exit: exact source-to-row sets; units, timestamps, and quality preserved; partial history; crash and restart idempotency; long-outage catch-up; late backloads; 2–4 worker fencing; HTTP 429 backoff; DB reconnect; bounded memory. Then a bounded read-only NF SoftOPEN pilot and a published-SPA regression.
Now: the fixture half is in CI. **SoftOPEN defer —** the bounded real read-only NF SoftOPEN pilot and the published-SPA regression.

## Phase 11 — Release

Entry: Phase 10 fixture evidence is green and the status file is truthful.
Exit: VERSION 4.0.0 images for central and web, newest-by-created pin, Railway re-pin, no fieldbus image, Grok proof on that sha, ACME only after the pilot is stable.
Now: this gate document and `wave_nf_status.json` are the N13 record. Nothing is deployed. Nothing is qualified.
