//! Continuous AFDD scheduler runtime owned by Central.
//!
//! Scheduled cycles and operator-triggered run-now cycles share `execute_cycle`.
//! A per-scope Tokio mutex prevents overlapping AFDD runs for the same building,
//! while failures are recorded without advancing the persisted checkpoint.
//!
//! Mode remains deployment/env-owned. Interval + rolling lookback may be updated
//! via authenticated `POST /api/afdd/scheduler/config` using an allowlisted set
//! (1/3/6/12 hour frequency; 1/2/3 day lookback) and persist under canonical state.

use std::collections::VecDeque;
use std::path::Path;
use std::sync::{Arc, Mutex};
use std::time::Duration as StdDuration;

use anyhow::{Context, Result};
use axum::extract::Extension;
use axum::middleware;
use axum::routing::{get, post};
use axum::{Json, Router};
use chrono::{DateTime, Duration, Utc};
use dashmap::DashMap;
use fdd_store::{
    next_due_at, plan_continuous_cycle, AfddConfig, AfddCycleWindow, AfddLookbackUnit, AfddMode,
    AfddOperatorSchedule, AfddSchedulerCheckpoint, AFDD_SCHEDULER_CHECKPOINT_PATH,
    AFDD_SCHEDULER_RUNTIME_CONFIG_PATH, OPERATOR_INTERVAL_MINUTES, OPERATOR_LOOKBACK_DAYS,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::sync::Mutex as AsyncMutex;
use tracing::{info, warn};

use crate::auth;
use crate::canonical_state::CanonicalStateStore;
use crate::state::AppState;

const LATEST_TELEMETRY_WATERMARK_PATH: &str = "state/live-historian/latest-telemetry.json";
const MAX_RECENT_CYCLES: usize = 50;

#[derive(Debug, Deserialize)]
struct LatestTelemetryWatermark {
    latest_persisted_timestamp_utc: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize)]
pub struct AfddCycleRecord {
    pub scope: String,
    pub trigger: String,
    pub started_at_utc: DateTime<Utc>,
    pub finished_at_utc: DateTime<Utc>,
    pub start_utc: DateTime<Utc>,
    pub end_utc: DateTime<Utc>,
    pub catch_up: bool,
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
        self.execute_cycle(scope, "scheduled", window).await.map(Some)
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
        self.execute_cycle(scope, "run_now", window).await
    }

    async fn execute_cycle(
        &self,
        scope: &str,
        trigger: &str,
        window: AfddCycleWindow,
    ) -> Result<AfddCycleRecord> {
        let scope_lock = self.scope_lock(scope);
        let Ok(_guard) = scope_lock.try_lock() else {
            anyhow::bail!("AFDD cycle already running for scope {scope}");
        };

        let started_at_utc = Utc::now();
        let payload = json!({
            "mode": "registry",
            "building_id": if scope == "all" { Value::Null } else { json!(scope) },
            "start_utc": window.start_utc.to_rfc3339(),
            "end_utc": window.end_utc.to_rfc3339(),
            "afdd_trigger": trigger,
            "afdd_catch_up": window.catch_up,
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
        let record = AfddCycleRecord {
            scope: scope.to_string(),
            trigger: trigger.to_string(),
            started_at_utc,
            finished_at_utc: Utc::now(),
            start_utc: window.start_utc,
            end_utc: window.end_utc,
            catch_up: window.catch_up,
            ok,
            error: if ok {
                None
            } else {
                error.or_else(|| Some("AFDD registry cycle failed".into()))
            },
            rules_succeeded: result.get("rules_succeeded").and_then(Value::as_u64),
            rules_failed: result.get("rules_failed").and_then(Value::as_u64),
            rules_skipped: result.get("rules_skipped").and_then(Value::as_u64),
        };

        if ok {
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
        let next_due = next_due_at(checkpoint.as_ref(), Utc::now(), &config)?;
        let status = self.status.lock().unwrap();
        Ok(json!({
            "ok": true,
            "config": config,
            "checkpoint": checkpoint,
            "latest_persisted_telemetry_utc": latest_telemetry,
            "next_due_at_utc": if config.mode == AfddMode::Continuous { Some(next_due) } else { None },
            "last_error": status.last_error,
            "recent_cycles": status.recent_cycles,
            "operator_schedule_editable": true,
            "operator_interval_minutes": OPERATOR_INTERVAL_MINUTES,
            "operator_lookback_days": OPERATOR_LOOKBACK_DAYS,
        }))
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

#[derive(Debug, Deserialize)]
pub struct UpdateConfigRequest {
    interval_minutes: u64,
    lookback_days: u64,
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
        .route("/api/afdd/scheduler/run-now", post(scheduler_run_now))
        .route("/api/afdd/scheduler/config", post(scheduler_update_config))
        .layer(Extension(runtime))
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            auth::jwt_middleware,
        ))
        .with_state(state)
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
    Json(body): Json<UpdateConfigRequest>,
) -> Json<Value> {
    let schedule = AfddOperatorSchedule {
        interval_minutes: body.interval_minutes,
        lookback_value: body.lookback_days,
        lookback_unit: AfddLookbackUnit::Days,
    };
    match runtime.update_operator_schedule(schedule) {
        Ok(config) => Json(json!({
            "ok": true,
            "config": config,
        })),
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
}
