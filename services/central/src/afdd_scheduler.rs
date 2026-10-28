//! Continuous AFDD scheduler runtime owned by Central.
//!
//! Scheduled cycles and operator-triggered run-now cycles share `execute_cycle`.
//! A per-scope Tokio mutex prevents overlapping AFDD runs for the same building,
//! while failures are recorded without advancing the persisted checkpoint.
//!
//! Mode remains deployment/env-owned. Interval, wall-clock local time, and rolling
//! lookback may be updated via authenticated `POST /api/afdd/scheduler/config`.
//! The timer upserts only the cycle window. Unbounded "update all" is rejected.
//! An explicit historical range is `POST /api/afdd/scheduler/backfill`.

use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration as StdDuration;

use anyhow::{Context, Result};
use axum::extract::{Extension, Query};
use axum::middleware;
use axum::routing::{get, post};
use axum::{Json, Router};
use chrono::{DateTime, Duration, Utc};
use dashmap::DashMap;
use fdd_store::{
    apply_scheduler_config_update, lookback_equals_schedule_cadence, next_due_at,
    parse_backfill_request, plan_bounded_backfill, plan_continuous_cycle, wall_clock_local_rfc3339,
    AfddBackfillChunk, AfddConfig, AfddCycleWindow, AfddMode, AfddOperatorSchedule,
    AfddSchedulerCheckpoint, AfddSchedulerCheckpointStore, SchedulerConfigUpdate,
    AFDD_SCHEDULER_CHECKPOINTS_PATH, AFDD_SCHEDULER_CHECKPOINT_PATH,
    AFDD_SCHEDULER_RUNTIME_CONFIG_PATH, OPERATOR_INTERVAL_MINUTES, OPERATOR_LOOKBACK_DAYS,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::sync::Mutex as AsyncMutex;
use tracing::{info, warn};
use uuid::Uuid;

use crate::auth;
use crate::canonical_state::CanonicalStateStore;
use crate::state::AppState;

const MAX_RECENT_CYCLES: usize = 50;
const AFDD_RUNS_PREFIX: &str = "state/afdd/runs";

/// Polls `from` into `into` until either is set or the guard drops (M70-01).
struct CancelBridge {
    stop: Arc<AtomicBool>,
    handle: Option<tokio::task::JoinHandle<()>>,
}

impl CancelBridge {
    fn link(from: Arc<AtomicBool>, into: Arc<AtomicBool>) -> Self {
        let stop = Arc::new(AtomicBool::new(false));
        let stop_w = stop.clone();
        let handle = tokio::spawn(async move {
            while !stop_w.load(Ordering::SeqCst) && !into.load(Ordering::SeqCst) {
                if from.load(Ordering::SeqCst) {
                    into.store(true, Ordering::SeqCst);
                    break;
                }
                tokio::time::sleep(StdDuration::from_millis(200)).await;
            }
        });
        Self {
            stop,
            handle: Some(handle),
        }
    }
}

impl Drop for CancelBridge {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(handle) = self.handle.take() {
            handle.abort();
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct AfddCycleRecord {
    pub run_id: String,
    pub scope: String,
    pub trigger: String,
    pub status: String,
    pub started_at_utc: DateTime<Utc>,
    pub finished_at_utc: DateTime<Utc>,
    pub start_utc: DateTime<Utc>,
    pub end_utc: DateTime<Utc>,
    pub catch_up: bool,
    /// Time-slice size used when evaluating [`start_utc`, `end_utc`] (seconds).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub chunk_seconds: Option<u64>,
    /// `lookback_window` for the timer and run-now. `bounded_backfill` for an
    /// explicit range. Never an unbounded rewrite.
    pub result_scope: String,
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rules_succeeded: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rules_failed: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rules_skipped: Option<u64>,
}

#[derive(Debug, Default)]
struct RuntimeStatus {
    recent_cycles: VecDeque<AfddCycleRecord>,
    last_cycles_by_building: BTreeMap<String, AfddCycleRecord>,
    last_error: Option<String>,
}

pub struct AfddSchedulerRuntime {
    config: Mutex<AfddConfig>,
    store: CanonicalStateStore,
    scope_locks: DashMap<String, Arc<AsyncMutex<()>>>,
    status: Mutex<RuntimeStatus>,
    scheduled_buildings: Mutex<Vec<String>>,
}

impl AfddSchedulerRuntime {
    pub fn from_env() -> Result<Arc<Self>> {
        let mut config = AfddConfig::from_env().context("load AFDD scheduler config")?;
        let store = CanonicalStateStore::from_env().context("open canonical AFDD state store")?;
        if let Some(schedule) = load_operator_schedule(&store)? {
            if let Err(error) = config.apply_operator_schedule(&schedule) {
                warn!(%error, "ignoring invalid persisted AFDD operator schedule");
            } else {
                info!(
                    interval_minutes = schedule.interval_minutes,
                    lookback_value = schedule.lookback_value,
                    "loaded persisted AFDD operator schedule"
                );
            }
        }
        Ok(Arc::new(Self {
            config: Mutex::new(config),
            store,
            scope_locks: DashMap::new(),
            status: Mutex::new(RuntimeStatus::default()),
            scheduled_buildings: Mutex::new(Vec::new()),
        }))
    }

    /// Resolve scheduled sites from env scope against NF provider sites only.
    pub fn validate_scheduled_buildings(&self, state: &AppState) -> Result<()> {
        let known = collect_known_afdd_buildings(state);
        let config = self.config_snapshot();
        let scheduled = config
            .resolve_scheduled_buildings(&known)
            .context("AFDD building scope")?;
        let mut store = self.load_checkpoint_store()?;
        if let Some(legacy) = self.legacy_checkpoint()? {
            store.seed_missing_from_legacy(&scheduled, &legacy);
            self.persist_checkpoint_store(&store)?;
        }
        let count = scheduled.len();
        let buildings = scheduled.join(",");
        *self
            .scheduled_buildings
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = scheduled;
        if config.mode == AfddMode::Continuous && count == 0 {
            warn!("continuous AFDD enabled but no buildings are scheduled");
        } else if count > 0 {
            info!(
                count,
                buildings = %buildings,
                "AFDD scheduled buildings"
            );
        }
        Ok(())
    }

    fn scheduled_building_ids(&self) -> Vec<String> {
        self.scheduled_buildings
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    fn config_snapshot(&self) -> AfddConfig {
        self.config
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    fn legacy_checkpoint(&self) -> Result<Option<AfddSchedulerCheckpoint>> {
        let Some(bytes) = self
            .store
            .read_optional(Path::new(AFDD_SCHEDULER_CHECKPOINT_PATH))?
        else {
            return Ok(None);
        };
        Ok(Some(
            serde_json::from_slice(&bytes).context("decode legacy AFDD scheduler checkpoint")?,
        ))
    }

    fn load_checkpoint_store(&self) -> Result<AfddSchedulerCheckpointStore> {
        let Some(bytes) = self
            .store
            .read_optional(Path::new(AFDD_SCHEDULER_CHECKPOINTS_PATH))?
        else {
            return Ok(AfddSchedulerCheckpointStore::default());
        };
        serde_json::from_slice(&bytes).context("decode AFDD scheduler checkpoints")
    }

    fn persist_checkpoint_store(&self, store: &AfddSchedulerCheckpointStore) -> Result<()> {
        let bytes = serde_json::to_vec_pretty(store)?;
        self.store
            .write(Path::new(AFDD_SCHEDULER_CHECKPOINTS_PATH), &bytes)
            .context("persist AFDD scheduler checkpoints")
    }

    fn checkpoint_for_building(
        &self,
        building_id: &str,
    ) -> Result<Option<AfddSchedulerCheckpoint>> {
        let store = self.load_checkpoint_store()?;
        match store.checkpoint_for(building_id) {
            Some(cp) => Ok(Some(cp.clone())),
            None => self.legacy_checkpoint(),
        }
    }

    /// Per-building watermark from Timescale `sample` max(ts) (Wave-X C6 / R8e).
    fn latest_telemetry_for_building(&self, building_id: &str) -> Result<Option<DateTime<Utc>>> {
        let building_id = building_id.to_string();
        block_on_async(async move {
            let tsdb = fdd_tsdb::Tsdb::connect_from_env().await?;
            tsdb.max_sample_ts(&building_id)
                .await
                .map_err(anyhow::Error::from)
        })
        .context("Timescale AFDD watermark query")
    }

    fn no_data_cycle_record(
        &self,
        scope: &str,
        trigger: &str,
        run_id: String,
        started_at_utc: DateTime<Utc>,
        window: AfddCycleWindow,
    ) -> AfddCycleRecord {
        AfddCycleRecord {
            run_id,
            scope: scope.to_string(),
            trigger: trigger.to_string(),
            status: "no_data".into(),
            started_at_utc,
            finished_at_utc: Utc::now(),
            start_utc: window.start_utc,
            end_utc: window.end_utc,
            catch_up: window.catch_up,
            chunk_seconds: None,
            result_scope: result_scope_for(trigger).into(),
            ok: true,
            error: None,
            rules_succeeded: Some(0),
            rules_failed: Some(0),
            rules_skipped: Some(0),
        }
    }

    fn persist_checkpoint_for_building(
        &self,
        building_id: &str,
        checkpoint: &AfddSchedulerCheckpoint,
    ) -> Result<()> {
        let mut store = self.load_checkpoint_store()?;
        store.upsert(building_id, checkpoint.clone());
        self.persist_checkpoint_store(&store)
    }

    fn persist_operator_schedule(&self, schedule: &AfddOperatorSchedule) -> Result<()> {
        let bytes = serde_json::to_vec_pretty(schedule)?;
        self.store
            .write(Path::new(AFDD_SCHEDULER_RUNTIME_CONFIG_PATH), &bytes)
            .context("persist AFDD operator schedule")
    }

    fn update_operator_schedule(&self, schedule: AfddOperatorSchedule) -> Result<AfddConfig> {
        schedule.validate_allowlist()?;
        let mut config = self
            .config
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        config.apply_operator_schedule(&schedule)?;
        self.persist_operator_schedule(&schedule)?;
        Ok(config.clone())
    }

    fn record_cycle(&self, record: AfddCycleRecord) {
        let mut status = self
            .status
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        status.last_error = record.error.clone();
        status
            .last_cycles_by_building
            .insert(record.scope.clone(), record.clone());
        status.recent_cycles.push_front(record);
        status.recent_cycles.truncate(MAX_RECENT_CYCLES);
    }

    fn persist_run_record(&self, record: &AfddCycleRecord) -> Result<()> {
        let relative = Path::new(AFDD_RUNS_PREFIX).join(format!("{}.json", record.run_id));
        let bytes = serde_json::to_vec_pretty(record)?;
        self.store
            .write(&relative, &bytes)
            .context("persist AFDD run metadata")
    }

    fn scope_lock(&self, scope: &str) -> Arc<AsyncMutex<()>> {
        self.scope_locks
            .entry(scope.to_string())
            .or_insert_with(|| Arc::new(AsyncMutex::new(())))
            .clone()
    }

    async fn run_scheduled_cycle(&self, building_id: &str) -> Result<Option<AfddCycleRecord>> {
        let config = self.config_snapshot();
        if config.mode != AfddMode::Continuous {
            return Ok(None);
        }
        let now = Utc::now();
        let checkpoint = self.checkpoint_for_building(building_id)?;
        let latest = self.latest_telemetry_for_building(building_id)?;
        let Some(window) = plan_continuous_cycle(checkpoint.as_ref(), now, latest, &config)? else {
            return Ok(None);
        };
        self.execute_cycle(building_id, "scheduled", window, true)
            .await
            .map(Some)
    }

    async fn run_now(&self, scope: &str) -> Result<AfddCycleRecord> {
        let building_ids = self.resolve_run_targets(scope)?;
        if building_ids.len() == 1 {
            return self.run_now_single(&building_ids[0]).await;
        }
        let mut records = Vec::with_capacity(building_ids.len());
        for building_id in building_ids {
            records.push(self.run_now_single(&building_id).await?);
        }
        let ok = records.iter().all(|record| record.ok);
        let combined = AfddCycleRecord {
            run_id: records
                .first()
                .map(|record| record.run_id.clone())
                .unwrap_or_else(|| Uuid::new_v4().to_string()),
            scope: scope.to_string(),
            trigger: "run_now".into(),
            status: if ok { "completed" } else { "partial" }.into(),
            started_at_utc: records
                .iter()
                .map(|record| record.started_at_utc)
                .min()
                .unwrap_or_else(Utc::now),
            finished_at_utc: Utc::now(),
            start_utc: records
                .iter()
                .map(|record| record.start_utc)
                .min()
                .unwrap_or_else(Utc::now),
            end_utc: records
                .iter()
                .map(|record| record.end_utc)
                .max()
                .unwrap_or_else(Utc::now),
            catch_up: false,
            chunk_seconds: None,
            result_scope: result_scope_for("run_now").into(),
            ok,
            error: records.iter().find_map(|record| record.error.clone()),
            rules_succeeded: Some(records.iter().filter_map(|r| r.rules_succeeded).sum()),
            rules_failed: Some(records.iter().filter_map(|r| r.rules_failed).sum()),
            rules_skipped: Some(records.iter().filter_map(|r| r.rules_skipped).sum()),
        };
        self.record_cycle(combined.clone());
        Ok(combined)
    }

    async fn run_now_single(&self, building_id: &str) -> Result<AfddCycleRecord> {
        let config = self.config_snapshot();
        let started_at_utc = Utc::now();
        let run_id = Uuid::new_v4().to_string();
        let Some(end_utc) = self.latest_telemetry_for_building(building_id)? else {
            let configured = i64::try_from(config.lookback_seconds()?)?;
            let window = AfddCycleWindow {
                start_utc: started_at_utc - Duration::seconds(configured),
                end_utc: started_at_utc,
                scheduled_for_utc: started_at_utc,
                catch_up: false,
            };
            let record =
                self.no_data_cycle_record(building_id, "run_now", run_id, started_at_utc, window);
            self.record_cycle(record.clone());
            let _ = self.persist_run_record(&record);
            return Ok(record);
        };
        let configured = i64::try_from(config.lookback_seconds()?)?;
        // Cap operator run-now so Railway edge/nginx cannot 504 a 24h hive
        // scan under memory pressure (#1127 / Soft-OPEN tip). Continuous timer
        // still uses the configured lookback.
        let max_run_now = std::env::var("OPENFDD_AFDD_RUN_NOW_MAX_LOOKBACK_SECONDS")
            .ok()
            .and_then(|value| value.parse::<i64>().ok())
            .filter(|value| *value > 0)
            .unwrap_or(6 * 3600);
        let lookback_seconds = configured.min(max_run_now);
        let now = Utc::now();
        let window = AfddCycleWindow {
            start_utc: end_utc - Duration::seconds(lookback_seconds),
            end_utc,
            scheduled_for_utc: now,
            catch_up: false,
        };
        // Soft-OPEN gate38: default 50→90s under live ACME hive; still fail-closed
        // deferred (not process death). Override with OPENFDD_AFDD_RUN_NOW_TIMEOUT_SECONDS.
        let timeout_secs = std::env::var("OPENFDD_AFDD_RUN_NOW_TIMEOUT_SECONDS")
            .ok()
            .and_then(|value| value.parse::<u64>().ok())
            .filter(|value| *value > 0)
            .unwrap_or(90);
        let cancel = Arc::new(AtomicBool::new(false));
        let cancel_flag = cancel.clone();
        let inflight = fdd_resources::InFlightGuard::spawn("afdd_run_now");
        // Structured bridge: Drop stops the poller on success/error (M70-01).
        let _bridge = CancelBridge::link(inflight.cancel_flag(), cancel.clone());
        let fut = self.execute_cycle_chunked(building_id, "run_now", window, true, Some(cancel));
        tokio::pin!(fut);
        let outcome = match tokio::time::timeout(StdDuration::from_secs(timeout_secs), &mut fut)
            .await
        {
            Ok(result) => result,
            Err(_) => {
                // Keep the future alive, set cancel, wait for cooperative stop (#1179).
                cancel_flag.store(true, Ordering::SeqCst);
                let wait = StdDuration::from_secs(
                    std::env::var("OPENFDD_AFDD_CANCEL_WAIT_SECONDS")
                        .ok()
                        .and_then(|v| v.parse().ok())
                        .filter(|v| *v > 0)
                        .unwrap_or(15),
                );
                match tokio::time::timeout(wait, &mut fut).await {
                    Ok(Ok(mut record)) => {
                        record.status = "cancelled".into();
                        record.ok = false;
                        record.error = Some(format!(
                                "AFDD run-now exceeded OPENFDD_AFDD_RUN_NOW_TIMEOUT_SECONDS={timeout_secs}; cancelled"
                            ));
                        Ok(record)
                    }
                    Ok(Err(e)) => Err(e),
                    Err(_) => {
                        // M70-02: do not drop fut (permit/scope) while the
                        // blocking worker may still be running — drain to join.
                        match fut.await {
                            Ok(mut record) => {
                                record.status = "cancelled".into();
                                record.ok = false;
                                record.error = Some(format!(
                                        "AFDD run-now exceeded OPENFDD_AFDD_RUN_NOW_TIMEOUT_SECONDS={timeout_secs}; cancelled after worker drain"
                                    ));
                                Ok(record)
                            }
                            Err(e) => Err(e),
                        }
                    }
                }
            }
        };
        drop(inflight);
        outcome
    }

    async fn run_backfill(
        &self,
        scope: &str,
        start_utc: DateTime<Utc>,
        end_utc: DateTime<Utc>,
        chunk_hours: u64,
    ) -> Result<Vec<AfddCycleRecord>> {
        let chunks = plan_bounded_backfill(start_utc, end_utc, chunk_hours)?;
        let building_ids = self.resolve_run_targets(scope)?;
        let mut records = Vec::with_capacity(chunks.len() * building_ids.len());
        for building_id in building_ids {
            for chunk in &chunks {
                let window = AfddCycleWindow {
                    start_utc: chunk.start_utc,
                    end_utc: chunk.end_utc,
                    scheduled_for_utc: Utc::now(),
                    catch_up: false,
                };
                records.push(
                    self.execute_cycle_chunked(&building_id, "backfill", window, false, None)
                        .await?,
                );
            }
        }
        Ok(records)
    }

    async fn execute_cycle(
        &self,
        scope: &str,
        trigger: &str,
        window: AfddCycleWindow,
        advance_checkpoint: bool,
    ) -> Result<AfddCycleRecord> {
        self.execute_cycle_chunked(scope, trigger, window, advance_checkpoint, None)
            .await
    }

    /// Chunked AFDD: time slices × equipment (type-first registry list) with
    /// cooperative cancel and between-chunk pressure checks (#1179 R3).
    async fn execute_cycle_chunked(
        &self,
        scope: &str,
        trigger: &str,
        window: AfddCycleWindow,
        advance_checkpoint: bool,
        cancel: Option<Arc<AtomicBool>>,
    ) -> Result<AfddCycleRecord> {
        let scope_lock = self.scope_lock(scope);
        let Ok(_guard) = scope_lock.try_lock() else {
            anyhow::bail!("AFDD cycle already running for scope {scope}");
        };

        let started_at_utc = Utc::now();
        let run_id = Uuid::new_v4().to_string();
        let inflight = fdd_resources::InFlightGuard::spawn("afdd_chunk");
        // Scheduled/backfill must observe memory abort even without a caller
        // cancel flag; when a caller flag exists, bridge the guard into it so
        // workers see one token (M70-01/02).
        let (cancel, _cancel_bridge) = match cancel {
            Some(existing) => {
                let bridge = CancelBridge::link(inflight.cancel_flag(), existing.clone());
                (Some(existing), Some(bridge))
            }
            None => (Some(inflight.cancel_flag()), None),
        };
        let _inflight = inflight;

        let pressure = fdd_resources::sample_pressure();
        if pressure.defer_expensive_compute {
            tracing::warn!(
                target: "security_audit",
                event = "afdd_pressure_defer",
                ?pressure.state,
                percent_used = ?pressure.percent_used,
                trigger,
                scope,
                "AFDD deferred under memory pressure (not OOM claim; fail-closed)"
            );
            anyhow::bail!(
                "memory pressure {:?}/{:?}%; AFDD deferred to protect ingest (OPENFDD compute pressure policy)",
                pressure.state,
                pressure.percent_used
            );
        }
        let Some(compute) =
            fdd_resources::try_acquire_compute(fdd_resources::ComputeClass::ScheduledAfdd)
        else {
            tracing::warn!(
                target: "security_audit",
                event = "afdd_compute_admission_shed",
                trigger,
                scope,
                "OPENFDD_COMPUTE_MAX_INFLIGHT saturated; AFDD deferred"
            );
            anyhow::bail!(
                "compute admission limit reached (OPENFDD_COMPUTE_MAX_INFLIGHT); AFDD deferred"
            );
        };

        let chunk_hours = afdd_chunk_hours();
        let chunk_seconds = chunk_hours.saturating_mul(3600);
        let time_chunks = plan_bounded_backfill(window.start_utc, window.end_utc, chunk_hours)
            .unwrap_or_else(|_| {
                vec![AfddBackfillChunk {
                    start_utc: window.start_utc,
                    end_utc: window.end_utc,
                }]
            });

        if scope == "all" {
            anyhow::bail!("AFDD registry run requires an explicit building_id");
        }
        let equipment_ids = list_equipment_ids_type_first(Some(scope));
        let equipment_chunks: Vec<Option<String>> = if equipment_ids.is_empty() {
            vec![None]
        } else {
            equipment_ids.into_iter().map(Some).collect()
        };

        let mut rules_succeeded = 0u64;
        let mut rules_failed = 0u64;
        let mut rules_skipped = 0u64;
        let mut cancelled = false;
        let mut last_error: Option<String> = None;
        let mut chunks_ok = 0u64;
        let mut chunks_failed = 0u64;

        for tchunk in &time_chunks {
            if cancel.as_ref().is_some_and(|c| c.load(Ordering::SeqCst)) {
                cancelled = true;
                break;
            }
            let mid = fdd_resources::sample_pressure();
            if mid.defer_expensive_compute {
                tracing::warn!(
                    target: "security_audit",
                    event = "memory_shed",
                    percent_used = ?mid.percent_used,
                    trigger,
                    scope,
                    "AFDD cycle stopped mid-chunk under memory pressure"
                );
                last_error = Some(format!(
                    "memory shed at {:?}% during chunked AFDD; partial results kept",
                    mid.percent_used
                ));
                cancelled = true;
                break;
            }
            for eq in &equipment_chunks {
                if cancel.as_ref().is_some_and(|c| c.load(Ordering::SeqCst)) {
                    cancelled = true;
                    break;
                }
                let mut payload = registry_run_payload(
                    scope,
                    tchunk.start_utc,
                    tchunk.end_utc,
                    trigger,
                    window.catch_up,
                    &run_id,
                );
                if let Some(equipment_id) = eq {
                    payload["equipment_id"] = json!(equipment_id);
                }
                // Wave-X C6: one SQL executor — never call the retired DF stub.
                let result = if crate::timescale_historian::historian_is_timescale() {
                    match crate::timescale_product::run_fdd_registry(&payload).await {
                        Ok(v) => v,
                        Err(error) => json!({
                            "ok": false,
                            "engine": "postgres-sql",
                            "error": format!("AFDD Timescale run failed: {error:#}"),
                        }),
                    }
                } else {
                    let cancel_worker = cancel.clone();
                    tokio::task::spawn_blocking({
                        let payload = payload.clone();
                        move || {
                            open_fdd_edge_prototype::fdd::registry_api::run_registry_with_cancel(
                                &payload,
                                cancel_worker,
                            )
                        }
                    })
                    .await
                    .unwrap_or_else(|error| {
                        json!({"ok": false, "error": format!("AFDD registry task failed: {error}")})
                    })
                };
                if result
                    .get("cancelled")
                    .and_then(Value::as_bool)
                    .unwrap_or(false)
                {
                    cancelled = true;
                }
                let ok = result.get("ok").and_then(Value::as_bool).unwrap_or(false);
                rules_succeeded += result
                    .get("rules_succeeded")
                    .and_then(Value::as_u64)
                    .unwrap_or(0);
                rules_failed += result
                    .get("rules_failed")
                    .and_then(Value::as_u64)
                    .unwrap_or(0);
                rules_skipped += result
                    .get("rules_skipped")
                    .and_then(Value::as_u64)
                    .unwrap_or(0);
                if ok && !cancelled {
                    chunks_ok += 1;
                } else {
                    chunks_failed += 1;
                    if let Some(err) = result.get("error").and_then(Value::as_str) {
                        last_error = Some(err.to_string());
                    }
                }
                if cancelled {
                    break;
                }
            }
            if cancelled {
                break;
            }
        }
        drop(compute);

        let rules_clean = !cancelled && chunks_failed == 0 && rules_failed == 0;
        let status = if cancelled {
            "cancelled"
        } else if chunks_failed > 0 || rules_failed > 0 {
            "partial"
        } else if chunks_ok == 0 {
            "failed"
        } else {
            "completed"
        };
        let ok = status == "completed";
        let record = AfddCycleRecord {
            run_id,
            scope: scope.to_string(),
            trigger: trigger.to_string(),
            status: status.to_string(),
            started_at_utc,
            finished_at_utc: Utc::now(),
            start_utc: window.start_utc,
            end_utc: window.end_utc,
            catch_up: window.catch_up,
            chunk_seconds: Some(chunk_seconds),
            result_scope: result_scope_for(trigger).to_string(),
            ok,
            error: if ok {
                None
            } else {
                last_error.or_else(|| {
                    Some(if cancelled {
                        "AFDD cycle cancelled under budget/pressure".into()
                    } else {
                        "AFDD registry cycle failed or partial".into()
                    })
                })
            },
            rules_succeeded: Some(rules_succeeded),
            rules_failed: Some(rules_failed),
            rules_skipped: Some(rules_skipped),
        };

        self.persist_run_record(&record)?;
        if advance_checkpoint && rules_clean {
            self.persist_checkpoint_for_building(
                scope,
                &AfddSchedulerCheckpoint {
                    last_completed_at_utc: record.finished_at_utc,
                    analyzed_through_utc: record.end_utc,
                },
            )?;
        }
        self.record_cycle(record.clone());
        Ok(record)
    }

    fn status_json(&self) -> Result<Value> {
        let config = self.config_snapshot();
        let checkpoint_store = self.load_checkpoint_store()?;
        let scheduled = self.scheduled_building_ids();
        let now = Utc::now();
        let (last_error, recent_cycles, last_cycles_by_building) = {
            let status = self
                .status
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            (
                status.last_error.clone(),
                status.recent_cycles.clone(),
                status.last_cycles_by_building.clone(),
            )
        };
        let timer_enabled = config.mode == AfddMode::Continuous;
        let schedule_kind = config.schedule_kind;
        let watermark_source = "timescale_sample_max_ts";
        let chunk_seconds = afdd_chunk_seconds();
        let latest_cycle = recent_cycles.front();
        let mut sites = Vec::new();
        for building_id in &scheduled {
            let checkpoint = checkpoint_store.checkpoint_for(building_id).cloned();
            let latest_telemetry = self.latest_telemetry_for_building(building_id)?;
            let next_due = next_due_at(checkpoint.as_ref(), now, &config)?;
            let next_due_local = config
                .wall_clock_timezone
                .as_deref()
                .and_then(|tz| wall_clock_local_rfc3339(next_due, tz).ok());
            let last_cycle = last_cycles_by_building.get(building_id);
            sites.push(json!({
                "building_id": building_id,
                "checkpoint": checkpoint,
                "latest_persisted_telemetry_utc": latest_telemetry,
                "next_due_at_utc": if timer_enabled { Some(next_due) } else { None },
                "next_due_local": if timer_enabled { next_due_local } else { None },
                "last_cycle": last_cycle,
                "cycle_window_start": last_cycle.map(|r| r.start_utc),
                "cycle_window_end": last_cycle.map(|r| r.end_utc),
                "chunk_seconds": last_cycle
                    .and_then(|r| r.chunk_seconds)
                    .unwrap_or(chunk_seconds),
            }));
        }
        let timer_scope = if scheduled.len() == 1 {
            scheduled[0].clone()
        } else if scheduled.is_empty() {
            "none".into()
        } else {
            "multi".into()
        };
        Ok(json!({
            "ok": true,
            "config": config,
            "schedule_kind": schedule_kind,
            "scheduled_buildings": scheduled,
            "sites": sites,
            "watermark_source": watermark_source,
            "result_write": "lookback_window",
            "chunk_seconds": chunk_seconds,
            "cycle_window_start": latest_cycle.map(|r| r.start_utc),
            "cycle_window_end": latest_cycle.map(|r| r.end_utc),
            "lookback_equals_schedule_cadence": lookback_equals_schedule_cadence(&config),
            "timer_scope": timer_scope,
            "last_error": last_error,
            "recent_cycles": recent_cycles,
            "operator_schedule_editable": true,
            "operator_interval_minutes": OPERATOR_INTERVAL_MINUTES,
            "operator_lookback_days": OPERATOR_LOOKBACK_DAYS,
            "soft_open_neq_fq": true,
        }))
    }

    fn resolve_run_targets(&self, scope: &str) -> Result<Vec<String>> {
        if scope != "all" {
            return Ok(vec![scope.to_string()]);
        }
        let scheduled = self.scheduled_building_ids();
        if scheduled.is_empty() {
            anyhow::bail!("no buildings are scheduled for AFDD");
        }
        Ok(scheduled)
    }
}

/// Registry payload keys read by `run_fdd_registry` (`start` / `end` plus aliases).
pub(crate) fn registry_run_payload(
    building_id: &str,
    start_utc: DateTime<Utc>,
    end_utc: DateTime<Utc>,
    trigger: &str,
    catch_up: bool,
    run_id: &str,
) -> Value {
    let start = start_utc.to_rfc3339();
    let end = end_utc.to_rfc3339();
    json!({
        "mode": "registry",
        "building_id": building_id,
        "start": start,
        "end": end,
        "window_start": start,
        "window_end": end,
        "start_utc": start,
        "end_utc": end,
        "afdd_trigger": trigger,
        "afdd_catch_up": catch_up,
        "afdd_run_id": run_id,
        "params": {}
    })
}

pub(crate) fn collect_known_afdd_buildings(state: &AppState) -> Vec<String> {
    let mut ids = BTreeSet::new();
    for site in &state.providers.sites {
        let trimmed = site.building_id.trim();
        if !trimmed.is_empty() {
            ids.insert(trimmed.to_string());
        }
    }
    ids.into_iter().collect()
}

fn afdd_chunk_hours() -> u64 {
    std::env::var("OPENFDD_AFDD_CHUNK_HOURS")
        .ok()
        .and_then(|v| v.parse::<u64>().ok())
        .filter(|v| *v > 0)
        .unwrap_or(1)
}

fn afdd_chunk_seconds() -> u64 {
    afdd_chunk_hours().saturating_mul(3600)
}

fn result_scope_for(trigger: &str) -> &'static str {
    match trigger {
        "backfill" => "bounded_backfill",
        _ => "lookback_window",
    }
}

fn load_operator_schedule(store: &CanonicalStateStore) -> Result<Option<AfddOperatorSchedule>> {
    let Some(bytes) = store.read_optional(Path::new(AFDD_SCHEDULER_RUNTIME_CONFIG_PATH))? else {
        return Ok(None);
    };
    Ok(Some(
        serde_json::from_slice(&bytes).context("decode AFDD operator schedule")?,
    ))
}

#[derive(Debug, Deserialize)]
pub struct RunNowRequest {
    #[serde(default)]
    building_id: Option<String>,
}

/// Type-first equipment list for chunked AFDD. Exact `equipment_id` values only
/// (no substring/prefix). Falls back to a single whole-building chunk when empty.
/// Soft-OPEN: Timescale product path reads stamped `equipment` rows (not Parquet hive).
fn list_equipment_ids_type_first(building_id: Option<&str>) -> Vec<String> {
    if crate::timescale_historian::historian_is_timescale() {
        if let Some(bid) = building_id.map(str::trim).filter(|s| !s.is_empty()) {
            match list_equipment_ids_timescale(bid) {
                Ok(ids) if !ids.is_empty() => return ids,
                Ok(_) => {}
                Err(error) => {
                    warn!(%error, building_id = %bid, "Timescale AFDD equipment list failed; falling back");
                }
            }
        }
    }
    let resp = open_fdd_edge_prototype::fdd::registry_api::equipment_response(building_id);
    let mut rows: Vec<(String, String)> = resp
        .get("equipment")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|row| {
            let id = row.get("equipment_id")?.as_str()?.trim();
            if id.is_empty() {
                return None;
            }
            let kind = row
                .get("equipment_type")
                .or_else(|| row.get("equipType"))
                .or_else(|| row.get("kind"))
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_ascii_lowercase();
            Some((kind, id.to_string()))
        })
        .collect();
    rows.sort_by(|a, b| a.0.cmp(&b.0).then_with(|| a.1.cmp(&b.1)));
    rows.into_iter().map(|(_, id)| id).collect()
}

/// Soft-OPEN R8d/R8e: type-first equipment ids from Timescale `equipment` table.
fn list_equipment_ids_timescale(building_id: &str) -> Result<Vec<String>> {
    let bid = building_id.to_string();
    block_on_async(async move {
        let env = crate::timescale_product::equipment_from_timescale(Some(&bid)).await?;
        let mut rows: Vec<(String, String)> = env
            .get("equipment")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|row| {
                let id = row.get("equipment_id")?.as_str()?.trim();
                if id.is_empty() {
                    return None;
                }
                let kind = row
                    .get("equipment_type")
                    .or_else(|| row.get("equipType"))
                    .and_then(Value::as_str)
                    .unwrap_or("unclassified")
                    .to_ascii_lowercase();
                Some((kind, id.to_string()))
            })
            .collect();
        rows.sort_by(|a, b| a.0.cmp(&b.0).then_with(|| a.1.cmp(&b.1)));
        Ok(rows.into_iter().map(|(_, id)| id).collect())
    })
}

/// Drive an async Timescale helper from sync AFDD paths without nesting a runtime.
/// Matches `live_historian` / `canonical_state`: `block_in_place` on multi-thread
/// workers; private current-thread runtime only when no Tokio context exists.
fn block_on_async<F, T>(future: F) -> Result<T>
where
    F: std::future::Future<Output = Result<T>>,
{
    if let Ok(handle) = tokio::runtime::Handle::try_current() {
        match handle.runtime_flavor() {
            tokio::runtime::RuntimeFlavor::MultiThread => {
                return tokio::task::block_in_place(|| handle.block_on(future));
            }
            tokio::runtime::RuntimeFlavor::CurrentThread => {
                anyhow::bail!("AFDD Timescale sync helper requires a multi-thread Tokio runtime");
            }
            _ => anyhow::bail!("unsupported Tokio runtime flavor for AFDD Timescale helper"),
        }
    }
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .context("afdd Timescale helper runtime")?;
    runtime.block_on(future)
}

fn normalize_scope(building_id: Option<&str>) -> String {
    building_id
        .map(str::trim)
        .filter(|scope| !scope.is_empty())
        .unwrap_or("all")
        .to_string()
}

pub fn router(state: Arc<AppState>, runtime: Arc<AfddSchedulerRuntime>) -> Router {
    Router::new()
        .route("/api/afdd/status", get(scheduler_status))
        .route("/api/afdd/scheduler/status", get(scheduler_status))
        .route(
            "/api/afdd/scheduler/result-slices",
            get(scheduler_result_slices),
        )
        .route("/api/afdd/scheduler/run-now", post(scheduler_run_now))
        .route("/api/afdd/scheduler/config", post(scheduler_update_config))
        .route("/api/afdd/scheduler/backfill", post(scheduler_backfill))
        .layer(Extension(runtime))
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            auth::jwt_middleware,
        ))
        .with_state(state)
}

#[derive(Debug, Deserialize)]
struct ResultSliceQuery {
    #[serde(default)]
    building_id: Option<String>,
}

async fn scheduler_result_slices(Query(query): Query<ResultSliceQuery>) -> Json<Value> {
    Json(
        open_fdd_edge_prototype::fdd::registry_api::result_slice_report(
            query.building_id.as_deref(),
        ),
    )
}

async fn scheduler_status(Extension(runtime): Extension<Arc<AfddSchedulerRuntime>>) -> Json<Value> {
    match runtime.status_json() {
        Ok(value) => Json(value),
        Err(error) => Json(json!({"ok": false, "error": error.to_string()})),
    }
}

async fn scheduler_run_now(
    Extension(runtime): Extension<Arc<AfddSchedulerRuntime>>,
    Json(body): Json<RunNowRequest>,
) -> Json<Value> {
    let scope = normalize_scope(body.building_id.as_deref());
    match runtime.run_now(&scope).await {
        Ok(record) => Json(json!({"ok": record.ok, "cycle": record})),
        Err(error) => Json(json!({"ok": false, "error": error.to_string()})),
    }
}

async fn scheduler_update_config(
    Extension(runtime): Extension<Arc<AfddSchedulerRuntime>>,
    Json(body): Json<Value>,
) -> Json<Value> {
    let update = match SchedulerConfigUpdate::from_json(&body) {
        Ok(update) => update,
        Err(error) => return Json(json!({"ok": false, "error": error.to_string()})),
    };
    let schedule = match apply_scheduler_config_update(&runtime.config_snapshot(), &update) {
        Ok(schedule) => schedule,
        Err(error) => return Json(json!({"ok": false, "error": error.to_string()})),
    };
    match runtime.update_operator_schedule(schedule) {
        Ok(config) => Json(json!({
            "ok": true,
            "config": config,
        })),
        Err(error) => Json(json!({"ok": false, "error": error.to_string()})),
    }
}

async fn scheduler_backfill(
    Extension(runtime): Extension<Arc<AfddSchedulerRuntime>>,
    Json(body): Json<Value>,
) -> Json<Value> {
    let parsed = match parse_backfill_request(&body) {
        Ok(parsed) => parsed,
        Err(error) => return Json(json!({"ok": false, "error": error.to_string()})),
    };
    let scope = normalize_scope(parsed.building_id.as_deref());
    match runtime
        .run_backfill(&scope, parsed.start_utc, parsed.end_utc, parsed.chunk_hours)
        .await
    {
        Ok(cycles) => {
            let ok = cycles.iter().all(|cycle| cycle.ok);
            Json(json!({
                "ok": ok,
                "result_scope": "bounded_backfill",
                "cycles": cycles,
            }))
        }
        Err(error) => Json(json!({"ok": false, "error": error.to_string()})),
    }
}

pub fn spawn(runtime: Arc<AfddSchedulerRuntime>) -> Option<tokio::task::JoinHandle<()>> {
    if runtime.config_snapshot().mode != AfddMode::Continuous {
        info!("AFDD scheduler is in bulk mode; continuous timer is disabled");
        return None;
    }
    Some(tokio::spawn(async move {
        let mut interval = tokio::time::interval(StdDuration::from_secs(30));
        interval.tick().await;
        loop {
            interval.tick().await;
            for building_id in runtime.scheduled_building_ids() {
                match runtime.run_scheduled_cycle(&building_id).await {
                    Ok(Some(record)) => info!(
                        scope = %record.scope,
                        analyzed_through = %record.end_utc,
                        catch_up = record.catch_up,
                        "continuous AFDD cycle completed"
                    ),
                    Ok(None) => {}
                    Err(error) => {
                        warn!(building_id = %building_id, %error, "continuous AFDD cycle failed");
                        runtime
                            .status
                            .lock()
                            .unwrap_or_else(std::sync::PoisonError::into_inner)
                            .last_error = Some(error.to_string());
                    }
                }
            }
        }
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn blank_scope_normalizes_to_all() {
        assert_eq!(normalize_scope(None), "all");
        assert_eq!(normalize_scope(Some("   ")), "all");
        assert_eq!(normalize_scope(Some(" building-a ")), "building-a");
    }

    #[test]
    fn result_scope_never_means_full_history() {
        assert_eq!(result_scope_for("scheduled"), "lookback_window");
        assert_eq!(result_scope_for("run_now"), "lookback_window");
        assert_eq!(result_scope_for("backfill"), "bounded_backfill");
    }

    /// Soft-OPEN P1: bare Handle::block_on on a worker panics with
    /// "Cannot start a runtime from within a runtime" (Grok ART 3.6.14 /scheduler/status 502).
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn block_on_async_safe_inside_multi_thread_runtime() {
        let value =
            block_on_async(async { Ok::<_, anyhow::Error>(42u32) }).expect("nested-safe block_on");
        assert_eq!(value, 42);
    }

    #[test]
    fn t1403_1_registry_payload_window_keys_match_chunk() {
        let start = Utc::now() - Duration::hours(6);
        let end = Utc::now();
        let start_s = start.to_rfc3339();
        let end_s = end.to_rfc3339();
        let payload = registry_run_payload("site-a", start, end, "scheduled", false, "run-1");
        assert_eq!(
            payload.get("start").and_then(Value::as_str),
            payload.get("window_start").and_then(Value::as_str)
        );
        assert_eq!(
            payload.get("end").and_then(Value::as_str),
            payload.get("window_end").and_then(Value::as_str)
        );
        assert_eq!(
            payload.get("start").and_then(Value::as_str),
            Some(start_s.as_str())
        );
        assert_eq!(
            payload.get("end").and_then(Value::as_str),
            Some(end_s.as_str())
        );
        assert_eq!(
            payload.get("building_id").and_then(Value::as_str),
            Some("site-a")
        );
    }

    #[test]
    fn t1403_4_provider_scope_rejects_csv_building_id() {
        let known = vec!["prov-a".into(), "prov-b".into()];
        let scheduled = AfddConfig::default()
            .resolve_scheduled_buildings(&known)
            .expect("all provider sites");
        assert_eq!(scheduled, vec!["prov-a", "prov-b"]);
        let csv_only = "csv-package-site";
        let err = AfddConfig {
            scope_building_ids: vec![csv_only.into()],
            ..AfddConfig::default()
        }
        .resolve_scheduled_buildings(&known)
        .expect_err("csv id");
        assert!(err.to_string().contains("NF provider site"));
        assert!(!known.contains(&csv_only.to_string()));
    }

    #[test]
    fn t1403_5_bounded_chunks_tile_24h_lookback_window() {
        use chrono::TimeZone;
        use fdd_store::plan_bounded_backfill;
        let start = Utc.with_ymd_and_hms(2026, 6, 10, 12, 0, 0).unwrap();
        let end = start + Duration::hours(24);
        let chunks = plan_bounded_backfill(start, end, 1).expect("plan chunks");
        assert_eq!(chunks.len(), 24);
        assert_eq!(chunks[0].start_utc, start);
        assert_eq!(chunks[23].end_utc, end);
        for pair in chunks.windows(2) {
            assert_eq!(pair[0].end_utc, pair[1].start_utc);
        }
        let window_seconds = (end - start).num_seconds();
        assert_eq!(window_seconds, 24 * 3600);
    }

    #[test]
    fn t1403_2_explicit_building_ids_select_subset() {
        let config = AfddConfig {
            scope_building_ids: vec!["site-b".into(), "site-a".into()],
            ..AfddConfig::default()
        };
        let scheduled = config
            .resolve_scheduled_buildings(&["site-a".into(), "site-b".into(), "site-c".into()])
            .unwrap();
        assert_eq!(scheduled, vec!["site-a", "site-b"]);
    }
}

#[cfg(test)]
mod contract_timescale {
    use super::*;
    use chrono::TimeZone;
    use fdd_store::AfddConfig;
    use fdd_tsdb::{SampleRow, Tsdb, UpsertBatch};

    fn fixture_database_url() -> Option<String> {
        std::env::var("OPENFDD_LIFECYCLE_DATABASE_URL")
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
    }

    fn assert_disposable(id: &str) {
        let upper = id.to_ascii_uppercase();
        assert!(!upper.contains("BUILDING_50") && !upper.contains("BOSSPI"));
    }

    async fn ensure_schema(tsdb: &Tsdb) {
        static ONCE: tokio::sync::OnceCell<()> = tokio::sync::OnceCell::const_new();
        ONCE.get_or_init(|| async {
            for stmt in crate::db_lifecycle::forward_statements() {
                sqlx::query(&stmt)
                    .execute(tsdb.pool())
                    .await
                    .expect("schema");
            }
        })
        .await;
    }

    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_* env while the disposable historian fixture is connected"
    )]
    #[tokio::test]
    async fn t1403_1_recorded_run_window_equals_payload_lookback() {
        let Some(url) = fixture_database_url() else {
            eprintln!("skip t1403_1: OPENFDD_LIFECYCLE_DATABASE_URL unset");
            return;
        };
        let _lock = crate::test_env_lock::lock_env();
        let site = format!("af{}", uuid::Uuid::new_v4().simple());
        assert_disposable(&site);
        std::env::set_var("OPENFDD_DATABASE_URL", &url);
        std::env::set_var("OPENFDD_HISTORIAN", "timescale");
        let results_dir = tempfile::tempdir().expect("results dir");
        std::env::set_var("OPENFDD_RULE_RESULTS_DIR", results_dir.path());

        let tsdb = Tsdb::connect(&url).await.expect("connect");
        ensure_schema(&tsdb).await;
        tsdb.ensure_site_building(&site).await.expect("site");
        tsdb.upsert_equipment(&site, "AHU_1", Some("ahu"))
            .await
            .expect("equipment");

        let t0 = Utc.with_ymd_and_hms(2026, 6, 1, 0, 0, 0).unwrap();
        let mut batch = UpsertBatch::default();
        for hour in [0i64, 40] {
            batch.push(SampleRow::new(
                t0 + Duration::hours(hour),
                &site,
                "AHU_1.sat",
                Some(70.0),
            ));
        }
        tsdb.upsert_samples(&batch).await.expect("samples");

        let lookback_hours = 6i64;
        let end = t0 + Duration::hours(40);
        let start = end - Duration::hours(lookback_hours);
        let payload = registry_run_payload(&site, start, end, "scheduled", false, "run-1");
        let summary = crate::timescale_product::run_fdd_registry(&payload)
            .await
            .expect("registry run");
        assert_eq!(
            summary.pointer("/window/start").and_then(|v| v.as_str()),
            Some(start.to_rfc3339().as_str())
        );
        assert_eq!(
            summary.pointer("/window/end").and_then(|v| v.as_str()),
            Some(end.to_rfc3339().as_str())
        );
        let outside: i64 = sqlx::query_scalar(
            "SELECT count(*)::bigint FROM sample WHERE site_id = $1 AND ts < $2::timestamptz",
        )
        .bind(&site)
        .bind(start)
        .fetch_one(tsdb.pool())
        .await
        .expect("outside");
        assert_eq!(outside, 1);
        let _ = tsdb.purge_building(&site).await;
    }

    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_* env while the disposable historian fixture is connected"
    )]
    #[tokio::test]
    async fn t1403_4_collect_known_is_provider_sites_only() {
        let Some(url) = fixture_database_url() else {
            eprintln!("skip t1403_4: OPENFDD_LIFECYCLE_DATABASE_URL unset");
            return;
        };
        let _lock = crate::test_env_lock::lock_env();
        let prov_a = format!("p4a{}", uuid::Uuid::new_v4().simple());
        let prov_b = format!("p4b{}", uuid::Uuid::new_v4().simple());
        let csv_only = format!("csv{}", uuid::Uuid::new_v4().simple());
        for id in [&prov_a, &prov_b, &csv_only] {
            assert_disposable(id);
        }
        let sites_json = format!(
            r#"[{{"building_id":"{prov_a}","tenant_id":"tenant-a","provider":"nf","endpoint":"https://portal.example","auth_mode":"anonymous"}},{{"building_id":"{prov_b}","tenant_id":"tenant-a","provider":"nf","endpoint":"https://portal.example","auth_mode":"anonymous"}}]"#
        );
        std::env::set_var("OPENFDD_PROVIDER_SITES", &sites_json);
        std::env::set_var("OPENFDD_DATABASE_URL", &url);
        std::env::set_var("OPENFDD_HISTORIAN", "timescale");
        let state = AppState::new();
        let tsdb = Tsdb::connect(&url).await.expect("connect");
        ensure_schema(&tsdb).await;
        tsdb.ensure_site_building(&csv_only)
            .await
            .expect("csv site");
        let known = collect_known_afdd_buildings(&state);
        assert_eq!(known.len(), 2);
        assert!(known.iter().any(|id| id == &prov_a));
        assert!(known.iter().any(|id| id == &prov_b));
        assert!(!known.iter().any(|id| id == &csv_only));
        let scheduled = AfddConfig::default()
            .resolve_scheduled_buildings(&known)
            .expect("schedule providers");
        assert_eq!(scheduled.len(), 2);
        let startup_err = AfddConfig {
            scope_building_ids: vec![csv_only.clone()],
            ..AfddConfig::default()
        }
        .resolve_scheduled_buildings(&known)
        .expect_err("csv in OPENFDD_AFDD_BUILDING_IDS");
        assert!(startup_err.to_string().contains("NF provider site"));
        let _ = tsdb.purge_building(&csv_only).await;
        std::env::remove_var("OPENFDD_PROVIDER_SITES");
    }

    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_* env while the disposable historian fixture is connected"
    )]
    #[tokio::test]
    async fn t1403_5_fdd_run_windows_tile_cycle_lookback() {
        let Some(url) = fixture_database_url() else {
            eprintln!("skip t1403_5: OPENFDD_LIFECYCLE_DATABASE_URL unset");
            return;
        };
        let _lock = crate::test_env_lock::lock_env();
        let site = format!("p5{}", uuid::Uuid::new_v4().simple());
        assert_disposable(&site);
        std::env::set_var("OPENFDD_DATABASE_URL", &url);
        std::env::set_var("OPENFDD_HISTORIAN", "timescale");
        std::env::set_var("OPENFDD_AFDD_CHUNK_HOURS", "1");
        let results_dir = tempfile::tempdir().expect("results dir");
        std::env::set_var("OPENFDD_RULE_RESULTS_DIR", results_dir.path());

        let tsdb = Tsdb::connect(&url).await.expect("connect");
        ensure_schema(&tsdb).await;
        tsdb.ensure_site_building(&site).await.expect("site");
        tsdb.upsert_equipment(&site, "AHU_1", Some("ahu"))
            .await
            .expect("equipment");

        let cycle_end = Utc.with_ymd_and_hms(2026, 6, 15, 0, 0, 0).unwrap();
        let cycle_start = cycle_end - Duration::hours(24);
        let t_sample = cycle_end - Duration::hours(1);
        let mut batch = UpsertBatch::default();
        batch.push(SampleRow::new(t_sample, &site, "AHU_1.sat", Some(72.0)));
        tsdb.upsert_samples(&batch).await.expect("samples");

        let chunks = fdd_store::plan_bounded_backfill(cycle_start, cycle_end, 1).expect("chunks");
        assert_eq!(chunks.len(), 24);
        for (idx, chunk) in chunks.iter().enumerate() {
            let payload = registry_run_payload(
                &site,
                chunk.start_utc,
                chunk.end_utc,
                "scheduled",
                false,
                &format!("run-{idx}"),
            );
            let _ = crate::timescale_product::run_fdd_registry(&payload)
                .await
                .expect("chunk run");
        }

        let windows: Vec<(DateTime<Utc>, DateTime<Utc>)> = sqlx::query_as(
            "SELECT DISTINCT window_start, window_end FROM fdd_run WHERE site_id = $1 ORDER BY window_start",
        )
        .bind(&site)
        .fetch_all(tsdb.pool())
        .await
        .expect("windows");
        assert_eq!(windows.len(), 24);
        assert_eq!(windows[0].0, cycle_start);
        assert_eq!(windows[23].1, cycle_end);
        for pair in windows.windows(2) {
            assert_eq!(pair[0].1, pair[1].0);
        }
        let record = AfddCycleRecord {
            run_id: "contract".into(),
            scope: site.clone(),
            trigger: "scheduled".into(),
            status: "completed".into(),
            started_at_utc: Utc::now(),
            finished_at_utc: Utc::now(),
            start_utc: cycle_start,
            end_utc: cycle_end,
            catch_up: false,
            chunk_seconds: Some(3600),
            result_scope: "lookback_window".into(),
            ok: true,
            error: None,
            rules_succeeded: Some(0),
            rules_failed: Some(0),
            rules_skipped: Some(0),
        };
        assert_eq!((record.end_utc - record.start_utc).num_seconds(), 24 * 3600);
        assert_eq!(record.chunk_seconds, Some(3600));
        let _ = tsdb.purge_building(&site).await;
        std::env::remove_var("OPENFDD_AFDD_CHUNK_HOURS");
    }

    #[tokio::test]
    async fn t1403_2_three_fixture_sites_and_unknown_id() {
        let Some(url) = fixture_database_url() else {
            eprintln!("skip t1403_2: OPENFDD_LIFECYCLE_DATABASE_URL unset");
            return;
        };
        let _lock = crate::test_env_lock::lock_env();
        let sites = [
            format!("a1{}", uuid::Uuid::new_v4().simple()),
            format!("a2{}", uuid::Uuid::new_v4().simple()),
            format!("a3{}", uuid::Uuid::new_v4().simple()),
        ];
        for site in &sites {
            assert_disposable(site);
        }
        std::env::set_var("OPENFDD_DATABASE_URL", &url);
        std::env::set_var("OPENFDD_HISTORIAN", "timescale");
        let tsdb = Tsdb::connect(&url).await.expect("connect");
        ensure_schema(&tsdb).await;
        for site in &sites {
            tsdb.ensure_site_building(site).await.expect("site");
        }
        let known = vec![sites[0].clone(), sites[1].clone(), sites[2].clone()];
        let scheduled = AfddConfig::default()
            .resolve_scheduled_buildings(&known)
            .expect("resolve all");
        for site in &sites {
            assert!(scheduled.iter().any(|id| id == site));
        }
        let bad = AfddConfig {
            scope_building_ids: vec![format!("{}-missing", sites[0])],
            ..AfddConfig::default()
        };
        assert!(bad
            .resolve_scheduled_buildings(&known)
            .expect_err("unknown")
            .to_string()
            .contains("NF provider site"));
        for site in &sites {
            let _ = tsdb.purge_building(site).await;
        }
    }
}
