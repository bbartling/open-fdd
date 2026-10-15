//! Timescale analytics for Wave-X Soft-OPEN envelopes (ADR-010).
//!
//! When `OPENFDD_DATABASE_URL` is set, product analytics never open a DataFusion
//! SessionContext — all query_ids dispatch here.

use anyhow::{Context, Result};
use fdd_tsdb::Tsdb;
use serde_json::{json, Value};
use sqlx::Row;

use crate::analytics::AnalyticsRequest;

/// Soft-OPEN: SQL body from `sql/analytics` pack (hash-pinned). Bind `$1` only.
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
const MV_CHANGE_POINT_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/mv_change_point_daily.sql");
const FUEL_DAILY_SQL: &str = include_str!("../../../sql/analytics/postgres/queries/fuel_daily.sql");
const RCX_PRESET_COVERAGE_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/rcx_preset_role_coverage.sql");

pub async fn motor_weekly_runtime(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(MOTOR_WEEKLY_SQL)
        .bind(building_id)
        .fetch_all(tsdb.pool())
        .await
        .context("motor_weekly_runtime")?;

    let mut out = Vec::new();
    for r in rows {
        let runtime = r
            .try_get::<f64, _>("runtime_hours")
            .ok()
            .or_else(|| r.try_get::<f64, _>("run_hours").ok());
        out.push(json!({
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "kind": r.try_get::<String, _>("kind").unwrap_or_else(|_| "motor".into()),
            "plant_group": r.try_get::<String, _>("plant_group").ok(),
            "week_start": r.try_get::<chrono::DateTime<chrono::Utc>, _>("week_start")
                .ok()
                .map(|t| t.to_rfc3339()),
            "week_label": r.try_get::<String, _>("week_label").ok(),
            "run_hours": runtime,
            "runtime_hours": runtime,
        }));
    }
    Ok(envelope("motor-weekly-runtime", building_id, out))
}

pub async fn bas_vs_web_oat(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(BAS_VS_WEB_SQL)
        .bind(building_id)
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
    Ok(envelope("bas-vs-web-oat", building_id, out))
}

pub async fn plant_health_matrix(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(PLANT_HEALTH_SQL)
        .bind(building_id)
        .fetch_all(tsdb.pool())
        .await
        .context("plant_health_matrix")?;

    // Wave-X C6: never fabricate score=1.0. Emit unavailable until scoped
    // diagnostic SQL health is implemented per cohort (see completion audit WX12).
    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "equip_type": r.try_get::<Option<String>, _>("equip_type").ok().flatten(),
            "score": Value::Null,
            "status": "unavailable",
            "reason": "plant_health_sql_pending",
        }));
    }
    Ok(envelope("plant-health", building_id, out))
}

pub async fn role_timeseries(
    tsdb: &Tsdb,
    building_id: &str,
    role_suffix: &str,
    query_id: &str,
    limit: i64,
) -> Result<Value> {
    let pattern = format!("%.{role_suffix}");
    let rows = sqlx::query(ROLE_TIMESERIES_SQL)
        .bind(building_id)
        .bind(&pattern)
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
    Ok(envelope(query_id, building_id, out))
}

pub async fn mechanical_cooling_oat_bins(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(MECH_COOLING_SQL)
        .bind(building_id)
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
    Ok(envelope("mechanical-cooling", building_id, out))
}

pub async fn sensor_stats(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(SENSOR_STATS_SQL)
        .bind(building_id)
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
    Ok(envelope("sensor-stats", building_id, out))
}

pub async fn schedule_occupancy(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(SCHEDULE_SQL)
        .bind(building_id)
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
    Ok(envelope("schedule", building_id, out))
}

pub async fn sensor_faults(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(SENSOR_FAULTS_SQL)
        .bind(building_id)
        .fetch_all(tsdb.pool())
        .await
        .context("sensor_faults")?;
    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "role": r.try_get::<String, _>("role").unwrap_or_default(),
            "n": r.try_get::<i64, _>("n").ok(),
            "last_ts": r.try_get::<chrono::DateTime<chrono::Utc>, _>("last_ts")
                .ok()
                .map(|t| t.to_rfc3339()),
            "min_val": r.try_get::<f64, _>("min_val").ok(),
            "max_val": r.try_get::<f64, _>("max_val").ok(),
            "stddev_val": r.try_get::<f64, _>("stddev_val").ok(),
            "fault_flag": r.try_get::<String, _>("fault_flag").unwrap_or_else(|_| "OK".into()),
        }));
    }
    Ok(envelope("sensor-faults", building_id, out))
}

pub async fn setpoints_snapshot(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(SETPOINTS_SQL)
        .bind(building_id)
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
    Ok(envelope("setpoints", building_id, out))
}

pub async fn diurnal_hourly(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(DIURNAL_SQL)
        .bind(building_id)
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
    Ok(envelope("diurnal", building_id, out))
}

pub async fn topology_equipment(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(TOPOLOGY_SQL)
        .bind(building_id)
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
    Ok(envelope("topology", building_id, out))
}

pub async fn metering_kwh(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(METERING_SQL)
        .bind(building_id)
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
    Ok(envelope("metering", building_id, out))
}

pub async fn pid_hunting_proxy(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(PID_HUNTING_SQL)
        .bind(building_id)
        .fetch_all(tsdb.pool())
        .await
        .context("pid_hunting_proxy")?;
    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "role": r.try_get::<String, _>("role").unwrap_or_default(),
            "n": r.try_get::<i64, _>("n").ok(),
            "avg_val": r.try_get::<f64, _>("avg_val").ok(),
            "stddev_val": r.try_get::<f64, _>("stddev_val").ok(),
            "hunt_flag": r.try_get::<String, _>("hunt_flag").unwrap_or_else(|_| "OK".into()),
        }));
    }
    Ok(envelope("pid-hunting", building_id, out))
}

pub async fn sql_anomaly_zscore(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(SQL_ANOMALY_SQL)
        .bind(building_id)
        .fetch_all(tsdb.pool())
        .await
        .context("sql_anomaly_zscore")?;
    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "role": r.try_get::<String, _>("role").unwrap_or_default(),
            "ts": r.try_get::<chrono::DateTime<chrono::Utc>, _>("ts").ok().map(|t| t.to_rfc3339()),
            "val": r.try_get::<f64, _>("val").ok(),
            "avg_val": r.try_get::<f64, _>("avg_val").ok(),
            "stddev_val": r.try_get::<f64, _>("stddev_val").ok(),
            "z_abs": r.try_get::<f64, _>("z_abs").ok(),
            "anomaly_flag": r.try_get::<String, _>("anomaly_flag").unwrap_or_else(|_| "OK".into()),
        }));
    }
    Ok(envelope("sql-anomaly", building_id, out))
}

pub async fn mv_change_point_daily(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(MV_CHANGE_POINT_SQL)
        .bind(building_id)
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
    Ok(envelope("mv-change-point", building_id, out))
}

pub async fn fuel_daily(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(FUEL_DAILY_SQL)
        .bind(building_id)
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
    Ok(envelope("fuel", building_id, out))
}

pub async fn rcx_preset_role_coverage(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(RCX_PRESET_COVERAGE_SQL)
        .bind(building_id)
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
    Ok(envelope("rcx-preset-coverage", building_id, out))
}

pub async fn economizer_deltas(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    // Soft-OPEN: per-equipment pivot from analytics pack (not cross-equip GROUP BY ts).
    let rows = sqlx::query(ECONOMIZER_SQL)
        .bind(building_id)
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
        }));
    }
    Ok(envelope("economizer", building_id, out))
}

pub async fn fdd_registry(tsdb: &Tsdb) -> Result<Value> {
    let rows = sqlx::query(
        r#"
        SELECT rule_id, sql_file, title, enabled
        FROM fdd_rule_registry
        ORDER BY rule_id
        "#,
    )
    .fetch_all(tsdb.pool())
    .await
    .context("fdd_registry")?;

    // Wave-X C7: warehouse cases.json uses cookbook ids (e.g. FC13) while the
    // product primary id may be FC13-SAT-HIGH. Surface yaml aliases so catalog
    // presence matches /api/fdd/run + /api/fdd/plot resolution.
    let aliases_by_id: std::collections::HashMap<String, Vec<String>> = {
        let root = crate::timescale_product::sql_root_for_registry();
        match fdd_rules::load_registry(&root) {
            Ok(reg) => reg
                .rules
                .into_iter()
                .map(|r| (r.rule_id, r.aliases))
                .collect(),
            Err(e) => {
                tracing::warn!(error = %e, "fdd_registry: yaml aliases unavailable");
                std::collections::HashMap::new()
            }
        }
    };

    let mut out = Vec::new();
    let mut alias_count = 0usize;
    for r in rows {
        let rule_id = r.try_get::<String, _>("rule_id").unwrap_or_default();
        let aliases = aliases_by_id.get(&rule_id).cloned().unwrap_or_default();
        alias_count += aliases.len();
        out.push(json!({
            "rule_id": rule_id,
            "aliases": aliases,
            "sql_file": r.try_get::<String, _>("sql_file").unwrap_or_default(),
            "title": r.try_get::<Option<String>, _>("title").ok().flatten(),
            "enabled": r.try_get::<bool, _>("enabled").unwrap_or(true),
            "engine": "postgres-sql",
        }));
    }
    Ok(json!({
        "ok": true,
        "engine": "postgres-sql",
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

fn envelope(query_id: &str, building_id: &str, rows: Vec<Value>) -> Value {
    json!({
        "query_id": query_id,
        "building_id": building_id,
        "engine": "timescale-sql",
        "analytics_pack": "openfdd-analytics-sql-v1",
        "pack_version": "3.6.9-softopen",
        "stale": false,
        "rows": rows,
    })
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
    _query_version: &str,
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

    let result = match query_id {
        "runtime" => motor_weekly_runtime(&tsdb, &building).await,
        "bas-vs-web-oat" => bas_vs_web_oat(&tsdb, &building).await,
        "ahu-health"
        | "vav-health"
        | "chiller-health"
        | "boiler-health"
        | "hp-health"
        | "zone-other-health"
        | "cooling-tower-health"
        | "sensor-health"
        | "ahu-temperature-health"
        | "ahu-pressure-health"
        | "ahu-economizer-health" => plant_health_matrix(&tsdb, &building).await,
        "economizer" | "rcx-ahu" => economizer_deltas(&tsdb, &building).await,
        "rcx-vav" => role_timeseries(&tsdb, &building, "zone_t", "rcx-vav", 2000).await,
        "rcx-chiller" => {
            role_timeseries(&tsdb, &building, "chw_supply_t", "rcx-chiller", 2000).await
        }
        "rcx-boiler" => role_timeseries(&tsdb, &building, "hw_supply_t", "rcx-boiler", 2000).await,
        "equipment-inspect" | "inspect" => {
            // Wide envelope for SPA Inspect (points + coverage), not long sample dump.
            let _ = tsdb;
            match crate::timescale_product::inspect_json(req).await {
                Ok(v) => Ok(v),
                Err(e) => Err(e),
            }
        }
        "mechanical-cooling" => mechanical_cooling_oat_bins(&tsdb, &building).await,
        "schedule" => schedule_occupancy(&tsdb, &building).await,
        "sensor-stats" => sensor_stats(&tsdb, &building).await,
        "sensor-faults" => sensor_faults(&tsdb, &building).await,
        "setpoints" => setpoints_snapshot(&tsdb, &building).await,
        "diurnal" => diurnal_hourly(&tsdb, &building).await,
        "topology" => topology_equipment(&tsdb, &building).await,
        "metering" => metering_kwh(&tsdb, &building).await,
        "pid-hunting" => pid_hunting_proxy(&tsdb, &building).await,
        "sql-anomaly" => sql_anomaly_zscore(&tsdb, &building).await,
        "mv-change-point" => mv_change_point_daily(&tsdb, &building).await,
        "fuel" => fuel_daily(&tsdb, &building).await,
        "rcx-preset-coverage" => rcx_preset_role_coverage(&tsdb, &building).await,
        other => Ok(json!({
            "query_id": other,
            "building_id": building,
            "engine": "timescale-sql",
            "analytics_pack": "openfdd-analytics-sql-v1",
            "pack_version": "3.6.9-softopen",
            "stale": false,
            "rows": [],
            "note": "Wave-X Timescale dispatch — query SQL port pending; DataFusion disabled",
        })),
    };

    result.map_err(|e| {
        (
            axum::http::StatusCode::INTERNAL_SERVER_ERROR,
            axum::Json(json!({
                "ok": false,
                "error": e.to_string(),
                "engine": "timescale-sql",
            })),
        )
    })
}
