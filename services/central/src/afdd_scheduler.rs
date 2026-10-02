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

use std::collections::VecDeque;
use std::path::Path;
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
    apply_scheduler_config_update, lookback_matches_cadence, next_due_at, parse_backfill_request,
    plan_bounded_backfill, plan_continuous_cycle, wall_clock_local_rfc3339, AfddConfig,
    AfddCycleWindow, AfddMode, AfddOperatorSchedule, AfddSchedulerCheckpoint,
    SchedulerConfigUpdate, AFDD_SCHEDULER_CHECKPOINT_PATH, AFDD_SCHEDULER_RUNTIME_CONFIG_PATH,
    OPERATOR_INTERVAL_MINUTES, OPERATOR_LOOKBACK_DAYS,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::sync::Mutex as AsyncMutex;
use tracing::{info, warn};
use uuid::Uuid;

use crate::auth;
use crate::canonical_state::CanonicalStateStore;
use crate::state::AppState;

const LATEST_TELEMETRY_WATERMARK_PATH: &str = "state/live-historian/latest-telemetry.json";
const MAX_RECENT_CYCLES: usize = 50;
const AFDD_RUNS_PREFIX: &str = "state/afdd/runs";

#[derive(Debug, Deserialize)]
struct LatestTelemetryWatermark {
    latest_persisted_timestamp_utc: DateTime<Utc>,
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
    last_error: Option<String>,
}

pub struct AfddSchedulerRuntime {
    config: Mutex<AfddConfig>,
    store: CanonicalStateStore,
    scope_locks: DashMap<String, Arc<AsyncMutex<()>>>,
    status: Mutex<RuntimeStatus>,
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
        }))
    }

    fn config_snapshot(&self) -> AfddConfig {
        self.config.lock().unwrap().clone()
    }

    fn checkpoint(&self) -> Result<Option<AfddSchedulerCheckpoint>> {
        let Some(bytes) = self
            .store
            .read_optional(Path::new(AFDD_SCHEDULER_CHECKPOINT_PATH))?
        else {
            return Ok(None);
        };
        Ok(Some(
            serde_json::from_slice(&bytes).context("decode AFDD scheduler checkpoint")?,
        ))
    }

    fn latest_telemetry(&self) -> Result<Option<DateTime<Utc>>> {
        let Some(bytes) = self
            .store
            .read_optional(Path::new(LATEST_TELEMETRY_WATERMARK_PATH))?
        else {
            return Ok(None);
        };
        let watermark: LatestTelemetryWatermark =
            serde_json::from_slice(&bytes).context("decode live telemetry watermark")?;
        Ok(Some(watermark.latest_persisted_timestamp_utc))
    }

    fn persist_checkpoint(&self, checkpoint: &AfddSchedulerCheckpoint) -> Result<()> {
        let bytes = serde_json::to_vec_pretty(checkpoint)?;
        self.store
            .write(Path::new(AFDD_SCHEDULER_CHECKPOINT_PATH), &bytes)
            .context("persist AFDD scheduler checkpoint")
    }

    fn persist_operator_schedule(&self, schedule: &AfddOperatorSchedule) -> Result<()> {
        let bytes = serde_json::to_vec_pretty(schedule)?;
        self.store
            .write(Path::new(AFDD_SCHEDULER_RUNTIME_CONFIG_PATH), &bytes)
            .context("persist AFDD operator schedule")
    }

    fn update_operator_schedule(&self, schedule: AfddOperatorSchedule) -> Result<AfddConfig> {
        schedule.validate_allowlist()?;
        let mut config = self.config.lock().unwrap();
        config.apply_operator_schedule(&schedule)?;
        self.persist_operator_schedule(&schedule)?;
        Ok(config.clone())
    }

    fn record_cycle(&self, record: AfddCycleRecord) {
        let mut status = self.status.lock().unwrap();
        status.last_error = record.error.clone();
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

    async fn run_scheduled_cycle(&self, scope: &str) -> Result<Option<AfddCycleRecord>> {
        let config = self.config_snapshot();
        if config.mode != AfddMode::Continuous {
            return Ok(None);
        }
        let now = Utc::now();
        let checkpoint = self.checkpoint()?;
        let latest = self.latest_telemetry()?;
        let Some(window) = plan_continuous_cycle(checkpoint.as_ref(), now, latest, &config)? else {
            return Ok(None);
        };
        self.execute_cycle(scope, "scheduled", window, true)
            .await
            .map(Some)
    }

    async fn run_now(&self, scope: &str) -> Result<AfddCycleRecord> {
        let config = self.config_snapshot();
        let end_utc = self
            .latest_telemetry()?
            .ok_or_else(|| anyhow::anyhow!("no persisted telemetry watermark is available"))?;
        let lookback_seconds = i64::try_from(config.lookback_seconds()?)?;
        let now = Utc::now();
        let window = AfddCycleWindow {
            start_utc: end_utc - Duration::seconds(lookback_seconds),
            end_utc,
            scheduled_for_utc: now,
            catch_up: false,
        };
        self.execute_cycle(scope, "run_now", window, true).await
    }

    async fn run_backfill(
        &self,
        scope: &str,
        start_utc: DateTime<Utc>,
        end_utc: DateTime<Utc>,
        chunk_hours: u64,
    ) -> Result<Vec<AfddCycleRecord>> {
        let chunks = plan_bounded_backfill(start_utc, end_utc, chunk_hours)?;
        let mut records = Vec::with_capacity(chunks.len());
        for chunk in chunks {
            let window = AfddCycleWindow {
                start_utc: chunk.start_utc,
                end_utc: chunk.end_utc,
                scheduled_for_utc: Utc::now(),
                catch_up: false,
            };
            // Backfill does not move the continuous checkpoint.
            records.push(self.execute_cycle(scope, "backfill", window, false).await?);
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
        let scope_lock = self.scope_lock(scope);
        let Ok(_guard) = scope_lock.try_lock() else {
            anyhow::bail!("AFDD cycle already running for scope {scope}");
        };

        let started_at_utc = Utc::now();
        let run_id = Uuid::new_v4().to_string();
        let payload = json!({
            "mode": "registry",
            "building_id": if scope == "all" { Value::Null } else { json!(scope) },
            "start_utc": window.start_utc.to_rfc3339(),
            "end_utc": window.end_utc.to_rfc3339(),
            "afdd_trigger": trigger,
            "afdd_catch_up": window.catch_up,
            "afdd_run_id": run_id,
            "params": {}
        });

        let result = tokio::task::spawn_blocking(move || {
            open_fdd_edge_prototype::fdd::registry_api::run_registry(&payload)
        })
        .await
        .unwrap_or_else(
            |error| json!({"ok": false, "error": format!("AFDD registry task failed: {error}")}),
        );

        let ok = result.get("ok").and_then(Value::as_bool).unwrap_or(false);
        let error = result
            .get("error")
            .and_then(Value::as_str)
            .map(str::to_string)
            .filter(|value| !value.is_empty());
        let rules_failed = result.get("rules_failed").and_then(Value::as_u64);
        // Partial success: registry ok but some rules failed - do not advance checkpoint.
        // Backfill passes advance_checkpoint=false so a historical range cannot
        // move the continuous watermark.
        let rules_clean = ok && rules_failed.unwrap_or(0) == 0;
        let status = if !ok {
            "failed"
        } else if rules_failed.unwrap_or(0) > 0 {
            "partial"
        } else {
            "completed"
        };
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
            result_scope: result_scope_for(trigger).to_string(),
            ok,
            error: if ok {
                None
            } else {
                error.or_else(|| Some("AFDD registry cycle failed".into()))
            },
            rules_succeeded: result.get("rules_succeeded").and_then(Value::as_u64),
            rules_failed,
            rules_skipped: result.get("rules_skipped").and_then(Value::as_u64),
        };

        // Persist run metadata before advancing the success checkpoint so a
        // failed write cannot leave an advanced watermark without a run record.
        self.persist_run_record(&record)?;
        if advance_checkpoint && rules_clean {
            self.persist_checkpoint(&AfddSchedulerCheckpoint {
                last_completed_at_utc: record.finished_at_utc,
                analyzed_through_utc: record.end_utc,
            })?;
        }
        self.record_cycle(record.clone());
        Ok(record)
    }

    fn status_json(&self) -> Result<Value> {
        let config = self.config_snapshot();
        let checkpoint = self.checkpoint()?;
        let latest_telemetry = self.latest_telemetry()?;
        let now = Utc::now();
        let next_due = next_due_at(checkpoint.as_ref(), now, &config)?;
        let next_due_local = config
            .wall_clock_timezone
            .as_deref()
            .and_then(|tz| wall_clock_local_rfc3339(next_due, tz).ok());
        let status = self.status.lock().unwrap();
        let timer_scope =
            normalize_scope(std::env::var("OPENFDD_AFDD_BUILDING_ID").ok().as_deref());
        let timer_enabled = config.mode == AfddMode::Continuous;
        let schedule_kind = config.schedule_kind;
        Ok(json!({
            "ok": true,
            "config": config,
            "schedule_kind": schedule_kind,
            "checkpoint": checkpoint,
            "latest_persisted_telemetry_utc": latest_telemetry,
            "next_due_at_utc": if timer_enabled { Some(next_due) } else { None },
            "next_due_local": if timer_enabled { next_due_local } else { None },
            "result_write": "lookback_window",
            "lookback_matches_cadence": lookback_matches_cadence(&config),
            "timer_scope": timer_scope,
            "last_error": status.last_error,
            "recent_cycles": status.recent_cycles,
            "operator_schedule_editable": true,
            "operator_interval_minutes": OPERATOR_INTERVAL_MINUTES,
            "operator_lookback_days": OPERATOR_LOOKBACK_DAYS,
        }))
    }
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

fn normalize_scope(building_id: Option<&str>) -> String {
    building_id
        .map(str::trim)
        .filter(|scope| !scope.is_empty())
        .unwrap_or("all")
        .to_string()
}

pub fn router(state: Arc<AppState>, runtime: Arc<AfddSchedulerRuntime>) -> Router {
    Router::new()
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
    let scope = normalize_scope(std::env::var("OPENFDD_AFDD_BUILDING_ID").ok().as_deref());
    Some(tokio::spawn(async move {
        let mut interval = tokio::time::interval(StdDuration::from_secs(30));
        interval.tick().await;
        loop {
            interval.tick().await;
            match runtime.run_scheduled_cycle(&scope).await {
                Ok(Some(record)) => info!(
                    scope = %record.scope,
                    analyzed_through = %record.end_utc,
                    catch_up = record.catch_up,
                    "continuous AFDD cycle completed"
                ),
                Ok(None) => {}
                Err(error) => {
                    warn!(scope = %scope, %error, "continuous AFDD cycle failed");
                    runtime.status.lock().unwrap().last_error = Some(error.to_string());
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
}
