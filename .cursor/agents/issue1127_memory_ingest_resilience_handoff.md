# Cursor handoff: issue 1127 memory and ingest resilience

Published audit and acceptance criteria: [issue #1127 comment](https://github.com/bbartling/open-fdd/issues/1127#issuecomment-5981855374). Root verified the posted body against the reviewed local draft. Implementation remains pending.

Date: 2026-10-04. Requested review: GPT-6.1 Sol ultra. Planning only.

Read [the full plan](../plans/issue1127_memory_ingest_resilience_sol61_20261004.plan.md) before implementation. Incident: [GitHub #1127](https://github.com/bbartling/open-fdd/issues/1127), central 3.5.64 / `4251505cdbe9cadcbbca214ec7cb3d4b5ffaf034`. Fetched master during audit: `5591410a5ae2393748898c78b5c86eee60af3991`; relevant memory/ingest paths are unchanged. Locked DataFusion 55.1.0, Arrow/Parquet 59.3.0, Tokio 1.53.1.

## Current verdict

**Cause UNKNOWN; memory pressure is strongly supported.** Read-only Railway history shows first surge from 1.16 GB to 17.67 GB before restart 1 and usage near/exactly 24 GB for several samples before restart 2. Recorded service limit is 24,000,000,000 bytes. These 30-second samples cannot identify a function or exact death instant. Preserve platform exit/OOM evidence before reclassifying to confirmed OOM. App/web logs have fresh starts and 502s but no panic, OOM or exit status. Deployment healthcheck success was a startup check. Curated evidence: `reports/issue1127_memory_audit_20261004/`. Live SSH found host RAM about 346.5 GB but container ceiling 24 GB and swap disabled; zero OOM counters/current peak below 1 GB belong to the revived cgroup and cannot classify the earlier deaths.

## First implementation concerns

1. `fdd_sql/historian.rs:36–55` allocates a fresh pool per context. Introduce one aggregate pool/runtime with isolated catalogs/providers; route the series bare session at `edge/fdd/registry_api.rs:852` through it. A shared pool still does not track every Arrow/JSON/import/cache allocation. Wire the currently unused `historian_session_config_from_env` tuning helper into actual production SessionConfig, with CPU/memory clamping; prove effective values.
2. `routes.rs:3301` times out a blocking JoinHandle, then Actions finishes. The worker can keep executing/publishing. Move reservations into real workers, supervise cancellation/termination, and make Actions a record rather than the concurrency authority. Include scheduler workers (`afdd_scheduler.rs:262`) and request disconnect/shutdown.
3. `run_sql` (`fdd_sql/session.rs:298`) collects Arrow and constructs full JSON. Stream bulk results and impose row+byte budgets for interactive results/serialization. Preserve fault correctness, rolling windows and first/last plot span.
4. Import handler (`routes.rs:3638–3669`) buffers and fully decompresses the package peek before admission, then decompresses again. Admit before staging, peek only bounded manifest, extract once, and keep the permit inside the worker. Cache paths also concatenate/clones full results.
5. Ingest specialist found full committed envelopes retained in RAM (`state.rs:513,537`), independent growing seen IDs (`ingest.rs:352`), unbounded events/writer queues and per-scope buffers. Bound global bytes; compact committed records to identity/digest/provenance; use durable replay indexes/tombstones. Never prune uncommitted rows or replay keys casually.
6. MQTT client enqueue/broker transport ACK is insufficient for canonical durability. Correct persistent/manual ACK and application commit acknowledgement/spool lifecycle. Preserve local HTTP 200+Committed+positive persisted_rows; 202/503 leaves the edge spool intact.

## Implementation sequence

Capture incident evidence and cheap resource/task telemetry → tested cgroup-aware discovery and explicit protected envelopes → shared compute runtime plus real global/class admission → cooperative cancellation, bounded materialization/cache/imports → durable ingest queue/receipt/ACK work → adaptive pressure/deferred background work → isolated combined-load qualification → controlled candidate smoke. Use bounded PRs and an isolated worktree; coordinate with existing Cursor ownership. A process split for analytics workers is an optional later OS isolation boundary.

Bootstrap must use actual process cgroups and visible ancestor constraints rather than host RAM/plan tier; keep RSS/cgroup/file-cache/swap distinctions. On a host with insufficient compute headroom, protect ingest/control and reject expensive jobs explicitly. Calibrate reserves from measured workloads; no universal safe percentages. Existing Pi 3 fieldbus-only guidance remains until representative device tests demonstrate additional capability. The user's hardware ranges are examples, not Railway facts or throughput claims.

Read-only live settings also show 512 MiB query memory with spill, unset batch/partition tuning, and `OPENFDD_PARQUET_FLUSH_ROWS=1` despite a 300-second flush timer. The row trigger immediately flushes nonempty batches. A metadata-only scan counted **72,267 Parquet files / 419,411,483 compressed bytes**, with **71,935 smaller than 64 KiB**, across `/workspace/openfdd`; this includes possible caches/results, not just canonical history. Measure partition-aware metadata/planning cost and real compaction scheduling. Source calls show explicit route/CLI compaction, without proof of an automatic runtime schedule. Retuning must preserve local committed ACK and replay behavior; fragmentation is not a proven crash cause.

## Acceptance that cannot be substituted

Correct output alone does not prove memory release. A timeout response alone does not prove cancellation. Building SessionBook flags and deleted/reclaimed Actions do not prove worker termination.

Use deterministic real-plan cancellation tests that assert worker completion, no late publication/checkpoint movement, returned pool reservations and released materialization ownership. Verify constrained spill output and cleanup separately. Then run isolated combined compute/import/compaction/continuous ingest tests with failure/restart boundaries, proving unique canonical rows, exact replay dedupe, retained spool while pending, eventual drain, measured memory envelope and ingest freshness. Sample cgroup/RSS/events and process start identity, and assert actual rule outputs. Existing capacity/flood HTTP success does not establish those properties. Test cgroup discovery through fixtures before claiming portable sizing.

No product edits, build, stress, deployment, limit change, public post or functional test was performed by this review. Parent owns logs, platform metrics, curated evidence and GitHub publication. This handoff and its new plan are the only files this reviewer owns; leave active plans, product files, credentials and running workloads under their current owners.
