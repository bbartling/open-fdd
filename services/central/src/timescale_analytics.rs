//! Timescale analytics for Wave-X Soft-OPEN envelopes (ADR-010).
//!
//! When `OPENFDD_DATABASE_URL` is set, product analytics never open a DataFusion
//! SessionContext — all query_ids dispatch here.

use anyhow::{Context, Result};
use fdd_tsdb::Tsdb;
use serde_json::{json, Value};
use sqlx::Row;

use crate::analytics::AnalyticsRequest;

pub async fn motor_weekly_runtime(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(
        r#"
        SELECT
          split_part(openfdd_key, '.', 1) AS equipment_id,
          date_trunc('week', ts) AS week_start,
          (COUNT(*) FILTER (WHERE COALESCE(val, 0) > 0.05)::double precision * 300.0 / 3600.0)
            AS runtime_hours
        FROM sample
        WHERE site_id = $1
          AND (openfdd_key LIKE '%.fan_status' OR openfdd_key LIKE '%.fan_cmd')
        GROUP BY 1, 2
        ORDER BY 1, 2
        LIMIT 500
        "#,
    )
    .bind(building_id)
    .fetch_all(tsdb.pool())
    .await
    .context("motor_weekly_runtime")?;

    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "week_start": r.try_get::<chrono::DateTime<chrono::Utc>, _>("week_start")
                .ok()
                .map(|t| t.to_rfc3339()),
            "runtime_hours": r.try_get::<f64, _>("runtime_hours").ok(),
        }));
    }
    Ok(envelope("motor-weekly-runtime", building_id, out))
}

pub async fn bas_vs_web_oat(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(
        r#"
        WITH bas AS (
          SELECT ts, val AS bas_oa_t
          FROM sample
          WHERE site_id = $1 AND openfdd_key LIKE '%.oa_t'
        ),
        web AS (
          SELECT ts, val AS web_oa_t
          FROM sample
          WHERE site_id = $1 AND openfdd_key LIKE '%.web_oa_t'
        )
        SELECT b.ts, b.bas_oa_t, w.web_oa_t, (b.bas_oa_t - w.web_oa_t) AS delta_f
        FROM bas b
        JOIN web w ON w.ts = b.ts
        ORDER BY b.ts DESC
        LIMIT 2000
        "#,
    )
    .bind(building_id)
    .fetch_all(tsdb.pool())
    .await
    .context("bas_vs_web_oat")?;

    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "ts": r.try_get::<chrono::DateTime<chrono::Utc>, _>("ts").ok().map(|t| t.to_rfc3339()),
            "bas_oa_t": r.try_get::<f64, _>("bas_oa_t").ok(),
            "web_oa_t": r.try_get::<f64, _>("web_oa_t").ok(),
            "delta_f": r.try_get::<f64, _>("delta_f").ok(),
        }));
    }
    Ok(envelope("bas-vs-web-oat", building_id, out))
}

pub async fn plant_health_matrix(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(
        r#"
        SELECT equipment_id, equip_type
        FROM equipment
        WHERE building_id = $1
        ORDER BY equip_type NULLS LAST, equipment_id
        LIMIT 500
        "#,
    )
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
    let rows = sqlx::query(
        r#"
        SELECT ts, openfdd_key, val,
               split_part(openfdd_key, '.', 1) AS equipment_id
        FROM sample
        WHERE site_id = $1 AND openfdd_key LIKE $2
        ORDER BY ts DESC
        LIMIT $3
        "#,
    )
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

pub async fn economizer_deltas(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    // Wide pivot for AHU sat/mat/rat/oa_t/oa_damper on shared timestamps (latest window).
    let rows = sqlx::query(
        r#"
        WITH keys AS (
          SELECT ts,
            max(val) FILTER (WHERE openfdd_key LIKE '%.oa_t') AS oa_t,
            max(val) FILTER (WHERE openfdd_key LIKE '%.rat') AS rat,
            max(val) FILTER (WHERE openfdd_key LIKE '%.mat') AS mat,
            max(val) FILTER (WHERE openfdd_key LIKE '%.sat') AS sat,
            max(val) FILTER (WHERE openfdd_key LIKE '%.oa_damper_pct') AS oa_damper_pct,
            max(split_part(openfdd_key, '.', 1))
              FILTER (WHERE openfdd_key LIKE '%.sat') AS equipment_id
          FROM sample
          WHERE site_id = $1
            AND (
              openfdd_key LIKE '%.oa_t' OR openfdd_key LIKE '%.rat'
              OR openfdd_key LIKE '%.mat' OR openfdd_key LIKE '%.sat'
              OR openfdd_key LIKE '%.oa_damper_pct'
            )
          GROUP BY ts
        )
        SELECT ts, equipment_id, oa_t, rat, mat, sat, oa_damper_pct,
               (oa_t - rat) AS delta_or_f,
               (mat - rat) AS delta_mr_f
        FROM keys
        WHERE oa_t IS NOT NULL AND rat IS NOT NULL AND mat IS NOT NULL
        ORDER BY ts DESC
        LIMIT 2000
        "#,
    )
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
    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "rule_id": r.try_get::<String, _>("rule_id").unwrap_or_default(),
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
        "stale": false,
        "rows": rows,
    })
}

fn building_from(req: &AnalyticsRequest) -> String {
    req.query
        .building_id
        .clone()
        .unwrap_or_else(|| "BUILDING_50".into())
}

/// Universal product dispatch — never calls DataFusion.
pub async fn respond_query(
    query_id: &str,
    _query_version: &str,
    req: &AnalyticsRequest,
) -> Result<Value, (axum::http::StatusCode, axum::Json<Value>)> {
    let building = building_from(req);
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
        "mechanical-cooling" => {
            role_timeseries(
                &tsdb,
                &building,
                "chiller_status",
                "mechanical-cooling",
                2000,
            )
            .await
        }
        "schedule" => role_timeseries(&tsdb, &building, "occ_mode", "schedule", 2000).await,
        "sensor-faults" | "sensor-stats" | "pid-hunting" | "setpoints" | "diurnal" | "topology"
        | "sql-anomaly" | "metering" | "mv-change-point" | "fuel" => {
            // Honest thin envelope — data present, full algorithm port tracked.
            let samples = tsdb.sample_count(&building).await.unwrap_or(0);
            Ok(json!({
                "query_id": query_id,
                "building_id": building,
                "engine": "timescale-sql",
                "stale": false,
                "rows": [],
                "sample_count": samples,
                "note": format!(
                    "Wave-X Timescale path active; full {query_id} SQL port pending — no DataFusion fallback"
                ),
            }))
        }
        other => Ok(json!({
            "query_id": other,
            "building_id": building,
            "engine": "timescale-sql",
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
