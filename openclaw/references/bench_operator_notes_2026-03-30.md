# Open-FDD bench operator notes — 2026-03-30

These are durable bench/testing notes worth keeping in-repo for future OpenClaw or manual operator passes.

## 1) Use the backend HTTP log route for container troubleshooting

When the local Docker socket is unavailable from the operator host/session, use the backend analytics routes instead of assuming logs are inaccessible.

Useful routes:
- `GET /analytics/system/containers`
- `GET /analytics/system/containers/{container_ref}/logs?tail=20&follow=0`
- `GET /analytics/system/host`

This worked on the active bench and was enough to verify:
- `openfdd_fdd_loop` was writing fault samples
- `openfdd_bacnet_scraper` health/warnings
- `openfdd_host_stats` warning behavior

## 2) Current bench signal split: export/logged writes can be healthy while active/state stays empty

Recent bench evidence showed all of the following can be true at once:
- `GET /download/faults?site_id=<UUID>` returns rows
- `openfdd_fdd_loop` logs `FDD run OK: <N> fault samples written`
- `GET /faults/active?site_id=<UUID>` still returns `[]`
- `GET /faults/state?site_id=<UUID>` still returns `[]`

That means issue triage should distinguish:
- fault calculation/writing/export health
- versus active/state visibility, timing, or retention semantics

Do not collapse those into a single broad "FDD emitted nothing" diagnosis.

## 3) BACnet scraper warnings must be cross-checked against direct KG-backed reads

A scraper warning alone is not enough to claim the modeled BACnet path is broken.

Recommended operator move:
1. pull modeled devices/objects from the current knowledge graph
2. read representative points directly against the DIY BACnet server on `:8080`
3. compare the direct read result to scraper/log behavior

On the current bench, this was important because:
- direct KG-backed reads for modeled devices `3456789` and `3456790` succeeded
- earlier scraper warnings involved an extra/stale-looking `device,34567` path that was not part of the current modeled device inventory
- later scraper passes cleaned up to `2 devices / 23 points / 0 errors`

## 4) Data-model robustness is promising, but discovery/tooling still need caution

Current bench evidence supports confidence in:
- clean graph shape (`orphan_blank_nodes=0`)
- modeled BACnet devices visible in the graph
- direct KG-backed reads working on representative points

But do not overstate readiness yet:
- UI BACnet discovery may still be mixed on some runs
- bench harnesses can fail due to local artifact/report-path assumptions instead of true product regressions
- modeling workflows should be judged using both backend graph checks and direct BACnet proof, not only a single Selenium result

## 5) Public LLM workflow prompt should be conservative for real jobs

Before using the published copy/paste LLM workflow on a live HVAC job, bias toward:
- preserving exported BACnet identity exactly
- not inventing devices/equipment/topology
- preferring `null` / `polling=false` when uncertain
- human/operator review before import

A public docs issue was opened to tighten that prompt for real-job use.
