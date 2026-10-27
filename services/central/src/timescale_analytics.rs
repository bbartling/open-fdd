//! Timescale analytics for Wave-X Soft-OPEN envelopes (ADR-010).
//!
//! When `OPENFDD_DATABASE_URL` is set, product analytics never open a DataFusion
//! SessionContext — all query_ids dispatch here.

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use fdd_tsdb::Tsdb;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use sqlx::Row;
use std::sync::OnceLock;

use crate::analytics::diagnostic_matrix::{
    diagnostic_rows_json, DiagnosticFlagKind, DiagnosticObservation,
    DIAGNOSTIC_MATRIX_QUERY_VERSION, DIAGNOSTIC_MATRIX_SCHEMA,
};
use crate::analytics::AnalyticsRequest;

/// Validated window + equipment binds for Timescale analytics SQL (before aggregation).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AnalyticsSqlScope {
    pub start: Option<DateTime<Utc>>,
    pub end: Option<DateTime<Utc>>,
    pub equipment_ids: Vec<String>,
}

impl AnalyticsSqlScope {
    pub fn from_request(req: &AnalyticsRequest) -> Self {
        let mut equipment_ids = req.query.equipment_ids.clone().unwrap_or_default();
        equipment_ids.retain(|id| !id.trim().is_empty());
        equipment_ids.sort();
        equipment_ids.dedup();
        Self {
            start: req.query.start,
            end: req.query.end,
            equipment_ids,
        }
    }

    pub fn equipment_bind(&self) -> Option<Vec<String>> {
        if self.equipment_ids.is_empty() {
            None
        } else {
            Some(self.equipment_ids.clone())
        }
    }
}

/// Pinned analytics registry — `pack_version` must match runtime envelopes (no silent drift).
const ANALYTICS_REGISTRY_JSON: &str = include_str!("../../../sql/analytics/registry.json");

/// Soft-OPEN pack version from `sql/analytics/registry.json` (compile-time include).
fn analytics_pack_version() -> &'static str {
    static PACK_VERSION: OnceLock<String> = OnceLock::new();
    PACK_VERSION
        .get_or_init(|| {
            serde_json::from_str::<Value>(ANALYTICS_REGISTRY_JSON)
                .ok()
                .and_then(|v| {
                    v.get("pack_version")
                        .and_then(|x| x.as_str())
                        .map(str::to_string)
                })
                .unwrap_or_else(|| "unknown".into())
        })
        .as_str()
}

/// Pack version plus a content hash of the registry and included SQL bodies.
/// The version string alone is not the cache identity.
pub(crate) fn analytics_sql_pack_identity() -> &'static str {
    static PACK: OnceLock<String> = OnceLock::new();
    PACK.get_or_init(|| {
        let mut hasher = Sha256::new();
        hasher.update(b"analytics-sql-pack-v1");
        for body in [
            ANALYTICS_REGISTRY_JSON,
            MOTOR_WEEKLY_SQL,
            BAS_VS_WEB_SQL,
            ECONOMIZER_SQL,
            PLANT_HEALTH_SQL,
            ROLE_TIMESERIES_SQL,
            MECH_COOLING_SQL,
            SENSOR_STATS_SQL,
            SCHEDULE_SQL,
            SENSOR_FAULTS_SQL,
            SETPOINTS_SQL,
            DIURNAL_SQL,
            TOPOLOGY_SQL,
            METERING_SQL,
            PID_HUNTING_SQL,
            SQL_ANOMALY_SQL,
            MV_CHANGE_POINT_SQL,
            FUEL_DAILY_SQL,
            RCX_PRESET_COVERAGE_SQL,
        ] {
            hasher.update((body.len() as u64).to_le_bytes());
            hasher.update(body.as_bytes());
        }
        format!(
            "{}:{}",
            analytics_pack_version(),
            hex::encode(hasher.finalize())
        )
    })
    .as_str()
}

/// Soft-OPEN: SQL body from `sql/analytics` pack (hash-pinned).
/// Sample queries bind `$1` site + `$2`/`$3` window + `$4` equipment_ids.
/// Inventory (`plant_health`) binds `$1` building + `$2` equipment_ids only.
const MOTOR_WEEKLY_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/motor_weekly_runtime.sql");
const BAS_VS_WEB_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/bas_vs_web_oat.sql");
const ECONOMIZER_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/economizer_deltas.sql");
const PLANT_HEALTH_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/plant_health_inventory.sql");
const ROLE_TIMESERIES_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/role_timeseries.sql");
const MECH_COOLING_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/mechanical_cooling_oat_bins.sql");
const SENSOR_STATS_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/sensor_stats.sql");
const SCHEDULE_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/schedule_occupancy.sql");
const SENSOR_FAULTS_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/sensor_faults_staleness.sql");
const SETPOINTS_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/setpoints_snapshot.sql");
const DIURNAL_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/diurnal_hourly.sql");
const TOPOLOGY_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/topology_equipment.sql");
const METERING_SQL: &str = include_str!("../../../sql/analytics/postgres/queries/metering_kwh.sql");
const PID_HUNTING_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/pid_hunting_proxy.sql");
const SQL_ANOMALY_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/sql_anomaly_zscore.sql");
const SQL_ANOMALY_SERIES_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/sql_anomaly_series.sql");
const ANOMALY_EVENT_LIMIT: i64 = 2000;
const MV_CHANGE_POINT_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/mv_change_point_daily.sql");
const FUEL_DAILY_SQL: &str = include_str!("../../../sql/analytics/postgres/queries/fuel_daily.sql");
const RCX_PRESET_COVERAGE_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/rcx_preset_role_coverage.sql");

fn with_scope_meta(mut env: Value, scope: &AnalyticsSqlScope) -> Value {
    if let Some(obj) = env.as_object_mut() {
        obj.insert(
            "window_start".to_string(),
            json!(scope
                .start
                .map(|t| t.to_rfc3339_opts(chrono::SecondsFormat::Secs, true))),
        );
        obj.insert(
            "window_end".to_string(),
            json!(scope
                .end
                .map(|t| t.to_rfc3339_opts(chrono::SecondsFormat::Secs, true))),
        );
        obj.insert("equipment_ids".to_string(), json!(scope.equipment_ids));
    }
    env
}

fn economizer_dt_min(raw: Option<f64>) -> f64 {
    match raw {
        Some(value) if value.is_finite() => value.max(0.0),
        _ => crate::analytics::economizer::DEFAULT_DT_MIN_F,
    }
}

fn empty_row_reason(query_id: &str, dt_min_f: Option<f64>) -> String {
    match query_id {
        "economizer" => {
            let dt = dt_min_f.unwrap_or(crate::analytics::economizer::DEFAULT_DT_MIN_F);
            format!(
                "no qualified economizer samples: fan-on proof, |OAT−RAT| ≥ {dt:.0}°F, and a measured MAT are required; off-fan, low-delta, and missing-MAT rows are not qualified"
            )
        }
        "runtime" => "no motor weekly runtime rows for this site and window".into(),
        "mechanical-cooling" => {
            "no mechanical-cooling outdoor-air bins: compressor or chiller status with outdoor air is required"
                .into()
        }
        "bas-vs-web-oat" => {
            "no coincident BAS and web outdoor-air samples for this site and window".into()
        }
        other => format!("no rows for {other}"),
    }
}

/// Row envelopes stay row-only. An empty result names the missing proof
/// instead of a silent success.
fn finish_row_envelope(
    query_id: &str,
    building_id: &str,
    rows: Vec<Value>,
    scope: &AnalyticsSqlScope,
    empty_key: &str,
    dt_min_f: Option<f64>,
) -> Value {
    let warnings = if rows.is_empty() {
        vec![empty_row_reason(empty_key, dt_min_f)]
    } else {
        Vec::new()
    };
    let mut env = with_scope_meta(envelope(query_id, building_id, rows), scope);
    if let Some(obj) = env.as_object_mut() {
        if !warnings.is_empty() {
            obj.insert("warnings".to_string(), json!(warnings));
        }
        if let Some(dt) = dt_min_f {
            obj.insert("dt_min_f".to_string(), json!(dt));
        }
    }
    env
}

pub async fn motor_weekly_runtime(
    tsdb: &Tsdb,
    building_id: &str,
    scope: &AnalyticsSqlScope,
) -> Result<Value> {
    // Soft-OPEN: bind requested window/equipment before aggregation (not building-only).
    let rows = sqlx::query(MOTOR_WEEKLY_SQL)
        .bind(building_id)
        .bind(scope.start)
        .bind(scope.end)
        .bind(scope.equipment_bind())
        .fetch_all(tsdb.pool())
        .await
        .context("motor_weekly_runtime")?;

    let mut out = Vec::new();
    for r in rows {
        let runtime = r
            .try_get::<f64, _>("runtime_hours")
            .ok()
            .or_else(|| r.try_get::<f64, _>("run_hours").ok());
        let equipment_id = r.try_get::<String, _>("equipment_id").unwrap_or_default();
        let signal = r.try_get::<String, _>("signal").ok();
        let label = signal
            .as_ref()
            .map(|sig| format!("{equipment_id} · {}", sig.replace('_', "-")));
        out.push(json!({
            "equipment_id": equipment_id,
            "kind": r.try_get::<String, _>("kind").unwrap_or_else(|_| "motor".into()),
            "signal": signal,
            "label": label,
            "plant_group": r.try_get::<String, _>("plant_group").ok(),
            "week_start": r.try_get::<chrono::DateTime<chrono::Utc>, _>("week_start")
                .ok()
                .map(|t| t.to_rfc3339()),
            "week_label": r.try_get::<String, _>("week_label").ok(),
            "run_hours": runtime,
            "runtime_hours": runtime,
            "n_observations": r.try_get::<i64, _>("n_observations").ok(),
            "partial_week": r.try_get::<bool, _>("partial_week").ok(),
        }));
    }
    let body = finish_row_envelope(
        "motor-weekly-runtime",
        building_id,
        out,
        scope,
        "runtime",
        None,
    );
    Ok(stamp_overview_dto(tsdb, building_id, scope, body).await)
}

pub async fn bas_vs_web_oat(
    tsdb: &Tsdb,
    building_id: &str,
    scope: &AnalyticsSqlScope,
) -> Result<Value> {
    // Soft-OPEN: bind requested window/equipment before aggregation (not building-only).
    let rows = sqlx::query(BAS_VS_WEB_SQL)
        .bind(building_id)
        .bind(scope.start)
        .bind(scope.end)
        .bind(scope.equipment_bind())
        .fetch_all(tsdb.pool())
        .await
        .context("bas_vs_web_oat")?;

    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "ts": r.try_get::<chrono::DateTime<chrono::Utc>, _>("ts").ok().map(|t| t.to_rfc3339()),
            "equipment_id": r.try_get::<String, _>("equipment_id").ok(),
            "bas_oa_t": r.try_get::<f64, _>("bas_oa_t").ok(),
            "web_oa_t": r.try_get::<f64, _>("web_oa_t").ok(),
            "delta_f": r.try_get::<f64, _>("delta_f").ok(),
        }));
    }
    let body = finish_row_envelope(
        "bas-vs-web-oat",
        building_id,
        out,
        scope,
        "bas-vs-web-oat",
        None,
    );
    Ok(stamp_overview_dto(tsdb, building_id, scope, body).await)
}

pub async fn role_timeseries(
    tsdb: &Tsdb,
    building_id: &str,
    role_suffix: &str,
    query_id: &str,
    limit: i64,
    scope: &AnalyticsSqlScope,
) -> Result<Value> {
    // Soft-OPEN: bind requested window/equipment before LIMIT (not building-only).
    let rows = sqlx::query(ROLE_TIMESERIES_SQL)
        .bind(building_id)
        .bind(scope.start)
        .bind(scope.end)
        .bind(scope.equipment_bind())
        .bind(role_suffix)
        .bind(limit)
        .fetch_all(tsdb.pool())
        .await
        .with_context(|| format!("role_timeseries {role_suffix}"))?;

    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "ts": r.try_get::<chrono::DateTime<chrono::Utc>, _>("ts").ok().map(|t| t.to_rfc3339()),
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "openfdd_key": r.try_get::<String, _>("openfdd_key").unwrap_or_default(),
            "val": r.try_get::<f64, _>("val").ok(),
        }));
    }
    Ok(with_scope_meta(envelope(query_id, building_id, out), scope))
}

pub async fn mechanical_cooling_oat_bins(
    tsdb: &Tsdb,
    building_id: &str,
    scope: &AnalyticsSqlScope,
) -> Result<Value> {
    // Soft-OPEN: bind requested window/equipment before aggregation (not building-only).
    let rows = sqlx::query(MECH_COOLING_SQL)
        .bind(building_id)
        .bind(scope.start)
        .bind(scope.end)
        .bind(scope.equipment_bind())
        .fetch_all(tsdb.pool())
        .await
        .context("mechanical_cooling_oat_bins")?;
    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "kind": r.try_get::<String, _>("kind").unwrap_or_else(|_| "oat_bin".into()),
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "oat_bin": r.try_get::<String, _>("oat_bin").unwrap_or_default(),
            "run_hours": r.try_get::<f64, _>("run_hours").ok(),
        }));
    }
    Ok(finish_row_envelope(
        "mechanical-cooling",
        building_id,
        out,
        scope,
        "mechanical-cooling",
        None,
    ))
}

pub async fn sensor_stats(
    tsdb: &Tsdb,
    building_id: &str,
    scope: &AnalyticsSqlScope,
) -> Result<Value> {
    // Soft-OPEN: bind requested window/equipment before aggregation (not building-only).
    let rows = sqlx::query(SENSOR_STATS_SQL)
        .bind(building_id)
        .bind(scope.start)
        .bind(scope.end)
        .bind(scope.equipment_bind())
        .fetch_all(tsdb.pool())
        .await
        .context("sensor_stats")?;
    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "role": r.try_get::<String, _>("role").unwrap_or_default(),
            "n": r.try_get::<i64, _>("n").ok(),
            "min_val": r.try_get::<f64, _>("min_val").ok(),
            "max_val": r.try_get::<f64, _>("max_val").ok(),
            "avg_val": r.try_get::<f64, _>("avg_val").ok(),
            "stddev_val": r.try_get::<f64, _>("stddev_val").ok(),
            "first_ts": r.try_get::<chrono::DateTime<chrono::Utc>, _>("first_ts")
                .ok()
                .map(|t| t.to_rfc3339()),
            "last_ts": r.try_get::<chrono::DateTime<chrono::Utc>, _>("last_ts")
                .ok()
                .map(|t| t.to_rfc3339()),
        }));
    }
    Ok(with_scope_meta(
        envelope("sensor-stats", building_id, out),
        scope,
    ))
}

pub async fn schedule_occupancy(
    tsdb: &Tsdb,
    building_id: &str,
    scope: &AnalyticsSqlScope,
) -> Result<Value> {
    // Soft-OPEN: bind requested window/equipment before LIMIT (not building-only).
    let rows = sqlx::query(SCHEDULE_SQL)
        .bind(building_id)
        .bind(scope.start)
        .bind(scope.end)
        .bind(scope.equipment_bind())
        .fetch_all(tsdb.pool())
        .await
        .context("schedule_occupancy")?;
    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "ts": r.try_get::<chrono::DateTime<chrono::Utc>, _>("ts").ok().map(|t| t.to_rfc3339()),
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "openfdd_key": r.try_get::<String, _>("openfdd_key").unwrap_or_default(),
            "val": r.try_get::<f64, _>("val").ok(),
        }));
    }
    Ok(with_scope_meta(
        envelope("schedule", building_id, out),
        scope,
    ))
}

pub async fn sensor_faults(
    tsdb: &Tsdb,
    building_id: &str,
    scope: &AnalyticsSqlScope,
) -> Result<Value> {
    // Soft-OPEN: bind requested window/equipment before aggregation (not building-only).
    let rows = sqlx::query(SENSOR_FAULTS_SQL)
        .bind(building_id)
        .bind(scope.start)
        .bind(scope.end)
        .bind(scope.equipment_bind())
        .fetch_all(tsdb.pool())
        .await
        .context("sensor_faults")?;
    let mut observations = Vec::with_capacity(rows.len());
    for r in rows {
        observations.push(DiagnosticObservation {
            equipment_id: r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            role: r.try_get::<String, _>("role").unwrap_or_default(),
            flag: r
                .try_get::<String, _>("fault_flag")
                .unwrap_or_else(|_| "OK".into()),
            n: r.try_get::<i64, _>("n").ok(),
            last_ts: r
                .try_get::<chrono::DateTime<chrono::Utc>, _>("last_ts")
                .ok()
                .map(|t| t.to_rfc3339()),
            min_val: r.try_get::<f64, _>("min_val").ok(),
            max_val: r.try_get::<f64, _>("max_val").ok(),
            avg_val: None,
            stddev_val: r.try_get::<f64, _>("stddev_val").ok(),
        });
    }
    let out = diagnostic_rows_json(building_id, DiagnosticFlagKind::Fault, observations);
    Ok(with_scope_meta(
        diagnostic_envelope("sensor-faults", building_id, out),
        scope,
    ))
}

pub async fn setpoints_snapshot(
    tsdb: &Tsdb,
    building_id: &str,
    scope: &AnalyticsSqlScope,
) -> Result<Value> {
    // Soft-OPEN: bind requested window/equipment before latest-per-role (not building-only).
    let rows = sqlx::query(SETPOINTS_SQL)
        .bind(building_id)
        .bind(scope.start)
        .bind(scope.end)
        .bind(scope.equipment_bind())
        .fetch_all(tsdb.pool())
        .await
        .context("setpoints_snapshot")?;
    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "role": r.try_get::<String, _>("role").unwrap_or_default(),
            "ts": r.try_get::<chrono::DateTime<chrono::Utc>, _>("ts").ok().map(|t| t.to_rfc3339()),
            "setpoint": r.try_get::<f64, _>("setpoint").ok(),
        }));
    }
    Ok(with_scope_meta(
        envelope("setpoints", building_id, out),
        scope,
    ))
}

pub async fn diurnal_hourly(
    tsdb: &Tsdb,
    building_id: &str,
    scope: &AnalyticsSqlScope,
) -> Result<Value> {
    // Soft-OPEN: bind requested window/equipment before aggregation (not building-only).
    let rows = sqlx::query(DIURNAL_SQL)
        .bind(building_id)
        .bind(scope.start)
        .bind(scope.end)
        .bind(scope.equipment_bind())
        .fetch_all(tsdb.pool())
        .await
        .context("diurnal_hourly")?;
    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "role": r.try_get::<String, _>("role").unwrap_or_default(),
            "hour_utc": r.try_get::<i32, _>("hour_utc").ok(),
            "avg_val": r.try_get::<f64, _>("avg_val").ok(),
            "n": r.try_get::<i64, _>("n").ok(),
        }));
    }
    Ok(with_scope_meta(
        envelope("diurnal", building_id, out),
        scope,
    ))
}

pub async fn topology_equipment(
    tsdb: &Tsdb,
    building_id: &str,
    scope: &AnalyticsSqlScope,
) -> Result<Value> {
    // Soft-OPEN: equipment filter + window on sample subqueries (role_count / last_ts).
    let rows = sqlx::query(TOPOLOGY_SQL)
        .bind(building_id)
        .bind(scope.start)
        .bind(scope.end)
        .bind(scope.equipment_bind())
        .fetch_all(tsdb.pool())
        .await
        .context("topology_equipment")?;
    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "equip_type": r.try_get::<Option<String>, _>("equip_type").ok().flatten(),
            "parent_equipment_id": r.try_get::<Option<String>, _>("parent_equipment_id")
                .ok()
                .flatten(),
            "role_count": r.try_get::<i64, _>("role_count").ok(),
            "last_sample_ts": r.try_get::<chrono::DateTime<chrono::Utc>, _>("last_sample_ts")
                .ok()
                .map(|t| t.to_rfc3339()),
        }));
    }
    Ok(with_scope_meta(
        envelope("topology", building_id, out),
        scope,
    ))
}

pub async fn metering_kwh(
    tsdb: &Tsdb,
    building_id: &str,
    scope: &AnalyticsSqlScope,
) -> Result<Value> {
    // Soft-OPEN: bind requested window/equipment before aggregation (not building-only).
    let rows = sqlx::query(METERING_SQL)
        .bind(building_id)
        .bind(scope.start)
        .bind(scope.end)
        .bind(scope.equipment_bind())
        .fetch_all(tsdb.pool())
        .await
        .context("metering_kwh")?;
    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "role": r.try_get::<String, _>("role").unwrap_or_default(),
            "day_utc": r.try_get::<chrono::DateTime<chrono::Utc>, _>("day_utc")
                .ok()
                .map(|t| t.to_rfc3339()),
            "n": r.try_get::<i64, _>("n").ok(),
            "min_val": r.try_get::<f64, _>("min_val").ok(),
            "max_val": r.try_get::<f64, _>("max_val").ok(),
            "avg_val": r.try_get::<f64, _>("avg_val").ok(),
            "delta_val": r.try_get::<f64, _>("delta_val").ok(),
        }));
    }
    Ok(with_scope_meta(
        envelope("metering", building_id, out),
        scope,
    ))
}

pub async fn pid_hunting_proxy(
    tsdb: &Tsdb,
    building_id: &str,
    scope: &AnalyticsSqlScope,
) -> Result<Value> {
    // Soft-OPEN: bind requested window/equipment before aggregation (not building-only).
    let rows = sqlx::query(PID_HUNTING_SQL)
        .bind(building_id)
        .bind(scope.start)
        .bind(scope.end)
        .bind(scope.equipment_bind())
        .fetch_all(tsdb.pool())
        .await
        .context("pid_hunting_proxy")?;
    let mut observations = Vec::with_capacity(rows.len());
    for r in rows {
        observations.push(DiagnosticObservation {
            equipment_id: r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            role: r.try_get::<String, _>("role").unwrap_or_default(),
            flag: r
                .try_get::<String, _>("hunt_flag")
                .unwrap_or_else(|_| "OK".into()),
            n: r.try_get::<i64, _>("n").ok(),
            last_ts: None,
            min_val: None,
            max_val: None,
            avg_val: r.try_get::<f64, _>("avg_val").ok(),
            stddev_val: r.try_get::<f64, _>("stddev_val").ok(),
        });
    }
    let out = diagnostic_rows_json(building_id, DiagnosticFlagKind::Hunt, observations);
    Ok(with_scope_meta(
        diagnostic_envelope("pid-hunting", building_id, out),
        scope,
    ))
}

fn anomaly_series_reason(
    n: i64,
    n_null: i64,
    stddev: Option<f64>,
    window_rows: u32,
) -> &'static str {
    if n == 0 && n_null > 0 {
        return "missing_values";
    }
    let needed = i64::from(window_rows) + 1;
    if n < needed {
        return "short_history";
    }
    match stddev {
        Some(scale) if scale.is_finite() && scale > 0.0 => "scored",
        _ => "constant_history",
    }
}

struct AnomalyCounts {
    n_samples: i64,
    n_scored: i64,
    n_flagged: i64,
    n_ok: i64,
    n_returned: i64,
    truncated: bool,
}

fn anomaly_coverage(
    params: &crate::sql_anomaly::SqlAnomalyParams,
    scope: &AnalyticsSqlScope,
    counts: &AnomalyCounts,
    series: Vec<Value>,
) -> Value {
    let stamp = |ts: Option<DateTime<Utc>>| {
        ts.map(|t| t.to_rfc3339_opts(chrono::SecondsFormat::Secs, true))
    };
    json!({
        "contract": "event-table",
        "semantics": "rolling-prior-window-zscore",
        "method": params.method,
        "window_rows": params.window_rows,
        "z_threshold": params.z_threshold,
        "transition_events": params.transition_events,
        "truncated": counts.truncated,
        "window_start": stamp(scope.start),
        "window_end": stamp(scope.end),
        "n_samples": counts.n_samples,
        "n_scored": counts.n_scored,
        "n_flagged": counts.n_flagged,
        "n_ok": counts.n_ok,
        "n_returned": counts.n_returned,
        "series": series,
    })
}

struct AnomalyBody {
    warnings: Vec<String>,
    rows: Vec<Value>,
    coverage: Value,
    truncated: bool,
}

fn anomaly_envelope(
    building_id: &str,
    scope: &AnalyticsSqlScope,
    params: &crate::sql_anomaly::SqlAnomalyParams,
    query_version: &str,
    body: AnomalyBody,
) -> Value {
    let mut env = with_scope_meta(envelope("sql-anomaly", building_id, body.rows), scope);
    if let Some(obj) = env.as_object_mut() {
        obj.insert("query_version".to_string(), json!(query_version));
        obj.insert("contract".to_string(), json!("event-table"));
        obj.insert(
            "semantics".to_string(),
            json!("rolling-prior-window-zscore"),
        );
        obj.insert("method".to_string(), json!(params.method));
        obj.insert("window_rows".to_string(), json!(params.window_rows));
        obj.insert("z_threshold".to_string(), json!(params.z_threshold));
        obj.insert(
            "transition_events".to_string(),
            json!(params.transition_events),
        );
        obj.insert("truncated".to_string(), json!(body.truncated));
        obj.insert("warnings".to_string(), json!(body.warnings));
        obj.insert("coverage".to_string(), json!(body.coverage));
    }
    env
}

struct ScoredEvent {
    equipment_id: String,
    role: String,
    ts: DateTime<Utc>,
    val: f64,
    avg_val: f64,
    stddev_val: f64,
    z_abs: f64,
    transition: bool,
}

fn anomaly_event_row(event: &ScoredEvent, threshold: f64) -> Value {
    json!({
        "anomaly_flag": "ANOMALY",
        "avg_val": event.avg_val,
        "equipment_id": event.equipment_id,
        "method": "zscore",
        "role": event.role,
        "stddev_val": event.stddev_val,
        "threshold": threshold,
        "transition": event.transition,
        "ts": event.ts.to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
        "val": event.val,
        "z_abs": event.z_abs,
    })
}

/// One event row per flagged sample. `window_rows` is the prior-sample
/// baseline, `z_threshold` is the cutoff, and `transition_events` keeps
/// rising edges only when true.
pub async fn sql_anomaly_zscore(
    tsdb: &Tsdb,
    building_id: &str,
    scope: &AnalyticsSqlScope,
    req: &AnalyticsRequest,
    query_version: &str,
) -> Result<Value> {
    let params = crate::sql_anomaly::params_from_request(req);
    let mut warnings = Vec::new();
    if let Some(warning) = crate::analytics::version_mismatch_warning(
        query_version,
        req.query.query_version.as_deref(),
    ) {
        warnings.push(warning);
    }
    if !crate::sql_anomaly::screening_enabled() {
        warnings
            .push("sql anomaly screening disabled (OPENFDD_SQL_ANOMALY_SCREENING=0)".to_string());
        let counts = AnomalyCounts {
            n_samples: 0,
            n_scored: 0,
            n_flagged: 0,
            n_ok: 0,
            n_returned: 0,
            truncated: false,
        };
        let coverage = anomaly_coverage(&params, scope, &counts, Vec::new());
        return Ok(anomaly_envelope(
            building_id,
            scope,
            &params,
            query_version,
            AnomalyBody {
                warnings,
                rows: Vec::new(),
                coverage,
                truncated: false,
            },
        ));
    }
    if params.method != "zscore" {
        warnings.push(format!(
            "sql-anomaly method '{}' is not supported; the event table uses zscore",
            params.method
        ));
        let counts = AnomalyCounts {
            n_samples: 0,
            n_scored: 0,
            n_flagged: 0,
            n_ok: 0,
            n_returned: 0,
            truncated: false,
        };
        let coverage = anomaly_coverage(&params, scope, &counts, Vec::new());
        return Ok(anomaly_envelope(
            building_id,
            scope,
            &params,
            query_version,
            AnomalyBody {
                warnings,
                rows: Vec::new(),
                coverage,
                truncated: false,
            },
        ));
    }

    let window_rows = i32::try_from(params.window_rows).context("sql-anomaly window_rows")?;
    let fetched = sqlx::query(SQL_ANOMALY_SQL)
        .bind(building_id)
        .bind(scope.start)
        .bind(scope.end)
        .bind(scope.equipment_bind())
        .bind(window_rows)
        .bind(params.z_threshold)
        .bind(params.transition_events)
        .fetch_all(tsdb.pool())
        .await
        .context("sql_anomaly_zscore")?;
    if fetched.is_empty() {
        anyhow::bail!("sql-anomaly event query returned no count row");
    }
    let mut n_scored = 0_i64;
    let mut n_flagged = 0_i64;
    let mut n_ok = 0_i64;
    let mut n_selected = 0_i64;
    let mut rows = Vec::new();
    for (index, row) in fetched.iter().enumerate() {
        if index == 0 {
            n_scored = row.try_get("n_scored").context("sql-anomaly n_scored")?;
            n_flagged = row.try_get("n_flagged").context("sql-anomaly n_flagged")?;
            n_ok = row.try_get("n_ok").context("sql-anomaly n_ok")?;
            n_selected = row
                .try_get("n_selected")
                .context("sql-anomaly n_selected")?;
        }
        let equipment_id: Option<String> = row
            .try_get("equipment_id")
            .context("sql-anomaly equipment_id")?;
        let Some(equipment_id) = equipment_id.filter(|id| !id.is_empty()) else {
            continue;
        };
        let role: String = row.try_get("role").context("sql-anomaly role")?;
        let ts: DateTime<Utc> = row.try_get("ts").context("sql-anomaly ts")?;
        let val: f64 = row.try_get("val").context("sql-anomaly val")?;
        let avg_val: f64 = row.try_get("avg_val").context("sql-anomaly avg_val")?;
        let stddev_val: f64 = row
            .try_get("stddev_val")
            .context("sql-anomaly stddev_val")?;
        let z_abs: f64 = row.try_get("z_abs").context("sql-anomaly z_abs")?;
        let transition: bool = row
            .try_get("transition")
            .context("sql-anomaly transition")?;
        rows.push(anomaly_event_row(
            &ScoredEvent {
                equipment_id,
                role,
                ts,
                val,
                avg_val,
                stddev_val,
                z_abs,
                transition,
            },
            params.z_threshold,
        ));
    }

    let series_rows = sqlx::query(SQL_ANOMALY_SERIES_SQL)
        .bind(building_id)
        .bind(scope.start)
        .bind(scope.end)
        .bind(scope.equipment_bind())
        .fetch_all(tsdb.pool())
        .await
        .context("sql_anomaly_series")?;
    let mut series = Vec::with_capacity(series_rows.len());
    let mut n_samples = 0_i64;
    for row in &series_rows {
        let equipment_id: String = row
            .try_get("equipment_id")
            .context("sql-anomaly series equipment_id")?;
        let role: String = row.try_get("role").context("sql-anomaly series role")?;
        let n: i64 = row.try_get("n").context("sql-anomaly series n")?;
        let n_null: i64 = row.try_get("n_null").context("sql-anomaly series n_null")?;
        let stddev: Option<f64> = row
            .try_get("stddev_val")
            .context("sql-anomaly series stddev")?;
        n_samples += n;
        series.push(json!({
            "equipment_id": equipment_id,
            "role": role,
            "reason": anomaly_series_reason(n, n_null, stddev, params.window_rows),
            "n": n,
            "n_null": n_null,
        }));
    }
    if n_samples == 0 {
        warnings.push("no screened samples in this window".to_string());
    }
    let n_returned = i64::try_from(rows.len()).context("sql-anomaly row count")?;
    let truncated = n_selected > ANOMALY_EVENT_LIMIT;
    let counts = AnomalyCounts {
        n_samples,
        n_scored,
        n_flagged,
        n_ok,
        n_returned,
        truncated,
    };
    let coverage = anomaly_coverage(&params, scope, &counts, series);
    Ok(anomaly_envelope(
        building_id,
        scope,
        &params,
        query_version,
        AnomalyBody {
            warnings,
            rows,
            coverage,
            truncated,
        },
    ))
}

pub async fn mv_change_point_daily(
    tsdb: &Tsdb,
    building_id: &str,
    scope: &AnalyticsSqlScope,
) -> Result<Value> {
    // Soft-OPEN: bind requested window/equipment before aggregation (not building-only).
    let rows = sqlx::query(MV_CHANGE_POINT_SQL)
        .bind(building_id)
        .bind(scope.start)
        .bind(scope.end)
        .bind(scope.equipment_bind())
        .fetch_all(tsdb.pool())
        .await
        .context("mv_change_point_daily")?;
    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "role": r.try_get::<String, _>("role").unwrap_or_default(),
            "day_utc": r.try_get::<chrono::DateTime<chrono::Utc>, _>("day_utc")
                .ok()
                .map(|t| t.to_rfc3339()),
            "avg_val": r.try_get::<f64, _>("avg_val").ok(),
            "prev_avg": r.try_get::<f64, _>("prev_avg").ok(),
            "delta_avg": r.try_get::<f64, _>("delta_avg").ok(),
            "n": r.try_get::<i64, _>("n").ok(),
            "change_flag": r.try_get::<String, _>("change_flag").unwrap_or_else(|_| "STABLE".into()),
        }));
    }
    Ok(with_scope_meta(
        envelope("mv-change-point", building_id, out),
        scope,
    ))
}

pub async fn fuel_daily(
    tsdb: &Tsdb,
    building_id: &str,
    scope: &AnalyticsSqlScope,
) -> Result<Value> {
    // Soft-OPEN: bind requested window/equipment before aggregation (not building-only).
    let rows = sqlx::query(FUEL_DAILY_SQL)
        .bind(building_id)
        .bind(scope.start)
        .bind(scope.end)
        .bind(scope.equipment_bind())
        .fetch_all(tsdb.pool())
        .await
        .context("fuel_daily")?;
    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "role": r.try_get::<String, _>("role").unwrap_or_default(),
            "day_utc": r.try_get::<chrono::DateTime<chrono::Utc>, _>("day_utc")
                .ok()
                .map(|t| t.to_rfc3339()),
            "n": r.try_get::<i64, _>("n").ok(),
            "min_val": r.try_get::<f64, _>("min_val").ok(),
            "max_val": r.try_get::<f64, _>("max_val").ok(),
            "avg_val": r.try_get::<f64, _>("avg_val").ok(),
            "delta_val": r.try_get::<f64, _>("delta_val").ok(),
        }));
    }
    Ok(with_scope_meta(envelope("fuel", building_id, out), scope))
}

pub async fn rcx_preset_role_coverage(
    tsdb: &Tsdb,
    building_id: &str,
    scope: &AnalyticsSqlScope,
) -> Result<Value> {
    // Soft-OPEN: bind requested window/equipment before aggregation (not building-only).
    let rows = sqlx::query(RCX_PRESET_COVERAGE_SQL)
        .bind(building_id)
        .bind(scope.start)
        .bind(scope.end)
        .bind(scope.equipment_bind())
        .fetch_all(tsdb.pool())
        .await
        .context("rcx_preset_role_coverage")?;
    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "role": r.try_get::<String, _>("role").unwrap_or_default(),
            "n": r.try_get::<i64, _>("n").ok(),
            "first_ts": r.try_get::<chrono::DateTime<chrono::Utc>, _>("first_ts")
                .ok()
                .map(|t| t.to_rfc3339()),
            "last_ts": r.try_get::<chrono::DateTime<chrono::Utc>, _>("last_ts")
                .ok()
                .map(|t| t.to_rfc3339()),
        }));
    }
    Ok(with_scope_meta(
        envelope("rcx-preset-coverage", building_id, out),
        scope,
    ))
}

pub async fn economizer_deltas(
    tsdb: &Tsdb,
    building_id: &str,
    scope: &AnalyticsSqlScope,
    dt_min_f: f64,
) -> Result<Value> {
    let dt_min = economizer_dt_min(Some(dt_min_f));
    // Soft-OPEN: bind requested window/equipment and the |OAT−RAT| gate before aggregation.
    let rows = sqlx::query(ECONOMIZER_SQL)
        .bind(building_id)
        .bind(scope.start)
        .bind(scope.end)
        .bind(scope.equipment_bind())
        .bind(dt_min)
        .fetch_all(tsdb.pool())
        .await
        .context("economizer_deltas")?;

    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "ts": r.try_get::<chrono::DateTime<chrono::Utc>, _>("ts").ok().map(|t| t.to_rfc3339()),
            "equipment_id": r.try_get::<Option<String>, _>("equipment_id").ok().flatten(),
            "oa_t": r.try_get::<f64, _>("oa_t").ok(),
            "rat": r.try_get::<f64, _>("rat").ok(),
            "mat": r.try_get::<f64, _>("mat").ok(),
            "sat": r.try_get::<f64, _>("sat").ok(),
            "oa_damper_pct": r.try_get::<f64, _>("oa_damper_pct").ok(),
            "delta_or_f": r.try_get::<f64, _>("delta_or_f").ok(),
            "delta_mr_f": r.try_get::<f64, _>("delta_mr_f").ok(),
            "mat_resid_f": r.try_get::<Option<f64>, _>("mat_resid_f").ok().flatten(),
            "fan_on": r.try_get::<bool, _>("fan_on").unwrap_or(false),
            "identifiable": r.try_get::<bool, _>("identifiable").unwrap_or(false),
        }));
    }
    Ok(finish_row_envelope(
        "economizer",
        building_id,
        out,
        scope,
        "economizer",
        Some(dt_min),
    ))
}

struct CatalogFields {
    description: Option<String>,
    equipment_kinds: Option<Vec<String>>,
    required_roles: Option<Vec<String>>,
    optional_roles: Option<Vec<String>>,
    applicability: &'static str,
}

fn catalog_fields_from_spec(spec: &fdd_rules::RuleSpec) -> CatalogFields {
    let applicability = if spec.equipment_kinds.is_empty() {
        "all"
    } else {
        "typed"
    };
    CatalogFields {
        description: Some(spec.description.clone()),
        equipment_kinds: Some(spec.equipment_kinds.clone()),
        required_roles: Some(spec.required_roles.clone()),
        optional_roles: Some(spec.optional_roles.clone()),
        applicability,
    }
}

/// Null columns are unknown. An explicit empty kind list applies to every type.
fn catalog_fields_from_columns(
    kinds: Option<Vec<String>>,
    required: Option<Vec<String>>,
    optional: Option<Vec<String>>,
) -> CatalogFields {
    match (kinds, required, optional) {
        (Some(kinds), Some(required), Some(optional)) => CatalogFields {
            applicability: if kinds.is_empty() { "all" } else { "typed" },
            description: None,
            equipment_kinds: Some(kinds),
            required_roles: Some(required),
            optional_roles: Some(optional),
        },
        _ => CatalogFields {
            description: None,
            equipment_kinds: None,
            required_roles: None,
            optional_roles: None,
            applicability: "unknown",
        },
    }
}

fn text_array(row: &sqlx::postgres::PgRow, column: &str) -> Option<Vec<String>> {
    row.try_get::<Option<Vec<String>>, _>(column).ok().flatten()
}

const CATALOGUE_VERSION_KEY: &str = "fdd_rule_catalogue_version";

/// Serializes catalogue writers only. Schema migration keeps its own advisory
/// key so a rules read does not queue behind `CREATE TABLE`, and a migration
/// does not wait on the catalogue.
const CATALOGUE_ADVISORY_LOCK_KEY: i64 = 4_040_530_042;

const CATALOGUE_DDL: &[&str] = &[
    r#"CREATE TABLE IF NOT EXISTS fdd_rule_registry (
      rule_id text PRIMARY KEY,
      sql_file text NOT NULL,
      title text,
      equipment_kinds text[],
      required_roles text[],
      optional_roles text[],
      parity_status text,
      enabled boolean NOT NULL DEFAULT true,
      detail jsonb
    )"#,
    "ALTER TABLE fdd_rule_registry ADD COLUMN IF NOT EXISTS title text",
    "ALTER TABLE fdd_rule_registry ADD COLUMN IF NOT EXISTS equipment_kinds text[]",
    "ALTER TABLE fdd_rule_registry ADD COLUMN IF NOT EXISTS required_roles text[]",
    "ALTER TABLE fdd_rule_registry ADD COLUMN IF NOT EXISTS optional_roles text[]",
    "ALTER TABLE fdd_rule_registry ADD COLUMN IF NOT EXISTS parity_status text",
    "ALTER TABLE fdd_rule_registry ADD COLUMN IF NOT EXISTS enabled boolean NOT NULL DEFAULT true",
    "ALTER TABLE fdd_rule_registry ADD COLUMN IF NOT EXISTS detail jsonb",
    r#"CREATE TABLE IF NOT EXISTS seed_meta (
      key text PRIMARY KEY,
      value text NOT NULL,
      updated_at timestamptz NOT NULL DEFAULT now()
    )"#,
];

fn pack_detail(version: &str) -> Value {
    json!({
        "catalogue_source": "pack",
        "pack_version": version,
        "removed": false,
        "overrides": {},
    })
}

async fn ensure_catalogue_schema(tx: &mut sqlx::Transaction<'_, sqlx::Postgres>) -> Result<()> {
    for statement in CATALOGUE_DDL {
        sqlx::query(statement)
            .execute(&mut **tx)
            .await
            .with_context(|| {
                format!(
                    "rule catalogue schema: {}",
                    statement.chars().take(60).collect::<String>()
                )
            })?;
    }
    Ok(())
}

async fn read_catalogue_rows(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
) -> Result<Vec<open_fdd_edge_prototype::fdd::registry_api::CatalogueExisting>> {
    let rows =
        sqlx::query("SELECT rule_id, enabled, detail FROM fdd_rule_registry ORDER BY rule_id")
            .fetch_all(&mut **tx)
            .await
            .context("rule catalogue unavailable: read fdd_rule_registry")?;
    let mut existing = Vec::with_capacity(rows.len());
    for row in &rows {
        let rule_id: String = row
            .try_get("rule_id")
            .context("rule catalogue unavailable: rule_id")?;
        let enabled: bool = row
            .try_get("enabled")
            .context("rule catalogue unavailable: enabled")?;
        let detail: Option<Value> = row
            .try_get("detail")
            .context("rule catalogue unavailable: detail")?;
        let parsed =
            open_fdd_edge_prototype::fdd::registry_api::catalogue_detail_from_json(detail.as_ref());
        existing.push(
            open_fdd_edge_prototype::fdd::registry_api::CatalogueExisting {
                rule_id,
                enabled,
                catalogue_source: parsed.catalogue_source,
                pack_version: parsed.pack_version,
                removed: parsed.removed,
                overrides: parsed.overrides,
            },
        );
    }
    Ok(existing)
}

fn load_catalogue_pack() -> Result<fdd_rules::RuleRegistry> {
    let root = crate::timescale_product::sql_root_for_registry();
    let reg = fdd_rules::load_registry(&root)
        .with_context(|| format!("rule catalogue unavailable: {}", root.display()))?;
    if reg.rules.is_empty() {
        anyhow::bail!(
            "rule catalogue unavailable: pack at {} has no rules",
            root.display()
        );
    }
    Ok(reg)
}

fn expected_catalogue_version(reg: &fdd_rules::RuleRegistry) -> String {
    open_fdd_edge_prototype::fdd::registry_api::plan_catalogue_reconcile(&reg.rules, &[])
        .catalogue_version
}

async fn stored_catalogue_version(pool: &sqlx::PgPool) -> Result<Option<String>> {
    let ready: bool = sqlx::query_scalar(
        "SELECT to_regclass('fdd_rule_registry') IS NOT NULL AND to_regclass('seed_meta') IS NOT NULL",
    )
    .fetch_one(pool)
    .await
    .context("rule catalogue unavailable: version")?;
    if !ready {
        return Ok(None);
    }
    sqlx::query_scalar("SELECT value FROM seed_meta WHERE key = $1")
        .bind(CATALOGUE_VERSION_KEY)
        .fetch_optional(pool)
        .await
        .context("rule catalogue unavailable: version")
}

/// Startup entry. One idempotent reconcile after schema apply, before the
/// listener accepts rules requests. No database URL skips it. A database that
/// cannot be reached does not block boot; the rules API still fails visibly.
pub(crate) async fn reconcile_catalogue_on_startup() -> Result<()> {
    if !crate::timescale_historian::historian_is_timescale() {
        return Ok(());
    }
    let url = std::env::var("OPENFDD_DATABASE_URL").unwrap_or_default();
    if url.trim().is_empty() {
        return Ok(());
    }
    let tsdb = match fdd_tsdb::Tsdb::connect_from_env().await {
        Ok(tsdb) => tsdb,
        Err(err) => {
            tracing::warn!(
                %err,
                "rule catalogue startup left unchanged; database unreachable"
            );
            return Ok(());
        }
    };
    let version = reconcile_catalogue_on_startup_with(&tsdb).await?;
    tracing::info!(catalogue_version = %version, "rule catalogue reconciled");
    Ok(())
}

/// Same reconcile `reconcile_catalogue_on_startup` runs, against a caller pool.
pub(crate) async fn reconcile_catalogue_on_startup_with(tsdb: &Tsdb) -> Result<String> {
    reconcile_rule_catalogue(tsdb).await
}

/// Insert or refresh the shipped rule pack. Operator `enabled` and `overrides`
/// stay. Pack rules that disappeared are marked removed and kept.
/// Writers take one transaction advisory lock so concurrent startups cannot
/// insert the same rule twice or pile DDL locks.
pub(crate) async fn reconcile_rule_catalogue(tsdb: &Tsdb) -> Result<String> {
    let reg = load_catalogue_pack()?;
    let mut tx = tsdb
        .pool()
        .begin()
        .await
        .context("rule catalogue unavailable: begin")?;
    sqlx::query("SELECT pg_advisory_xact_lock($1)")
        .bind(CATALOGUE_ADVISORY_LOCK_KEY)
        .execute(&mut *tx)
        .await
        .context("rule catalogue unavailable: lock")?;
    ensure_catalogue_schema(&mut tx).await?;
    let existing = read_catalogue_rows(&mut tx).await?;
    let plan =
        open_fdd_edge_prototype::fdd::registry_api::plan_catalogue_reconcile(&reg.rules, &existing);
    for upsert in &plan.upserts {
        sqlx::query(
            r#"
            INSERT INTO fdd_rule_registry (
              rule_id, sql_file, title, equipment_kinds, required_roles, optional_roles,
              parity_status, enabled, detail
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, true, $8)
            ON CONFLICT (rule_id) DO UPDATE SET
              sql_file = EXCLUDED.sql_file,
              title = EXCLUDED.title,
              equipment_kinds = EXCLUDED.equipment_kinds,
              required_roles = EXCLUDED.required_roles,
              optional_roles = EXCLUDED.optional_roles,
              parity_status = EXCLUDED.parity_status,
              detail = (
                COALESCE(fdd_rule_registry.detail, '{}'::jsonb) || EXCLUDED.detail
              ) || jsonb_build_object(
                'overrides',
                CASE
                  WHEN jsonb_typeof(fdd_rule_registry.detail->'overrides') = 'object'
                  THEN fdd_rule_registry.detail->'overrides'
                  ELSE '{}'::jsonb
                END
              )
            WHERE fdd_rule_registry.sql_file IS DISTINCT FROM EXCLUDED.sql_file
               OR fdd_rule_registry.title IS DISTINCT FROM EXCLUDED.title
               OR fdd_rule_registry.equipment_kinds IS DISTINCT FROM EXCLUDED.equipment_kinds
               OR fdd_rule_registry.required_roles IS DISTINCT FROM EXCLUDED.required_roles
               OR fdd_rule_registry.optional_roles IS DISTINCT FROM EXCLUDED.optional_roles
               OR fdd_rule_registry.parity_status IS DISTINCT FROM EXCLUDED.parity_status
               OR COALESCE(fdd_rule_registry.detail->>'pack_version', '')
                    IS DISTINCT FROM COALESCE(EXCLUDED.detail->>'pack_version', '')
               OR COALESCE(fdd_rule_registry.detail->>'catalogue_source', '')
                    IS DISTINCT FROM 'pack'
               OR COALESCE(fdd_rule_registry.detail->>'removed', 'false')
                    IS DISTINCT FROM 'false'
            "#,
        )
        .bind(&upsert.rule_id)
        .bind(&upsert.sql_file)
        .bind(&upsert.title)
        .bind(&upsert.equipment_kinds)
        .bind(&upsert.required_roles)
        .bind(&upsert.optional_roles)
        .bind(&upsert.parity_status)
        .bind(pack_detail(&upsert.pack_version))
        .execute(&mut *tx)
        .await
        .with_context(|| format!("rule catalogue upsert {}", upsert.rule_id))?;
    }
    if !plan.removed_rule_ids.is_empty() {
        sqlx::query(
            r#"
            UPDATE fdd_rule_registry
            SET detail = jsonb_set(
              COALESCE(detail, '{}'::jsonb),
              '{removed}',
              'true'::jsonb,
              true
            )
            WHERE rule_id = ANY($1::text[])
              AND COALESCE(detail->>'removed', 'false') IS DISTINCT FROM 'true'
            "#,
        )
        .bind(&plan.removed_rule_ids)
        .execute(&mut *tx)
        .await
        .context("rule catalogue removed rules")?;
    }
    sqlx::query(
        r#"
        INSERT INTO seed_meta(key, value) VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value, updated_at = now()
        WHERE seed_meta.value IS DISTINCT FROM EXCLUDED.value
        "#,
    )
    .bind(CATALOGUE_VERSION_KEY)
    .bind(&plan.catalogue_version)
    .execute(&mut *tx)
    .await
    .context("rule catalogue version")?;
    tx.commit()
        .await
        .context("rule catalogue unavailable: commit")?;
    Ok(plan.catalogue_version)
}

pub async fn fdd_registry(tsdb: &Tsdb) -> Result<Value> {
    let reg = load_catalogue_pack()?;
    let expected = expected_catalogue_version(&reg);
    // A current version is a read. Reconcile, including its DDL, runs only when
    // startup has not caught up yet so concurrent lists do not lock the catalogue.
    let catalogue_version = match stored_catalogue_version(tsdb.pool()).await? {
        Some(stored) if stored == expected => stored,
        _ => reconcile_rule_catalogue(tsdb).await?,
    };
    let rows = sqlx::query(
        r#"
        SELECT rule_id, sql_file, title, enabled, detail,
               equipment_kinds, required_roles, optional_roles
        FROM fdd_rule_registry
        ORDER BY rule_id
        "#,
    )
    .fetch_all(tsdb.pool())
    .await
    .context("rule catalogue unavailable: list")?;

    let specs: std::collections::HashMap<String, fdd_rules::RuleSpec> = reg
        .rules
        .into_iter()
        .map(|rule| (rule.rule_id.clone(), rule))
        .collect();

    let mut out = Vec::new();
    let mut alias_count = 0usize;
    for r in rows {
        let rule_id: String = r
            .try_get("rule_id")
            .context("rule catalogue unavailable: rule_id")?;
        let detail: Option<Value> = r
            .try_get("detail")
            .context("rule catalogue unavailable: detail")?;
        let parsed =
            open_fdd_edge_prototype::fdd::registry_api::catalogue_detail_from_json(detail.as_ref());
        if parsed.removed {
            continue;
        }
        let spec = specs.get(&rule_id);
        let aliases = spec.map(|rule| rule.aliases.clone()).unwrap_or_default();
        alias_count += aliases.len();
        let fields = match spec {
            Some(rule) => catalog_fields_from_spec(rule),
            None => catalog_fields_from_columns(
                text_array(&r, "equipment_kinds"),
                text_array(&r, "required_roles"),
                text_array(&r, "optional_roles"),
            ),
        };
        let sql_file: String = r
            .try_get("sql_file")
            .context("rule catalogue unavailable: sql_file")?;
        let title: Option<String> = r
            .try_get("title")
            .context("rule catalogue unavailable: title")?;
        let enabled: bool = r
            .try_get("enabled")
            .context("rule catalogue unavailable: enabled")?;
        out.push(json!({
            "rule_id": rule_id,
            "aliases": aliases,
            "sql_file": sql_file,
            "title": title,
            "description": fields.description,
            "equipment_kinds": fields.equipment_kinds,
            "required_roles": fields.required_roles,
            "optional_roles": fields.optional_roles,
            "applicability": fields.applicability,
            "enabled": enabled,
            "pack_version": parsed.pack_version,
            "overrides": parsed.overrides,
            "removed": false,
            "engine": "postgres-sql",
        }));
    }
    Ok(json!({
        "ok": true,
        "engine": "postgres-sql",
        "catalogue_version": catalogue_version,
        "count": out.len(),
        "alias_count": alias_count,
        "rules": out,
    }))
}

#[allow(dead_code)]
pub async fn historian_stats(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let samples = tsdb.sample_count(building_id).await?;
    let rules = tsdb.rule_registry_count().await?;
    Ok(json!({
        "building_id": building_id,
        "engine": "timescale",
        "sample_count": samples,
        "fdd_rule_registry": rules,
        "historian": "timescale-only",
        "dual_write": false,
    }))
}

/// Sample identity on an Overview DTO. Not the telemetry write revision.
struct OverviewFreshness {
    stale: bool,
    watermark: Option<String>,
    generation: Option<String>,
}

fn overview_freshness_unavailable() -> OverviewFreshness {
    OverviewFreshness {
        stale: true,
        watermark: None,
        generation: None,
    }
}

fn overview_freshness_known(
    building_id: &str,
    order: u64,
    utc: &str,
    coverage: &str,
) -> OverviewFreshness {
    OverviewFreshness {
        stale: false,
        watermark: (!utc.is_empty()).then(|| utc.to_string()),
        generation: Some(sample_generation(building_id, order, utc, coverage)),
    }
}

fn sample_generation(building_id: &str, order: u64, utc: &str, coverage: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"overview-sample-generation-v1");
    hasher.update([0]);
    hasher.update(building_id.as_bytes());
    hasher.update([0]);
    hasher.update(order.to_le_bytes());
    hasher.update([0]);
    hasher.update(utc.as_bytes());
    hasher.update([0]);
    hasher.update(coverage.as_bytes());
    hex::encode(hasher.finalize())
}

fn apply_overview_freshness(mut body: Value, freshness: &OverviewFreshness) -> Value {
    let Some(obj) = body.as_object_mut() else {
        return body;
    };
    obj.insert("stale".to_string(), json!(freshness.stale));
    obj.insert("watermark".to_string(), json!(freshness.watermark));
    obj.insert("generation".to_string(), json!(freshness.generation));
    body
}

/// Attach the latest sample time this DTO used. A failed read is stale and
/// does not invent a timestamp or a generation.
async fn stamp_overview_dto(
    tsdb: &Tsdb,
    building_id: &str,
    scope: &AnalyticsSqlScope,
    body: Value,
) -> Value {
    let input = crate::timescale_product::read_analytics_cache_input_from(
        tsdb,
        building_id,
        scope.start,
        scope.end,
        &scope.equipment_ids,
    )
    .await;
    let freshness = match input.watermark {
        Ok(watermark) => overview_freshness_known(
            building_id,
            watermark.order,
            &watermark.utc,
            &watermark.coverage,
        ),
        Err(reason) => {
            tracing::warn!(%reason, "overview watermark unavailable");
            overview_freshness_unavailable()
        }
    };
    apply_overview_freshness(body, &freshness)
}

fn envelope(query_id: &str, building_id: &str, rows: Vec<Value>) -> Value {
    json!({
        "query_id": query_id,
        "building_id": building_id,
        "engine": "timescale-sql",
        "analytics_pack": "openfdd-analytics-sql-v1",
        "pack_version": analytics_pack_version(),
        "rows": rows,
    })
}

fn diagnostic_envelope(query_id: &str, building_id: &str, rows: Vec<Value>) -> Value {
    let mut env = envelope(query_id, building_id, rows);
    if let Some(obj) = env.as_object_mut() {
        obj.insert(
            "schema_version".to_string(),
            json!(DIAGNOSTIC_MATRIX_SCHEMA),
        );
        obj.insert(
            "query_version".to_string(),
            json!(DIAGNOSTIC_MATRIX_QUERY_VERSION),
        );
        obj.insert("site_id".to_string(), json!(building_id));
        obj.insert("warnings".to_string(), json!(Vec::<String>::new()));
    }
    env
}

/// Convert Timescale dispatch JSON into a cacheable [`AnalyticsEnvelope`].
pub fn envelope_from_dispatch_value(
    query_version: &str,
    req: &AnalyticsRequest,
    value: Value,
) -> crate::analytics::AnalyticsEnvelope {
    use crate::analytics::{finalize_historian, AnalyticsEnvelope, SCHEMA_VERSION};
    use chrono::Utc;

    if let Ok(env) = serde_json::from_value::<AnalyticsEnvelope>(value.clone()) {
        return finalize_historian(req, env, query_version);
    }
    let obj = value.as_object().cloned().unwrap_or_default();
    let rows = obj
        .get("rows")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().cloned().collect())
        .unwrap_or_default();
    let equipment = obj
        .get("equipment")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().cloned().collect())
        .unwrap_or_default();
    let points = obj
        .get("points")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().cloned().collect())
        .unwrap_or_default();
    let skipped = obj
        .get("skipped")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().cloned().collect())
        .unwrap_or_default();
    let warnings = obj
        .get("warnings")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|w| w.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    let coverage = obj.get("coverage").cloned();
    let engine = obj
        .get("engine")
        .and_then(|v| v.as_str())
        .unwrap_or("timescale-sql")
        .to_string();
    let schema_version = obj
        .get("schema_version")
        .and_then(|v| v.as_str())
        .unwrap_or(SCHEMA_VERSION)
        .to_string();
    let generated_at = obj
        .get("generated_at")
        .and_then(|v| v.as_str())
        .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
        .map(|t| t.with_timezone(&Utc))
        .unwrap_or_else(Utc::now);
    let qv = obj
        .get("query_version")
        .and_then(|v| v.as_str())
        .unwrap_or(query_version);
    let mut env = AnalyticsEnvelope {
        schema_version,
        query_version: qv.to_string(),
        job_id: req.query.job_id.clone(),
        run_id: req.query.run_id.clone(),
        input_fingerprint: None,
        generated_at,
        engine,
        coverage,
        warnings,
        rows,
        equipment,
        points,
        skipped,
    };
    let dispatch_meta_keys = [
        "query_id",
        "building_id",
        "note",
        "sample_count",
        "pack_version",
        "analytics_pack",
    ];
    let has_meta = dispatch_meta_keys.iter().any(|key| obj.contains_key(*key));
    if has_meta {
        let mut cov = env
            .coverage
            .and_then(|v| v.as_object().cloned())
            .unwrap_or_default();
        for key in dispatch_meta_keys {
            if let Some(v) = obj.get(key) {
                cov.insert(key.to_string(), v.clone());
            }
        }
        env.coverage = Some(Value::Object(cov));
    }
    finalize_historian(req, env, query_version)
}

fn building_from(
    req: &AnalyticsRequest,
) -> Result<String, (axum::http::StatusCode, axum::Json<Value>)> {
    match req
        .query
        .building_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        Some(id) => Ok(id.to_string()),
        None => Err((
            axum::http::StatusCode::BAD_REQUEST,
            axum::Json(json!({
                "ok": false,
                "error": "building_id is required",
                "engine": "timescale-sql",
            })),
        )),
    }
}

/// Universal product dispatch — never calls DataFusion.
pub async fn respond_query(
    query_id: &str,
    query_version: &str,
    req: &AnalyticsRequest,
) -> Result<Value, (axum::http::StatusCode, axum::Json<Value>)> {
    let building = building_from(req)?;
    let tsdb = Tsdb::connect_from_env().await.map_err(|e| {
        (
            axum::http::StatusCode::SERVICE_UNAVAILABLE,
            axum::Json(json!({
                "ok": false,
                "error": e.to_string(),
                "engine": "timescale-sql",
                "hint": "OPENFDD_DATABASE_URL required for Wave-X product path",
            })),
        )
    })?;

    let scope = AnalyticsSqlScope::from_request(req);
    let result = match query_id {
        "runtime" => motor_weekly_runtime(&tsdb, &building, &scope).await,
        "bas-vs-web-oat" => bas_vs_web_oat(&tsdb, &building, &scope).await,
        "ahu-health" => Ok(crate::analytics::plant_health::handle_ahu(req)
            .await
            .to_json()),
        "ahu-temperature-health" => Ok(crate::analytics::plant_health::handle_ahu_temperature(req)
            .await
            .to_json()),
        "ahu-pressure-health" => Ok(crate::analytics::plant_health::handle_ahu_pressure(req)
            .await
            .to_json()),
        "ahu-economizer-health" => Ok(crate::analytics::plant_health::handle_ahu_economizer(req)
            .await
            .to_json()),
        "chiller-health" => Ok(crate::analytics::plant_health::handle_chiller(req)
            .await
            .to_json()),
        "boiler-health" => Ok(crate::analytics::plant_health::handle_boiler(req)
            .await
            .to_json()),
        "hp-health" => Ok(crate::analytics::plant_health::handle_hp(req)
            .await
            .to_json()),
        "zone-other-health" => Ok(crate::analytics::plant_health::handle_zone_other(req)
            .await
            .to_json()),
        "cooling-tower-health" => Ok(crate::analytics::plant_health::handle_cooling_tower(req)
            .await
            .to_json()),
        "vav-health" => Ok(crate::analytics::vav_health::handle_async(req)
            .await
            .to_json()),
        "sensor-health" => crate::analytics::sensor_health::handle_async(req)
            .await
            .map(|env| env.to_json()),
        "economizer" | "rcx-ahu" => {
            economizer_deltas(&tsdb, &building, &scope, economizer_dt_min(req.dt_min_f)).await
        }
        "rcx-vav" => role_timeseries(&tsdb, &building, "zone_t", "rcx-vav", 2000, &scope).await,
        "rcx-chiller" => {
            role_timeseries(
                &tsdb,
                &building,
                "chw_supply_t",
                "rcx-chiller",
                2000,
                &scope,
            )
            .await
        }
        "rcx-boiler" => {
            role_timeseries(&tsdb, &building, "hw_supply_t", "rcx-boiler", 2000, &scope).await
        }
        "equipment-inspect" | "inspect" => {
            // Wide envelope for SPA Inspect (points + coverage), not long sample dump.
            let _ = tsdb;
            match crate::timescale_product::inspect_json(req).await {
                Ok(v) => Ok(v),
                Err(e) => Err(e),
            }
        }
        "mechanical-cooling" => mechanical_cooling_oat_bins(&tsdb, &building, &scope).await,
        "schedule" => schedule_occupancy(&tsdb, &building, &scope).await,
        "sensor-stats" => sensor_stats(&tsdb, &building, &scope).await,
        "sensor-faults" => sensor_faults(&tsdb, &building, &scope).await,
        "setpoints" => setpoints_snapshot(&tsdb, &building, &scope).await,
        "diurnal" => diurnal_hourly(&tsdb, &building, &scope).await,
        "topology" => topology_equipment(&tsdb, &building, &scope).await,
        "metering" => metering_kwh(&tsdb, &building, &scope).await,
        "pid-hunting" => pid_hunting_proxy(&tsdb, &building, &scope).await,
        "sql-anomaly" => sql_anomaly_zscore(&tsdb, &building, &scope, req, query_version).await,
        "mv-change-point" => mv_change_point_daily(&tsdb, &building, &scope).await,
        "fuel" => fuel_daily(&tsdb, &building, &scope).await,
        "rcx-preset-coverage" => rcx_preset_role_coverage(&tsdb, &building, &scope).await,
        other => Ok(json!({
            "query_id": other,
            "building_id": building,
            "engine": "timescale-sql",
            "analytics_pack": "openfdd-analytics-sql-v1",
            "pack_version": analytics_pack_version(),
            "rows": [],
            "note": "Wave-X Timescale dispatch — query SQL port pending; DataFusion disabled",
        })),
    };

    let body = result.map_err(|e| {
        (
            axum::http::StatusCode::INTERNAL_SERVER_ERROR,
            axum::Json(json!({
                "ok": false,
                "error": e.to_string(),
                "engine": "timescale-sql",
            })),
        )
    })?;
    // runtime and bas-vs-web-oat stamp inside their query functions because
    // those routes return the function value directly.
    if matches!(query_id, "runtime" | "bas-vs-web-oat") {
        return Ok(body);
    }
    Ok(stamp_overview_dto(&tsdb, &building, &scope, body).await)
}

#[cfg(test)]
mod pack_version_tests {
    use super::*;
    use chrono::TimeZone;

    fn assert_window_equipment_binds(sql: &str, name: &str) {
        // Regression: building-only $1 was the Soft-OPEN residual — fail closed if lost.
        assert!(
            sql.contains("$2::timestamptz"),
            "{name} SQL must bind window start ($2)"
        );
        assert!(
            sql.contains("$3::timestamptz"),
            "{name} SQL must bind window end ($3)"
        );
        assert!(
            sql.contains("$4::text[]") || sql.contains("ANY ($4)"),
            "{name} SQL must bind equipment_ids ($4)"
        );
    }

    #[test]
    fn economizer_sql_declares_window_and_equipment_binds() {
        assert_window_equipment_binds(ECONOMIZER_SQL, "economizer");
        assert!(
            ECONOMIZER_SQL.contains("$5::double precision"),
            "economizer must bind the |OAT−RAT| minimum"
        );
        assert!(
            ECONOMIZER_SQL.contains("fan_status"),
            "economizer must read fan status"
        );
        assert!(
            ECONOMIZER_SQL.contains("fan_status > 0.05"),
            "missing or off fan status must not qualify"
        );
        assert!(
            ECONOMIZER_SQL.contains("mat IS NOT NULL"),
            "missing MAT must not qualify"
        );
        assert!(
            ECONOMIZER_SQL.contains("abs(oa_t - rat)"),
            "economizer must enforce absolute OAT−RAT"
        );
        assert!(
            ECONOMIZER_SQL.contains("mat_resid_f"),
            "MAT residual is the mixing-model difference"
        );
    }

    #[test]
    fn overview_traffic_sql_declares_window_and_equipment_binds() {
        // Soft-OPEN post-#1258: highest-traffic Overview routes after economizer.
        assert_window_equipment_binds(BAS_VS_WEB_SQL, "bas-vs-web-oat");
        assert_window_equipment_binds(MECH_COOLING_SQL, "mechanical-cooling");
        assert_window_equipment_binds(MOTOR_WEEKLY_SQL, "runtime");
    }

    #[test]
    fn rcx_sensor_schedule_sql_declares_window_and_equipment_binds() {
        // Soft-OPEN post-#1264: RCx role_timeseries + sensor + schedule Overview/RCx traffic.
        assert_window_equipment_binds(ROLE_TIMESERIES_SQL, "role-timeseries");
        assert_window_equipment_binds(SENSOR_STATS_SQL, "sensor-stats");
        assert_window_equipment_binds(SENSOR_FAULTS_SQL, "sensor-faults");
        assert_window_equipment_binds(SCHEDULE_SQL, "schedule");
        assert!(
            ROLE_TIMESERIES_SQL.contains("a.role = $5"),
            "role_timeseries must bind the exact role as $5"
        );
        assert!(
            ROLE_TIMESERIES_SQL.contains("LIMIT $6"),
            "role_timeseries must keep limit as $6 after window/equipment binds"
        );
    }

    #[test]
    fn plant_health_inventory_binds_equipment_only() {
        // Soft-OPEN: window honestly unsupported — equipment table inventory.
        assert!(
            !PLANT_HEALTH_SQL.contains("$2::timestamptz"),
            "plant-health inventory must not fake window binds"
        );
        assert!(
            PLANT_HEALTH_SQL.contains("$2::text[]") || PLANT_HEALTH_SQL.contains("ANY ($2)"),
            "plant-health inventory must bind equipment_ids ($2)"
        );
    }

    #[test]
    fn residual_traffic_sql_declares_window_and_equipment_binds() {
        // Soft-OPEN post-#1265: remaining advertised sample/topology routes.
        assert_window_equipment_binds(DIURNAL_SQL, "diurnal");
        assert_window_equipment_binds(FUEL_DAILY_SQL, "fuel");
        assert_window_equipment_binds(METERING_SQL, "metering");
        assert_window_equipment_binds(SETPOINTS_SQL, "setpoints");
        assert_window_equipment_binds(PID_HUNTING_SQL, "pid-hunting");
        assert_window_equipment_binds(SQL_ANOMALY_SQL, "sql-anomaly");
        assert_window_equipment_binds(SQL_ANOMALY_SERIES_SQL, "sql-anomaly-series");
        assert_window_equipment_binds(MV_CHANGE_POINT_SQL, "mv-change-point");
        assert_window_equipment_binds(RCX_PRESET_COVERAGE_SQL, "rcx-preset-coverage");
        assert_window_equipment_binds(TOPOLOGY_SQL, "topology");
    }

    #[test]
    fn analytics_sql_scope_from_request_keeps_window_and_equipment() {
        let start = Utc.with_ymd_and_hms(2026, 4, 1, 0, 0, 0).unwrap();
        let end = Utc.with_ymd_and_hms(2026, 4, 8, 0, 0, 0).unwrap();
        let req = AnalyticsRequest {
            query: crate::analytics::AnalyticsQuery {
                building_id: Some("SYNTHETIC_ECON".into()),
                start: Some(start),
                end: Some(end),
                equipment_ids: Some(vec![
                    "AHU_A".into(),
                    "".into(),
                    "AHU_A".into(),
                    "AHU_B".into(),
                ]),
                ..Default::default()
            },
            ..Default::default()
        };
        let scope = AnalyticsSqlScope::from_request(&req);
        assert_eq!(scope.start, Some(start));
        assert_eq!(scope.end, Some(end));
        assert_eq!(
            scope.equipment_ids,
            vec!["AHU_A".to_string(), "AHU_B".to_string()]
        );
        assert_eq!(
            scope.equipment_bind(),
            Some(vec!["AHU_A".into(), "AHU_B".into()])
        );
    }

    #[test]
    fn envelope_pack_version_matches_analytics_registry() {
        let reg: Value =
            serde_json::from_str(ANALYTICS_REGISTRY_JSON).expect("registry.json parses");
        let declared = reg
            .get("pack_version")
            .and_then(|v| v.as_str())
            .expect("registry pack_version");
        assert_eq!(
            analytics_pack_version(),
            declared,
            "runtime analytics envelope must advertise registry pack_version (no silent drift)"
        );
        let env = envelope("runtime", "SITE", vec![]);
        assert_eq!(
            env.get("pack_version").and_then(|v| v.as_str()),
            Some(declared)
        );
        assert!(
            declared.contains("softopen"),
            "Soft-OPEN pack_version must include softopen marker"
        );
    }

    #[test]
    fn motor_weekly_sql_prefers_status_over_command() {
        assert!(
            MOTOR_WEEKLY_SQL.contains("MIN(signal_rank)"),
            "status must win over command so plant_group hours are not doubled"
        );
        assert!(MOTOR_WEEKLY_SQL.contains("fan_status"));
        assert!(MOTOR_WEEKLY_SQL.contains("fan_cmd"));
        assert!(
            !MOTOR_WEEKLY_SQL.contains("GROUP BY 1, 3, 4\n"),
            "the old group-by counted fan_status and fan_cmd in one plant_group"
        );
        assert!(
            MOTOR_WEEKLY_SQL.contains("dt_seconds <= 3600.0"),
            "motor hours must integrate eligible deltas, not a fixed poll"
        );
        assert!(
            !MOTOR_WEEKLY_SQL.contains("* 300.0"),
            "motor hours must not multiply sample counts by 300s"
        );
        assert!(
            MECH_COOLING_SQL.contains("dt_seconds <= 3600.0"),
            "mechanical cooling hours must integrate eligible deltas"
        );
        assert!(
            !MECH_COOLING_SQL.contains("* 300.0"),
            "mechanical cooling hours must not multiply sample counts by 300s"
        );
        assert!(
            MOTOR_WEEKLY_SQL.contains("AS n_observations"),
            "weekly runtime must report the chosen-signal sample count"
        );
        assert!(
            MOTOR_WEEKLY_SQL.contains("AS partial_week")
                && MOTOR_WEEKLY_SQL.contains("interval '6 days'"),
            "weekly runtime must mark buckets that do not span the week"
        );
    }
}

#[cfg(test)]
mod overview_freshness_tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn failed_watermark_is_stale_without_a_time_or_generation() {
        let body = apply_overview_freshness(
            json!({"rows": [1], "building_id": "site-a"}),
            &overview_freshness_unavailable(),
        );
        assert_eq!(body["stale"], true);
        assert!(body["watermark"].is_null());
        assert!(body["generation"].is_null());
        assert_eq!(body["rows"], json!([1]));
    }

    #[test]
    fn known_watermark_names_the_latest_data_time_and_generation() {
        let timed = overview_freshness_known(
            "site-a",
            20260401000000,
            "2026-04-01T00:00:00Z",
            "samples=2",
        );
        let body = apply_overview_freshness(json!({"rows": []}), &timed);
        assert_eq!(body["stale"], false);
        assert_eq!(body["watermark"], "2026-04-01T00:00:00Z");
        let generation = body["generation"].as_str().expect("generation");
        assert!(!generation.is_empty());

        let later = overview_freshness_known(
            "site-a",
            20260402000000,
            "2026-04-02T00:00:00Z",
            "samples=3",
        );
        assert_ne!(later.generation.as_deref(), Some(generation));

        let other_site = overview_freshness_known(
            "site-b",
            20260401000000,
            "2026-04-01T00:00:00Z",
            "samples=2",
        );
        assert_ne!(other_site.generation, timed.generation);
    }

    #[test]
    fn empty_scope_is_not_stale_and_has_no_data_time() {
        let empty = overview_freshness_known("site-a", 0, "", "samples=0");
        let body = apply_overview_freshness(json!({}), &empty);
        assert_eq!(body["stale"], false);
        assert!(body["watermark"].is_null());
        assert!(body["generation"].is_string());
    }

    #[test]
    fn non_object_body_is_left_unchanged() {
        let body = apply_overview_freshness(json!([1, 2]), &overview_freshness_unavailable());
        assert_eq!(body, json!([1, 2]));
    }
}
