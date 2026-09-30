//! Serve analytics envelopes from the parquet result cache when the key matches.
//!
//! A hit does not recompute. A watermark newer than the cached order is `stale`
//! (default) or recomputed when `OPENFDD_ANALYTICS_CACHE_ON_STALE=recompute`
//! or the request sets `refresh: true`. AFDD `{rule_id}.json` files are not
//! this cache.

use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Instant;

use axum::http::StatusCode;
use axum::Json;
use chrono::{DateTime, SecondsFormat, Utc};
use fdd_store::{
    config_hash, freshness_for_watermark, historian_watermark_order, order_key_to_rfc3339,
    read_plan, read_result, write_result, AnalyticsCacheKey, AnalyticsResultTable, CacheFreshness,
    CacheProvenance, SessionBook, SessionError, SessionKind, StaleAction,
};
use serde_json::{json, Value};

use super::{AnalyticsEnvelope, AnalyticsRequest, SCHEMA_VERSION};

pub struct ServedAnalytics {
    pub envelope: AnalyticsEnvelope,
    pub cache: Value,
}

pub async fn respond(
    query_id: &str,
    query_version: &str,
    req: &AnalyticsRequest,
    compute: impl AsyncFnOnce() -> AnalyticsEnvelope,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let served = serve(query_id, query_version, req, compute).await?;
    Ok(json_body(&served))
}

pub async fn serve(
    query_id: &str,
    query_version: &str,
    req: &AnalyticsRequest,
    compute: impl AsyncFnOnce() -> AnalyticsEnvelope,
) -> Result<ServedAnalytics, (StatusCode, Json<Value>)> {
    serve_with(
        &storage_root(),
        crate::building_sessions::book(),
        query_id,
        query_version,
        req,
        stale_action_from_env(),
        compute,
    )
    .await
}

pub async fn serve_with(
    root: &Path,
    sessions: &Mutex<SessionBook>,
    query_id: &str,
    query_version: &str,
    req: &AnalyticsRequest,
    on_stale: StaleAction,
    compute: impl AsyncFnOnce() -> AnalyticsEnvelope,
) -> Result<ServedAnalytics, (StatusCode, Json<Value>)> {
    let started = Instant::now();
    let Some(building_id) = req
        .query
        .building_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
    else {
        let envelope = compute().await;
        return Ok(skipped(
            envelope,
            started,
            "building_id required for analytics result cache",
        ));
    };

    let key = match cache_key(building_id, query_id, query_version, req) {
        Ok(key) => key,
        Err(reason) => {
            let envelope = compute().await;
            return Ok(skipped(envelope, started, &reason));
        }
    };

    {
        let mut guard = sessions.lock().unwrap_or_else(|poison| poison.into_inner());
        let now = crate::building_sessions::now_ms();
        guard.evict_idle(now);
        if let Err(err) = guard.open(&key.building_id, SessionKind::CsvGuest, now) {
            return Err(session_error(err));
        }
    }

    let historian_order = historian_watermark_order(root, &key.building_id).unwrap_or(0);
    let cached = read_result(root, &key).ok().flatten();
    let freshness = match &cached {
        Some((_, prov)) => freshness_for_watermark(prov.watermark_order, historian_order),
        None => CacheFreshness::Miss,
    };
    let plan = read_plan(freshness, req.refresh, on_stale);
    if plan.serve_cached {
        if let Some((table, prov)) = cached {
            let envelope = envelope_from_table(&table, &prov, req);
            let cache = cache_status(true, plan.stale, started, &key, &prov, historian_order);
            return Ok(ServedAnalytics { envelope, cache });
        }
    }

    {
        let mut guard = sessions.lock().unwrap_or_else(|poison| poison.into_inner());
        let now = crate::building_sessions::now_ms();
        if let Err(err) = guard.begin_job(&key.building_id, now) {
            return Err(session_error(err));
        }
    }
    let _unload = HistorianUnload {
        sessions,
        building_id: key.building_id.clone(),
    };
    let envelope = compute().await;
    let table = table_from_envelope(&envelope);
    let provenance = CacheProvenance {
        building_id: key.building_id.clone(),
        query_id: key.query_id.clone(),
        query_version: key.query_version.clone(),
        window_start: key.window_start.clone(),
        window_end: key.window_end.clone(),
        config_hash: key.config_hash.clone(),
        watermark_order: historian_order,
        watermark_utc: order_key_to_rfc3339(historian_order),
        generated_at: envelope
            .generated_at
            .to_rfc3339_opts(SecondsFormat::Secs, true),
        engine: envelope.engine.clone(),
        result_query_version: envelope.query_version.clone(),
    };
    if let Err(err) = write_result(root, &key, &table, &provenance) {
        tracing::warn!(error = %err, query_id, "analytics result parquet write failed");
    } else if let Err(err) = fdd_store::enforce_budget_throttled(root, 60) {
        tracing::warn!(error = %err, "local data budget enforcement failed");
    }
    let cache = cache_status(false, false, started, &key, &provenance, historian_order);
    Ok(ServedAnalytics { envelope, cache })
}

struct HistorianUnload<'a> {
    sessions: &'a Mutex<SessionBook>,
    building_id: String,
}

impl Drop for HistorianUnload<'_> {
    fn drop(&mut self) {
        let mut guard = self
            .sessions
            .lock()
            .unwrap_or_else(|poison| poison.into_inner());
        guard.finish_job(&self.building_id, crate::building_sessions::now_ms());
    }
}

pub fn json_body(served: &ServedAnalytics) -> Json<Value> {
    let stale = served
        .cache
        .get("stale")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    Json(json!({
        "ok": true,
        "stale": stale,
        "analytics": served.envelope.to_json(),
        "cache": served.cache,
    }))
}

fn storage_root() -> PathBuf {
    if let Ok(raw) = std::env::var("OPENFDD_ANALYTICS_CACHE_ROOT") {
        let trimmed = raw.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed);
        }
    }
    fdd_store::local_file_root_from_env().unwrap_or_else(super::historian::parquet_root_base)
}

fn stale_action_from_env() -> StaleAction {
    match std::env::var("OPENFDD_ANALYTICS_CACHE_ON_STALE") {
        Ok(value) if value.trim().eq_ignore_ascii_case("recompute") => StaleAction::Recompute,
        _ => StaleAction::ServeStale,
    }
}

fn cache_key(
    building_id: &str,
    query_id: &str,
    query_version: &str,
    req: &AnalyticsRequest,
) -> Result<AnalyticsCacheKey, String> {
    fdd_store::safe_partition_value(building_id, "building_id").map_err(|e| e.to_string())?;
    fdd_store::safe_partition_value(query_id, "query_id").map_err(|e| e.to_string())?;
    fdd_store::safe_partition_value(query_version, "query_version").map_err(|e| e.to_string())?;
    Ok(AnalyticsCacheKey {
        building_id: building_id.to_string(),
        query_id: query_id.to_string(),
        query_version: query_version.to_string(),
        window_start: window_token(req.query.start),
        window_end: window_token(req.query.end),
        config_hash: config_hash(&config_material(req)),
    })
}

fn window_token(ts: Option<DateTime<Utc>>) -> String {
    ts.map(|t| t.to_rfc3339_opts(SecondsFormat::Secs, true))
        .unwrap_or_else(|| "open".into())
}

fn config_material(req: &AnalyticsRequest) -> String {
    let mut equipment = req.query.equipment_ids.clone().unwrap_or_default();
    equipment.sort();
    format!(
        "req_qv={}\nread_tenant={}\ndt_min={}\ngap={}\nmax_points={}\nequipment={}\nseries={}",
        req.query.query_version.as_deref().unwrap_or(""),
        req.read_tenant_id.as_deref().unwrap_or(""),
        req.dt_min_f.map(|v| v.to_string()).unwrap_or_default(),
        req.max_gap_seconds
            .map(|v| v.to_string())
            .unwrap_or_default(),
        req.query.max_points.unwrap_or(0),
        equipment.join(","),
        canonical_json(req.series.as_ref().unwrap_or(&Value::Null)),
    )
}

fn canonical_json(value: &Value) -> String {
    match value {
        Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            let parts: Vec<String> = keys
                .into_iter()
                .map(|k| {
                    let key = serde_json::to_string(k).unwrap_or_else(|_| "\"\"".into());
                    format!("{key}:{}", canonical_json(&map[k]))
                })
                .collect();
            format!("{{{}}}", parts.join(","))
        }
        Value::Array(items) => {
            let parts: Vec<String> = items.iter().map(canonical_json).collect();
            format!("[{}]", parts.join(","))
        }
        other => other.to_string(),
    }
}

fn table_from_envelope(env: &AnalyticsEnvelope) -> AnalyticsResultTable {
    AnalyticsResultTable {
        rows: env.rows.clone(),
        equipment: env.equipment.clone(),
        points: env.points.clone(),
        skipped: env.skipped.clone(),
        warnings: env.warnings.clone(),
        coverage: env.coverage.clone(),
        engine: env.engine.clone(),
        result_query_version: env.query_version.clone(),
    }
}

fn envelope_from_table(
    table: &AnalyticsResultTable,
    prov: &CacheProvenance,
    req: &AnalyticsRequest,
) -> AnalyticsEnvelope {
    let generated_at = DateTime::parse_from_rfc3339(&prov.generated_at)
        .map(|t| t.with_timezone(&Utc))
        .unwrap_or_else(|_| Utc::now());
    let query_version = if table.result_query_version.is_empty() {
        prov.query_version.clone()
    } else {
        table.result_query_version.clone()
    };
    AnalyticsEnvelope {
        schema_version: SCHEMA_VERSION.into(),
        query_version,
        job_id: req.query.job_id.clone(),
        run_id: req.query.run_id.clone(),
        input_fingerprint: None,
        generated_at,
        engine: if table.engine.is_empty() {
            prov.engine.clone()
        } else {
            table.engine.clone()
        },
        coverage: table.coverage.clone(),
        warnings: table.warnings.clone(),
        rows: table.rows.clone(),
        equipment: table.equipment.clone(),
        points: table.points.clone(),
        skipped: table.skipped.clone(),
    }
}

fn cache_status(
    hit: bool,
    stale: bool,
    started: Instant,
    key: &AnalyticsCacheKey,
    prov: &CacheProvenance,
    historian_order: u64,
) -> Value {
    json!({
        "hit": hit,
        "stale": stale,
        "elapsed_ms": started.elapsed().as_millis() as u64,
        "schema": fdd_store::SCHEMA_NAME,
        "query_id": key.query_id,
        "query_version": key.query_version,
        "config_hash": key.config_hash,
        "building_id": key.building_id,
        "watermark_utc": prov.watermark_utc,
        "watermark_order": prov.watermark_order,
        "historian_watermark_order": historian_order,
        "historian_watermark_utc": order_key_to_rfc3339(historian_order),
    })
}

fn skipped(envelope: AnalyticsEnvelope, started: Instant, reason: &str) -> ServedAnalytics {
    ServedAnalytics {
        envelope,
        cache: json!({
            "hit": false,
            "stale": false,
            "skipped": true,
            "reason": reason,
            "elapsed_ms": started.elapsed().as_millis() as u64,
        }),
    }
}

fn session_error(err: SessionError) -> (StatusCode, Json<Value>) {
    match err {
        SessionError::AtCapacity { max } => (
            StatusCode::TOO_MANY_REQUESTS,
            Json(json!({
                "ok": false,
                "error": format!("max concurrent building sessions is {max}"),
            })),
        ),
        SessionError::UnsafeBuildingId => (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "unsafe building_id"})),
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analytics::{envelope, AnalyticsQuery};
    use fdd_store::SessionLimits;
    use std::fs;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;

    fn req(building: &str) -> AnalyticsRequest {
        AnalyticsRequest {
            query: AnalyticsQuery {
                building_id: Some(building.into()),
                ..AnalyticsQuery::default()
            },
            ..AnalyticsRequest::default()
        }
    }

    fn limits() -> SessionLimits {
        SessionLimits {
            max_interactive: 2,
            idle_timeout_ms: 60_000,
            mqtt_buffer_rows: 32,
            max_mqtt_buffers: 4,
        }
    }

    #[tokio::test]
    async fn cache_hit_does_not_recompute_and_records_elapsed() {
        let tmp = tempfile::tempdir().unwrap();
        let sessions = Mutex::new(SessionBook::new(limits()));
        let calls = Arc::new(AtomicUsize::new(0));
        let calls_hit = calls.clone();
        let first = serve_with(
            tmp.path(),
            &sessions,
            "runtime",
            "runtime-v1",
            &req("site-a"),
            StaleAction::ServeStale,
            async || {
                calls_hit.fetch_add(1, Ordering::SeqCst);
                let mut env = envelope("runtime-v1", &req("site-a").query, Vec::new());
                env.rows
                    .push(json!({"equipment_id": "AHU_1", "run_hours": 3.5}));
                env.engine = "datafusion".into();
                env
            },
        )
        .await
        .unwrap();
        assert_eq!(first.cache["hit"], false);
        assert!(first.cache.get("elapsed_ms").is_some());
        assert!(sessions.lock().unwrap().historian_resident().is_empty());

        let calls_second = calls.clone();
        let second = serve_with(
            tmp.path(),
            &sessions,
            "runtime",
            "runtime-v1",
            &req("site-a"),
            StaleAction::ServeStale,
            async || {
                calls_second.fetch_add(1, Ordering::SeqCst);
                envelope("runtime-v1", &req("site-a").query, Vec::new())
            },
        )
        .await
        .unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(second.cache["hit"], true);
        assert_eq!(second.cache["stale"], false);
        assert_eq!(second.envelope.rows[0]["equipment_id"], "AHU_1");
        assert!(second.cache["elapsed_ms"].as_u64().is_some());
        assert!(sessions.lock().unwrap().ram_resident().is_empty());
    }

    #[tokio::test]
    async fn watermark_advance_is_stale_until_refresh() {
        let tmp = tempfile::tempdir().unwrap();
        let sessions = Mutex::new(SessionBook::new(limits()));
        let calls = Arc::new(AtomicUsize::new(0));
        let c1 = calls.clone();
        let _ = serve_with(
            tmp.path(),
            &sessions,
            "sensor-faults",
            "sensor-faults-v1",
            &req("site-a"),
            StaleAction::ServeStale,
            async || {
                c1.fetch_add(1, Ordering::SeqCst);
                let mut env = envelope("sensor-faults-v1", &req("site-a").query, Vec::new());
                env.rows
                    .push(json!({"equipment_id": "AHU_1", "fault_hours": 1.0}));
                env
            },
        )
        .await
        .unwrap();
        let hist = tmp
            .path()
            .join("history/building_id=site-a/equipment_id=ahu/year=2026/month=03");
        fs::create_dir_all(&hist).unwrap();
        fs::write(hist.join("part-20260301T000000Z-live.parquet"), b"x").unwrap();
        let c2 = calls.clone();
        let stale = serve_with(
            tmp.path(),
            &sessions,
            "sensor-faults",
            "sensor-faults-v1",
            &req("site-a"),
            StaleAction::ServeStale,
            async || {
                c2.fetch_add(1, Ordering::SeqCst);
                envelope("sensor-faults-v1", &req("site-a").query, Vec::new())
            },
        )
        .await
        .unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(stale.cache["stale"], true);
        assert_eq!(stale.cache["hit"], true);
        assert_eq!(stale.envelope.rows[0]["fault_hours"], 1.0);

        let mut refresh = req("site-a");
        refresh.refresh = true;
        let c3 = calls.clone();
        let fresh = serve_with(
            tmp.path(),
            &sessions,
            "sensor-faults",
            "sensor-faults-v1",
            &refresh,
            StaleAction::ServeStale,
            async || {
                c3.fetch_add(1, Ordering::SeqCst);
                let mut env = envelope("sensor-faults-v1", &req("site-a").query, Vec::new());
                env.rows
                    .push(json!({"equipment_id": "AHU_1", "fault_hours": 2.0}));
                env
            },
        )
        .await
        .unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 2);
        assert_eq!(fresh.cache["hit"], false);
        assert_eq!(fresh.cache["stale"], false);
        assert_eq!(fresh.envelope.rows[0]["fault_hours"], 2.0);
    }
}
