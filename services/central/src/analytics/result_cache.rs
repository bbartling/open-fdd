//! Serve analytics envelopes from the PostgreSQL result cache when the key matches.
//!
//! The key covers the result contract, SQL pack, and model revision. Freshness
//! compares the scoped historian watermark and coverage. A failed or missing
//! watermark read is explicit and is never a fresh hit. A newer watermark is
//! `stale` (default) or recomputed when `OPENFDD_ANALYTICS_CACHE_ON_STALE=recompute`
//! or the request sets `refresh: true`. AFDD `{rule_id}.json` files are not
//! this cache. Rows live in `analytics_result` (see `result_store`). Without a
//! configured Timescale historian the cache is skipped; nothing is written to disk.

use std::sync::Mutex;
use std::time::Instant;

use axum::http::StatusCode;
use axum::Json;
use chrono::{DateTime, SecondsFormat, Utc};
use fdd_store::{
    config_hash, freshness_for_identity, read_plan, AnalyticsCacheKey, AnalyticsResultTable,
    CacheFreshness, CacheIdentity, CacheProvenance, InputWatermark, SessionBook, SessionError,
    SessionKind, StaleAction,
};
use serde_json::{json, Value};

use super::result_store::{ResultStore, STORE_SCHEMA};
use super::{AnalyticsEnvelope, AnalyticsRequest, SCHEMA_VERSION};

/// Semantic result contract. Distinct from storage schema [`STORE_SCHEMA`].
/// Unstamped envelopes written before this field existed are incompatible.
pub const ANALYTICS_RESULT_CONTRACT: &str = "analytics-result-contract-v2";

/// How `serve_with` learns the computation identity.
pub enum CacheWatch {
    /// Production path: scoped Timescale watermark, coverage, and model revision.
    Resolve,
    /// Caller-supplied identity (tests and already-resolved input).
    #[cfg(test)]
    Resolved(CacheIdentity),
}

fn analytics_admission_busy() -> (StatusCode, Json<Value>) {
    (
        StatusCode::TOO_MANY_REQUESTS,
        Json(json!({
            "ok": false,
            "error": "compute admission limit reached (OPENFDD_COMPUTE_MAX_INFLIGHT); retry later",
            "code": "compute_admission_busy",
            "class": "analytics",
        })),
    )
}

fn analytics_request_rejected(detail: String) -> (StatusCode, Json<Value>) {
    (
        StatusCode::BAD_REQUEST,
        Json(json!({
            "ok": false,
            "error": detail,
            "code": "analytics_request_rejected",
            "class": "analytics",
        })),
    )
}

fn analytics_pressure_deferred(notes: &[String], abort: bool) -> (StatusCode, Json<Value>) {
    let status = if abort {
        StatusCode::GATEWAY_TIMEOUT
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    };
    (
        status,
        Json(json!({
            "ok": false,
            "error": if abort {
                "memory abort: refusing expensive analytics before cgroup kill; retry later"
            } else {
                "memory shed: deferring expensive analytics recompute; retry later"
            },
            "code": if abort {
                "memory_abort"
            } else {
                "memory_shed"
            },
            "class": "analytics",
            "notes": notes,
        })),
    )
}

/// Cache hits skip this. Recompute paths must hold a process-wide Analytics
/// permit and refuse when pressure asks to defer expensive compute (#1127 M-01).
async fn compute_with_admission_fallible(
    compute: impl AsyncFnOnce() -> Result<AnalyticsEnvelope, (StatusCode, Json<Value>)>,
) -> Result<AnalyticsEnvelope, (StatusCode, Json<Value>)> {
    let pressure = fdd_resources::sample_pressure();
    if pressure.defer_expensive_compute {
        tracing::warn!(
            target: "security_audit",
            event = "memory_shed",
            shed_state = ?pressure.shed_state,
            percent_used = ?pressure.percent_used,
            "analytics shed under cgroup memory fraction"
        );
        return Err(analytics_pressure_deferred(
            &pressure.notes,
            pressure.abort_in_flight,
        ));
    }
    let permit = fdd_resources::try_acquire_compute(fdd_resources::ComputeClass::Analytics)
        .ok_or_else(analytics_admission_busy)?;
    let inflight = fdd_resources::InFlightGuard::spawn("analytics");
    let cancel = inflight.cancel_flag();
    let envelope = compute().await?;
    if cancel.load(std::sync::atomic::Ordering::SeqCst) || fdd_resources::memory_abort_requested() {
        return Err(analytics_pressure_deferred(
            &["in-flight memory watchdog aborted analytics SQL".into()],
            true,
        ));
    }
    drop(inflight);
    drop(permit);
    Ok(envelope)
}

pub struct ServedAnalytics {
    pub envelope: AnalyticsEnvelope,
    pub cache: Value,
}

/// Timescale product dispatch through the same `analytics_result` path as every
/// other computing `/api/analytics/*` POST.
pub async fn respond_timescale(
    query_id: &str,
    query_version: &str,
    req: &AnalyticsRequest,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let served = serve_fallible(query_id, query_version, req, async || {
        let value = crate::timescale_analytics::respond_query(query_id, query_version, req).await?;
        Ok(crate::timescale_analytics::envelope_from_dispatch_value(
            query_version,
            req,
            value,
        ))
    })
    .await?;
    let _permit = fdd_resources::try_acquire_compute(fdd_resources::ComputeClass::Analytics)
        .ok_or_else(analytics_admission_busy)?;
    Ok(json_body(&served))
}

pub async fn respond(
    query_id: &str,
    query_version: &str,
    req: &AnalyticsRequest,
    compute: impl AsyncFnOnce() -> AnalyticsEnvelope,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let served = serve(query_id, query_version, req, compute).await?;
    // M70-06: JSON construction/serialization is charged to compute admission
    // (serve may have already dropped its permit after SQL/cache work).
    let _permit = fdd_resources::try_acquire_compute(fdd_resources::ComputeClass::Analytics)
        .ok_or_else(analytics_admission_busy)?;
    Ok(json_body(&served))
}

pub async fn serve(
    query_id: &str,
    query_version: &str,
    req: &AnalyticsRequest,
    compute: impl AsyncFnOnce() -> AnalyticsEnvelope,
) -> Result<ServedAnalytics, (StatusCode, Json<Value>)> {
    serve_fallible(query_id, query_version, req, async || Ok(compute().await)).await
}

pub async fn serve_fallible(
    query_id: &str,
    query_version: &str,
    req: &AnalyticsRequest,
    compute: impl AsyncFnOnce() -> Result<AnalyticsEnvelope, (StatusCode, Json<Value>)>,
) -> Result<ServedAnalytics, (StatusCode, Json<Value>)> {
    let store = match super::result_store::store_from_env().await {
        Ok(store) => store,
        Err(reason) => {
            let started = Instant::now();
            let envelope = compute_with_admission_fallible(compute).await?;
            return Ok(skipped(
                envelope,
                started,
                &format!("analytics result cache unavailable: {reason}"),
            ));
        }
    };
    serve_with(
        &store,
        crate::building_sessions::book(),
        (query_id, query_version),
        req,
        stale_action_from_env(),
        CacheWatch::Resolve,
        compute,
    )
    .await
}

pub async fn serve_with(
    store: &ResultStore,
    sessions: &Mutex<SessionBook>,
    query: (&str, &str),
    req: &AnalyticsRequest,
    on_stale: StaleAction,
    watch: CacheWatch,
    compute: impl AsyncFnOnce() -> Result<AnalyticsEnvelope, (StatusCode, Json<Value>)>,
) -> Result<ServedAnalytics, (StatusCode, Json<Value>)> {
    let (query_id, query_version) = query;
    if let Err(detail) = super::validate_analytics_request(req) {
        return Err(analytics_request_rejected(detail));
    }
    let started = Instant::now();
    let Some(building_id) = req
        .query
        .building_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
    else {
        let envelope = compute_with_admission_fallible(compute).await?;
        return Ok(skipped(
            envelope,
            started,
            "building_id required for analytics result cache",
        ));
    };

    let identity = match watch {
        CacheWatch::Resolve => resolve_cache_identity(building_id, req).await,
        #[cfg(test)]
        CacheWatch::Resolved(identity) => identity,
    };
    let config_extension = if query_id == "bas-vs-web-oat" {
        match fdd_tsdb::Tsdb::connect_from_env().await {
            Ok(tsdb) => {
                match crate::timescale_product::resolve_site_oa_t_reference(
                    tsdb.pool(),
                    building_id,
                )
                .await
                {
                    Ok(picked) => {
                        crate::timescale_product::bas_vs_web_oa_t_config_line(picked.as_ref())
                    }
                    Err(_) => "oa_t_ref=unavailable".into(),
                }
            }
            Err(_) => "oa_t_ref=unavailable".into(),
        }
    } else {
        String::new()
    };
    let key = match cache_key(
        building_id,
        query_id,
        query_version,
        req,
        &identity,
        &config_extension,
    ) {
        Ok(key) => key,
        Err(reason) => {
            let envelope = compute_with_admission_fallible(compute).await?;
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

    // Soft-OPEN 371 T1c: peek provenance only — never materialize cached rows
    // before compute admission when serving a durable cache hit.
    let peeked = match store.peek(&key).await {
        Ok(peeked) => peeked,
        Err(err) => {
            tracing::warn!(error = %err, query_id, "analytics result cache peek failed");
            None
        }
    };
    let freshness = match &peeked {
        Some(prov) => freshness_for_identity(prov, &identity),
        None => CacheFreshness::Miss,
    };
    let plan = read_plan(freshness, req.refresh, on_stale);
    if plan.serve_cached && peeked.is_some() {
        let _permit = fdd_resources::try_acquire_compute(fdd_resources::ComputeClass::Analytics)
            .ok_or_else(analytics_admission_busy)?;
        if let Some((table, prov)) = store.read(&key).await.ok().flatten() {
            let envelope = envelope_from_table(&table, &prov, req);
            let cache = cache_status(true, plan.stale, started, &key, &prov, &identity);
            return Ok(ServedAnalytics { envelope, cache });
        }
        // Rare race: row was trimmed after peek — fall through to recompute.
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
    let envelope = compute_with_admission_fallible(compute).await?;
    let table = table_from_envelope(&envelope);
    let provenance = provenance_for(&key, &envelope, &identity);
    let certifiable = input_certifiable(&identity);
    let persistable = cache_persistable(&identity);
    if persistable {
        if let Err(err) = store.write(&key, &table, &provenance).await {
            tracing::warn!(error = %err, query_id, "analytics result cache write failed");
        }
    }
    // A just-computed envelope is fresh only when the input read succeeded.
    let cache = cache_status(false, !certifiable, started, &key, &provenance, &identity);
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
    identity: &CacheIdentity,
    config_extension: &str,
) -> Result<AnalyticsCacheKey, String> {
    fdd_store::safe_partition_value(building_id, "building_id").map_err(|e| e.to_string())?;
    fdd_store::safe_partition_value(query_id, "query_id").map_err(|e| e.to_string())?;
    fdd_store::safe_partition_value(query_version, "query_version").map_err(|e| e.to_string())?;
    let material = if config_extension.is_empty() {
        config_material(req, identity)
    } else {
        format!("{}\n{config_extension}", config_material(req, identity))
    };
    Ok(AnalyticsCacheKey {
        building_id: building_id.to_string(),
        query_id: query_id.to_string(),
        query_version: query_version.to_string(),
        window_start: window_token(req.query.start),
        window_end: window_token(req.query.end),
        config_hash: config_hash(&material),
    })
}

fn window_token(ts: Option<DateTime<Utc>>) -> String {
    ts.map(|t| t.to_rfc3339_opts(SecondsFormat::Secs, true))
        .unwrap_or_else(|| "open".into())
}

fn config_material(req: &AnalyticsRequest, identity: &CacheIdentity) -> String {
    let mut equipment = req.query.equipment_ids.clone().unwrap_or_default();
    equipment.sort();
    format!(
        "req_qv={}\nread_tenant={}\ndt_min={}\ngap={}\nmax_points={}\nequipment={}\nseries={}\nresult_contract={}\nsql_pack={}\nmodel_revision={}",
        req.query.query_version.as_deref().unwrap_or(""),
        req.read_tenant_id.as_deref().unwrap_or(""),
        req.dt_min_f.map(|v| v.to_string()).unwrap_or_default(),
        req.max_gap_seconds
            .map(|v| v.to_string())
            .unwrap_or_default(),
        req.query.max_points.unwrap_or(0),
        equipment.join(","),
        canonical_json(req.series.as_ref().unwrap_or(&Value::Null)),
        identity.result_contract,
        key_component(&identity.sql_pack),
        key_component(&identity.model_revision),
    )
}

/// Empty identity components must not collide with a real fingerprint.
fn key_component(value: &str) -> &str {
    if value.is_empty() {
        "status:unavailable"
    } else {
        value
    }
}

#[cfg(test)]
fn legacy_request_material(req: &AnalyticsRequest) -> String {
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
    let mut coverage = env.coverage.clone();
    if env.oa_t_reference.is_some() || env.web_asof_bound_seconds.is_some() {
        let mut cov = coverage
            .as_ref()
            .and_then(|v| v.as_object())
            .cloned()
            .unwrap_or_default();
        if let Some(ref meta) = env.oa_t_reference {
            cov.insert("oa_t_reference".into(), meta.clone());
        }
        if let Some(bound) = env.web_asof_bound_seconds {
            cov.insert("web_asof_bound_seconds".into(), json!(bound));
        }
        coverage = Some(Value::Object(cov));
    }
    AnalyticsResultTable {
        rows: env.rows.clone(),
        equipment: env.equipment.clone(),
        points: env.points.clone(),
        skipped: env.skipped.clone(),
        warnings: env.warnings.clone(),
        coverage,
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
    let (oa_t_reference, web_asof_bound_seconds) = table
        .coverage
        .as_ref()
        .and_then(|v| v.as_object())
        .map(|cov| {
            (
                cov.get("oa_t_reference").cloned(),
                cov.get("web_asof_bound_seconds").and_then(|v| v.as_f64()),
            )
        })
        .unwrap_or((None, None));
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
        oa_t_reference,
        web_asof_bound_seconds,
    }
}

fn cache_status(
    hit: bool,
    stale: bool,
    started: Instant,
    key: &AnalyticsCacheKey,
    prov: &CacheProvenance,
    identity: &CacheIdentity,
) -> Value {
    let (source, status, order, utc, coverage, error) = match &identity.watermark {
        InputWatermark::Known {
            source,
            order,
            utc,
            coverage,
        } => (
            json!(source),
            json!("known"),
            json!(order),
            json!(utc),
            json!(coverage),
            Value::Null,
        ),
        InputWatermark::Unavailable { reason } => (
            json!("unavailable"),
            json!("unavailable"),
            Value::Null,
            Value::Null,
            Value::Null,
            json!(reason),
        ),
    };
    json!({
        "hit": hit,
        "stale": stale,
        "elapsed_ms": started.elapsed().as_millis() as u64,
        "schema": STORE_SCHEMA,
        "query_id": key.query_id,
        "query_version": key.query_version,
        "config_hash": key.config_hash,
        "building_id": key.building_id,
        "watermark_utc": prov.watermark_utc,
        "watermark_order": prov.watermark_order,
        "historian_watermark_order": order,
        "historian_watermark_utc": utc,
        "watermark_source": source,
        "watermark_status": status,
        "coverage": coverage,
        "result_contract": identity.result_contract,
        "sql_pack": key_component(&identity.sql_pack),
        "model_revision": key_component(&identity.model_revision),
        "watermark_error": error,
    })
}

fn input_certifiable(identity: &CacheIdentity) -> bool {
    !identity.result_contract.is_empty()
        && !identity.sql_pack.is_empty()
        && !identity.model_revision.is_empty()
        && matches!(identity.watermark, InputWatermark::Known { .. })
}

fn historian_has_samples(identity: &CacheIdentity) -> bool {
    match &identity.watermark {
        InputWatermark::Known { coverage, .. } => coverage
            .strip_prefix("samples=")
            .and_then(|rest| rest.split(';').next())
            .and_then(|token| token.parse::<i64>().ok())
            .is_some_and(|count| count > 0),
        InputWatermark::Unavailable { .. } => false,
    }
}

fn cache_persistable(identity: &CacheIdentity) -> bool {
    input_certifiable(identity) && historian_has_samples(identity)
}

fn provenance_for(
    key: &AnalyticsCacheKey,
    envelope: &AnalyticsEnvelope,
    identity: &CacheIdentity,
) -> CacheProvenance {
    let (order, utc, source, status, coverage) = match &identity.watermark {
        InputWatermark::Known {
            source,
            order,
            utc,
            coverage,
        } => (
            *order,
            utc.clone(),
            source.clone(),
            "known".to_string(),
            coverage.clone(),
        ),
        InputWatermark::Unavailable { .. } => (
            0,
            String::new(),
            String::new(),
            "unavailable".to_string(),
            String::new(),
        ),
    };
    CacheProvenance {
        building_id: key.building_id.clone(),
        query_id: key.query_id.clone(),
        query_version: key.query_version.clone(),
        window_start: key.window_start.clone(),
        window_end: key.window_end.clone(),
        config_hash: key.config_hash.clone(),
        watermark_order: order,
        watermark_utc: utc,
        generated_at: envelope
            .generated_at
            .to_rfc3339_opts(SecondsFormat::Secs, true),
        engine: envelope.engine.clone(),
        result_query_version: envelope.query_version.clone(),
        result_contract: identity.result_contract.clone(),
        sql_pack: identity.sql_pack.clone(),
        model_revision: identity.model_revision.clone(),
        watermark_source: source,
        watermark_status: status,
        coverage,
    }
}

async fn resolve_cache_identity(building_id: &str, req: &AnalyticsRequest) -> CacheIdentity {
    let sql_pack = crate::timescale_product::analytics_cache_sql_pack().unwrap_or_default();
    let equipment = req.query.equipment_ids.clone().unwrap_or_default();
    let input = crate::timescale_product::read_analytics_cache_input(
        building_id,
        req.query.start,
        req.query.end,
        &equipment,
    )
    .await;
    let model_revision = input.model_revision.unwrap_or_default();
    let watermark = match input.watermark {
        Ok(watermark) => InputWatermark::Known {
            source: "timescale".into(),
            order: watermark.order,
            utc: watermark.utc,
            coverage: watermark.coverage,
        },
        Err(reason) => InputWatermark::Unavailable { reason },
    };
    CacheIdentity {
        result_contract: ANALYTICS_RESULT_CONTRACT.into(),
        sql_pack,
        model_revision,
        watermark,
    }
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
    use crate::analytics::result_store::memory::MemoryStore;
    use crate::analytics::{envelope, AnalyticsQuery};
    use crate::test_env_lock::lock_env;
    use fdd_store::SessionLimits;
    use std::fs;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Arc, MutexGuard};

    /// GitHub runners often report high host RSS; pin a tiny synthetic cgroup so
    /// analytics cache tests exercise admission/cache logic, not live shed.
    struct CgroupTestEnv {
        _env_lock: MutexGuard<'static, ()>,
        _dir: tempfile::TempDir,
        prev_cgroup: Option<String>,
    }

    impl CgroupTestEnv {
        fn low_pressure() -> Self {
            let _env_lock = lock_env();
            let prev_cgroup = std::env::var("OPENFDD_CGROUP_DIR").ok();
            let tmp = tempfile::tempdir().unwrap();
            let cg = tmp.path().join("cg");
            fs::create_dir_all(&cg).unwrap();
            fs::write(cg.join("memory.current"), "1000\n").unwrap();
            fs::write(cg.join("memory.max"), "1000000000\n").unwrap();
            std::env::set_var("OPENFDD_CGROUP_DIR", &cg);
            Self {
                _env_lock,
                _dir: tmp,
                prev_cgroup,
            }
        }
    }

    impl Drop for CgroupTestEnv {
        fn drop(&mut self) {
            match self.prev_cgroup.take() {
                Some(v) => std::env::set_var("OPENFDD_CGROUP_DIR", v),
                None => std::env::remove_var("OPENFDD_CGROUP_DIR"),
            }
        }
    }

    fn req(building: &str) -> AnalyticsRequest {
        AnalyticsRequest {
            query: AnalyticsQuery {
                building_id: Some(building.into()),
                ..AnalyticsQuery::default()
            },
            ..AnalyticsRequest::default()
        }
    }

    fn mem_store() -> ResultStore {
        ResultStore::Memory(Arc::new(MemoryStore::new(64)))
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
        let _cg = CgroupTestEnv::low_pressure();
        let store = mem_store();
        let sessions = Mutex::new(SessionBook::new(limits()));
        let calls = Arc::new(AtomicUsize::new(0));
        let calls_hit = calls.clone();
        let first = serve_with(
            &store,
            &sessions,
            ("runtime", "runtime-v1"),
            &req("site-a"),
            StaleAction::ServeStale,
            CacheWatch::Resolved(timescale_identity("model-a", 1, "samples=1;series=1")),
            async || {
                calls_hit.fetch_add(1, Ordering::SeqCst);
                let mut env = envelope("runtime-v1", &req("site-a").query, Vec::new());
                env.rows
                    .push(json!({"equipment_id": "AHU_1", "run_hours": 3.5}));
                env.engine = "datafusion".into();
                Ok(env)
            },
        )
        .await
        .unwrap();
        assert_eq!(first.cache["hit"], false);
        assert!(first.cache.get("elapsed_ms").is_some());
        assert!(sessions.lock().unwrap().historian_resident().is_empty());

        let calls_second = calls.clone();
        let second = serve_with(
            &store,
            &sessions,
            ("runtime", "runtime-v1"),
            &req("site-a"),
            StaleAction::ServeStale,
            CacheWatch::Resolved(timescale_identity("model-a", 1, "samples=1;series=1")),
            async || {
                calls_second.fetch_add(1, Ordering::SeqCst);
                Ok(envelope("runtime-v1", &req("site-a").query, Vec::new()))
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
        let _cg = CgroupTestEnv::low_pressure();
        let store = mem_store();
        let sessions = Mutex::new(SessionBook::new(limits()));
        let calls = Arc::new(AtomicUsize::new(0));
        let c1 = calls.clone();
        let _ = serve_with(
            &store,
            &sessions,
            ("sensor-faults", "sensor-faults-v1"),
            &req("site-a"),
            StaleAction::ServeStale,
            CacheWatch::Resolved(timescale_identity("model-a", 1, "samples=1;series=1")),
            async || {
                c1.fetch_add(1, Ordering::SeqCst);
                let mut env = envelope("sensor-faults-v1", &req("site-a").query, Vec::new());
                env.rows
                    .push(json!({"equipment_id": "AHU_1", "fault_hours": 1.0}));
                Ok(env)
            },
        )
        .await
        .unwrap();
        let c2 = calls.clone();
        let stale = serve_with(
            &store,
            &sessions,
            ("sensor-faults", "sensor-faults-v1"),
            &req("site-a"),
            StaleAction::ServeStale,
            CacheWatch::Resolved(timescale_identity("model-a", 2, "samples=2;series=1")),
            async || {
                c2.fetch_add(1, Ordering::SeqCst);
                Ok(envelope(
                    "sensor-faults-v1",
                    &req("site-a").query,
                    Vec::new(),
                ))
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
            &store,
            &sessions,
            ("sensor-faults", "sensor-faults-v1"),
            &refresh,
            StaleAction::ServeStale,
            CacheWatch::Resolved(timescale_identity("model-a", 2, "samples=2;series=1")),
            async || {
                c3.fetch_add(1, Ordering::SeqCst);
                let mut env = envelope("sensor-faults-v1", &req("site-a").query, Vec::new());
                env.rows
                    .push(json!({"equipment_id": "AHU_1", "fault_hours": 2.0}));
                Ok(env)
            },
        )
        .await
        .unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 2);
        assert_eq!(fresh.cache["hit"], false);
        assert_eq!(fresh.cache["stale"], false);
        assert_eq!(fresh.envelope.rows[0]["fault_hours"], 2.0);
    }

    #[tokio::test]
    async fn cache_miss_refuses_when_compute_admission_saturated() {
        let _cg = CgroupTestEnv::low_pressure();
        let mut held = Vec::new();
        loop {
            match fdd_resources::try_acquire_compute(fdd_resources::ComputeClass::ManualFdd) {
                Some(p) => held.push(p),
                None => break,
            }
            if held.len() > 64 {
                panic!("semaphore did not saturate");
            }
        }
        let store = mem_store();
        let sessions = Mutex::new(SessionBook::new(limits()));
        let err = match serve_with(
            &store,
            &sessions,
            ("runtime", "runtime-v1"),
            &req("site-busy"),
            StaleAction::ServeStale,
            CacheWatch::Resolved(timescale_identity("model-a", 1, "samples=1;series=1")),
            async || Ok(envelope("runtime-v1", &req("site-busy").query, Vec::new())),
        )
        .await
        {
            Ok(_) => panic!("saturated admission must refuse analytics recompute"),
            Err(e) => e,
        };
        assert_eq!(err.0, StatusCode::TOO_MANY_REQUESTS);
        assert_eq!(err.1["code"], json!("compute_admission_busy"));
        drop(held);
    }

    fn timescale_identity(model: &str, order: u64, coverage: &str) -> CacheIdentity {
        CacheIdentity {
            result_contract: ANALYTICS_RESULT_CONTRACT.into(),
            sql_pack: "analytics=test-pack;fdd=test-pack".into(),
            model_revision: model.into(),
            watermark: InputWatermark::Known {
                source: "timescale".into(),
                order,
                utc: "2026-06-01T00:00:00Z".into(),
                coverage: coverage.into(),
            },
        }
    }

    fn duplicate_scatter() -> Vec<Value> {
        vec![
            json!({
                "equipment_id": "AHU_1",
                "timestamp_utc": "2026-06-01T00:00:00Z",
                "dry_bulb_f": 70.0
            }),
            json!({
                "equipment_id": "AHU_1",
                "timestamp_utc": "2026-06-01T00:00:00Z",
                "dry_bulb_f": 71.0
            }),
        ]
    }

    fn corrected_scatter() -> AnalyticsEnvelope {
        let mut env = envelope("rcx-preset-v1", &req("site-a").query, Vec::new());
        env.points = vec![json!({
            "equipment_id": "AHU_1",
            "timestamp_utc": "2026-06-01T00:00:00Z",
            "x_role": "web_oa_t",
            "x_point": "weather.web_oa_t",
            "oat_f": 60.0
        })];
        env.generated_at = DateTime::parse_from_rfc3339("2026-06-02T00:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        env
    }

    async fn write_legacy_scatter(store: &ResultStore, request: &AnalyticsRequest) {
        let hash = config_hash(&legacy_request_material(request));
        let key = AnalyticsCacheKey {
            building_id: "site-a".into(),
            query_id: "rcx-preset".into(),
            query_version: "rcx-preset-v1".into(),
            window_start: "open".into(),
            window_end: "open".into(),
            config_hash: hash.clone(),
        };
        let table = AnalyticsResultTable {
            rows: Vec::new(),
            equipment: Vec::new(),
            points: duplicate_scatter(),
            skipped: Vec::new(),
            warnings: Vec::new(),
            coverage: None,
            engine: "timescale-sql".into(),
            result_query_version: "rcx-preset-v1".into(),
        };
        let provenance = CacheProvenance {
            building_id: key.building_id.clone(),
            query_id: key.query_id.clone(),
            query_version: key.query_version.clone(),
            window_start: key.window_start.clone(),
            window_end: key.window_end.clone(),
            config_hash: hash,
            watermark_order: 0,
            watermark_utc: String::new(),
            generated_at: "2026-06-01T01:00:32Z".into(),
            engine: "timescale-sql".into(),
            result_query_version: "rcx-preset-v1".into(),
            result_contract: String::new(),
            sql_pack: String::new(),
            model_revision: String::new(),
            watermark_source: String::new(),
            watermark_status: String::new(),
            coverage: String::new(),
        };
        store.write(&key, &table, &provenance).await.unwrap();
    }

    #[tokio::test]
    async fn preupgrade_envelope_recomputes_and_refresh_survives_restart() {
        let _cg = CgroupTestEnv::low_pressure();
        let store = mem_store();
        let request = req("site-a");
        write_legacy_scatter(&store, &request).await;
        let legacy_hash = config_hash(&legacy_request_material(&request));
        let identity = timescale_identity("model-a", 20260601000000, "samples=4;series=2");
        let current_hash = config_hash(&config_material(&request, &identity));
        assert_ne!(legacy_hash, current_hash);

        let sessions = Mutex::new(SessionBook::new(limits()));
        let calls = Arc::new(AtomicUsize::new(0));
        let calls_first = calls.clone();
        let first = serve_with(
            &store,
            &sessions,
            ("rcx-preset", "rcx-preset-v1"),
            &request,
            StaleAction::ServeStale,
            CacheWatch::Resolved(identity.clone()),
            async || {
                calls_first.fetch_add(1, Ordering::SeqCst);
                Ok(corrected_scatter())
            },
        )
        .await
        .unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(first.cache["hit"], false);
        assert_eq!(first.cache["stale"], false);
        assert_eq!(first.cache["schema"], json!(STORE_SCHEMA));
        assert_eq!(STORE_SCHEMA, "analytics-result-postgres-v1");
        assert_eq!(first.envelope.points.len(), 1);
        assert_eq!(first.envelope.points[0]["x_role"], "web_oa_t");

        let restarted = Mutex::new(SessionBook::new(limits()));
        let calls_second = calls.clone();
        let second = serve_with(
            &store,
            &restarted,
            ("rcx-preset", "rcx-preset-v1"),
            &request,
            StaleAction::ServeStale,
            CacheWatch::Resolved(identity.clone()),
            async || {
                calls_second.fetch_add(1, Ordering::SeqCst);
                Ok(corrected_scatter())
            },
        )
        .await
        .unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(second.cache["hit"], true);
        assert_eq!(second.cache["stale"], false);
        assert_eq!(second.envelope.points[0]["x_role"], "web_oa_t");
        assert_eq!(
            second.envelope.generated_at, first.envelope.generated_at,
            "refresh result survives a new session"
        );

        let mut refresh = request.clone();
        refresh.refresh = true;
        let calls_refresh = calls.clone();
        let refreshed = serve_with(
            &store,
            &restarted,
            ("rcx-preset", "rcx-preset-v1"),
            &refresh,
            StaleAction::ServeStale,
            CacheWatch::Resolved(identity.clone()),
            async || {
                calls_refresh.fetch_add(1, Ordering::SeqCst);
                let mut env = corrected_scatter();
                env.points[0]["oat_f"] = json!(61.0);
                env.generated_at = DateTime::parse_from_rfc3339("2026-06-03T00:00:00Z")
                    .unwrap()
                    .with_timezone(&Utc);
                Ok(env)
            },
        )
        .await
        .unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 2);
        assert_eq!(refreshed.cache["hit"], false);
        assert_eq!(refreshed.envelope.points[0]["oat_f"], 61.0);

        let again = Mutex::new(SessionBook::new(limits()));
        let calls_again = calls.clone();
        let persisted = serve_with(
            &store,
            &again,
            ("rcx-preset", "rcx-preset-v1"),
            &request,
            StaleAction::ServeStale,
            CacheWatch::Resolved(identity),
            async || {
                calls_again.fetch_add(1, Ordering::SeqCst);
                Ok(corrected_scatter())
            },
        )
        .await
        .unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 2);
        assert_eq!(persisted.cache["hit"], true);
        assert_eq!(persisted.cache["stale"], false);
        assert_eq!(persisted.envelope.points[0]["oat_f"], 61.0);
        assert_eq!(
            persisted.envelope.generated_at,
            refreshed.envelope.generated_at
        );
    }

    #[test]
    fn bas_vs_web_config_hash_includes_oa_t_reference_line() {
        let request = req("site-a");
        let identity = timescale_identity("model-a", 1, "samples=1;series=1");
        let default_key = cache_key(
            "site-a",
            "bas-vs-web-oat",
            "bas-vs-web-oat-v4",
            &request,
            &identity,
            "oa_t_ref=WX.oa_t_a=default_lowest_binding",
        )
        .unwrap();
        let primary_key = cache_key(
            "site-a",
            "bas-vs-web-oat",
            "bas-vs-web-oat-v4",
            &request,
            &identity,
            "oa_t_ref=WX.oa_t_b=primary_reference",
        )
        .unwrap();
        assert_ne!(default_key.config_hash, primary_key.config_hash);
    }

    #[tokio::test]
    async fn incompatible_stamp_on_the_current_partition_recomputes() {
        let _cg = CgroupTestEnv::low_pressure();
        let store = mem_store();
        let sessions = Mutex::new(SessionBook::new(limits()));
        let request = req("site-a");
        let identity = timescale_identity("model-a", 1, "samples=1;series=1");
        let key = cache_key(
            "site-a",
            "rcx-preset",
            "rcx-preset-v1",
            &request,
            &identity,
            "",
        )
        .unwrap();
        let table = AnalyticsResultTable {
            rows: Vec::new(),
            equipment: Vec::new(),
            points: duplicate_scatter(),
            skipped: Vec::new(),
            warnings: Vec::new(),
            coverage: None,
            engine: "timescale-sql".into(),
            result_query_version: "rcx-preset-v1".into(),
        };
        let mut provenance = provenance_for(&key, &corrected_scatter(), &identity);
        provenance.result_contract.clear();
        provenance.sql_pack.clear();
        provenance.model_revision.clear();
        provenance.watermark_status.clear();
        provenance.coverage.clear();
        provenance.watermark_order = 0;
        store.write(&key, &table, &provenance).await.unwrap();

        let served = serve_with(
            &store,
            &sessions,
            ("rcx-preset", "rcx-preset-v1"),
            &request,
            StaleAction::ServeStale,
            CacheWatch::Resolved(identity),
            async || Ok(corrected_scatter()),
        )
        .await
        .unwrap();
        assert_eq!(served.cache["hit"], false);
        assert_eq!(served.cache["stale"], false);
        assert_eq!(served.envelope.points.len(), 1);
        assert_eq!(served.envelope.points[0]["x_role"], "web_oa_t");
    }

    #[tokio::test]
    async fn timescale_advance_is_stale() {
        let _cg = CgroupTestEnv::low_pressure();
        let store = mem_store();
        let sessions = Mutex::new(SessionBook::new(limits()));
        let calls = Arc::new(AtomicUsize::new(0));
        let request = req("site-a");
        let first_id = timescale_identity("model-a", 20260601000000, "samples=4;series=2");
        let c1 = calls.clone();
        let _ = serve_with(
            &store,
            &sessions,
            ("rcx-preset", "rcx-preset-v1"),
            &request,
            StaleAction::ServeStale,
            CacheWatch::Resolved(first_id),
            async || {
                c1.fetch_add(1, Ordering::SeqCst);
                Ok(corrected_scatter())
            },
        )
        .await
        .unwrap();
        let c2 = calls.clone();
        let advanced = timescale_identity("model-a", 20260602000000, "samples=5;series=2");
        let stale = serve_with(
            &store,
            &sessions,
            ("rcx-preset", "rcx-preset-v1"),
            &request,
            StaleAction::ServeStale,
            CacheWatch::Resolved(advanced),
            async || {
                c2.fetch_add(1, Ordering::SeqCst);
                Ok(corrected_scatter())
            },
        )
        .await
        .unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(stale.cache["hit"], true);
        assert_eq!(stale.cache["stale"], true);
        assert_eq!(stale.cache["watermark_status"], json!("known"));
        assert_eq!(stale.envelope.points[0]["oat_f"], 60.0);
    }

    #[tokio::test]
    async fn model_remap_and_sql_pack_are_distinct_identities() {
        let _cg = CgroupTestEnv::low_pressure();
        let store = mem_store();
        let sessions = Mutex::new(SessionBook::new(limits()));
        let request = req("site-a");
        let calls = Arc::new(AtomicUsize::new(0));
        let original = timescale_identity("model-a", 1, "samples=1;series=1");
        let c1 = calls.clone();
        let _ = serve_with(
            &store,
            &sessions,
            ("rcx-preset", "rcx-preset-v1"),
            &request,
            StaleAction::ServeStale,
            CacheWatch::Resolved(original.clone()),
            async || {
                c1.fetch_add(1, Ordering::SeqCst);
                Ok(corrected_scatter())
            },
        )
        .await
        .unwrap();
        let mut remapped = original.clone();
        remapped.model_revision = "model-b".into();
        let c2 = calls.clone();
        let remapped_hit = serve_with(
            &store,
            &sessions,
            ("rcx-preset", "rcx-preset-v1"),
            &request,
            StaleAction::ServeStale,
            CacheWatch::Resolved(remapped),
            async || {
                c2.fetch_add(1, Ordering::SeqCst);
                let mut env = corrected_scatter();
                env.points[0]["x_role"] = json!("web_oa_t_remapped");
                Ok(env)
            },
        )
        .await
        .unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 2);
        assert_eq!(remapped_hit.cache["hit"], false);
        assert_eq!(
            remapped_hit.envelope.points[0]["x_role"],
            "web_oa_t_remapped"
        );

        let mut other_pack = original.clone();
        other_pack.sql_pack = "analytics=other;fdd=other".into();
        let c3 = calls.clone();
        let pack_hit = serve_with(
            &store,
            &sessions,
            ("rcx-preset", "rcx-preset-v1"),
            &request,
            StaleAction::ServeStale,
            CacheWatch::Resolved(other_pack),
            async || {
                c3.fetch_add(1, Ordering::SeqCst);
                Ok(corrected_scatter())
            },
        )
        .await
        .unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 3);
        assert_eq!(pack_hit.cache["hit"], false);
        assert_ne!(
            config_hash(&config_material(&request, &original)),
            config_hash(&config_material(
                &request,
                &timescale_identity("model-b", 1, "samples=1;series=1")
            ))
        );
    }

    #[tokio::test]
    async fn broken_watermark_is_never_a_fresh_hit() {
        let _cg = CgroupTestEnv::low_pressure();
        let store = mem_store();
        let sessions = Mutex::new(SessionBook::new(limits()));
        let request = req("site-a");
        let calls = Arc::new(AtomicUsize::new(0));
        let known = timescale_identity("model-a", 1, "samples=1;series=1");
        let c1 = calls.clone();
        let _ = serve_with(
            &store,
            &sessions,
            ("rcx-preset", "rcx-preset-v1"),
            &request,
            StaleAction::ServeStale,
            CacheWatch::Resolved(known.clone()),
            async || {
                c1.fetch_add(1, Ordering::SeqCst);
                Ok(corrected_scatter())
            },
        )
        .await
        .unwrap();
        let mut broken = known.clone();
        broken.watermark = InputWatermark::Unavailable {
            reason: "timescale watermark read failed".into(),
        };
        let c2 = calls.clone();
        let stale = serve_with(
            &store,
            &sessions,
            ("rcx-preset", "rcx-preset-v1"),
            &request,
            StaleAction::ServeStale,
            CacheWatch::Resolved(broken.clone()),
            async || {
                c2.fetch_add(1, Ordering::SeqCst);
                Ok(corrected_scatter())
            },
        )
        .await
        .unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(stale.cache["hit"], true);
        assert_eq!(stale.cache["stale"], true);
        assert_eq!(stale.cache["watermark_status"], json!("unavailable"));
        assert_eq!(stale.cache["historian_watermark_order"], Value::Null);
        assert_eq!(
            stale.cache["watermark_error"],
            json!("timescale watermark read failed")
        );

        let c3 = calls.clone();
        let again = serve_with(
            &store,
            &sessions,
            ("rcx-preset", "rcx-preset-v1"),
            &request,
            StaleAction::ServeStale,
            CacheWatch::Resolved(broken),
            async || {
                c3.fetch_add(1, Ordering::SeqCst);
                Ok(corrected_scatter())
            },
        )
        .await
        .unwrap();
        assert_eq!(again.cache["stale"], true);
        assert_ne!(
            (
                again.cache["hit"].as_bool().unwrap_or(false),
                again.cache["stale"].as_bool().unwrap_or(true)
            ),
            (true, false)
        );
    }

    #[tokio::test]
    async fn tenants_do_not_share_a_cache_hit() {
        let _cg = CgroupTestEnv::low_pressure();
        let store = mem_store();
        let sessions = Mutex::new(SessionBook::new(limits()));
        let identity = timescale_identity("model-a", 1, "samples=1;series=1");
        let mut site_a = req("site-a");
        site_a.read_tenant_id = Some("tenant-a".into());
        let _ = serve_with(
            &store,
            &sessions,
            ("rcx-preset", "rcx-preset-v1"),
            &site_a,
            StaleAction::ServeStale,
            CacheWatch::Resolved(identity.clone()),
            async || Ok(corrected_scatter()),
        )
        .await
        .unwrap();
        let mut site_b = req("site-b");
        site_b.read_tenant_id = Some("tenant-b".into());
        let calls = Arc::new(AtomicUsize::new(0));
        let calls_b = calls.clone();
        let other = serve_with(
            &store,
            &sessions,
            ("rcx-preset", "rcx-preset-v1"),
            &site_b,
            StaleAction::ServeStale,
            CacheWatch::Resolved(identity),
            async || {
                calls_b.fetch_add(1, Ordering::SeqCst);
                let mut env = corrected_scatter();
                env.points[0]["equipment_id"] = json!("AHU_9");
                Ok(env)
            },
        )
        .await
        .unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(other.cache["hit"], false);
        assert_eq!(other.envelope.points[0]["equipment_id"], "AHU_9");
    }
}
