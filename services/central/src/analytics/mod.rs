//! Central analytics envelopes and family compute modules (Milestone C/D).
//!
//! Engine labels:
//! - [`CENTRAL_ENGINE`] — pure Rust / Arrow-ready algorithms (inline samples)
//! - [`DF_ENGINE`] — DataFusion SQL over historian Parquet (see `historian`)

pub mod economizer;
pub mod historian;
pub mod mechanical_cooling;
pub mod metering;
pub mod mv_change_point;
pub mod plant;
pub mod plant_health;
pub mod rcx;
pub mod rcx_presets;
pub mod result_cache;
pub mod runtime;
pub mod schedule;
pub mod sensor_health;
pub mod vav_health;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

/// Pure Rust / inline-sample engine id.
pub const CENTRAL_ENGINE: &str = "central-analytics-v1";
/// DataFusion SQL / historian Parquet engine id (set only when DF path executes).
pub const DF_ENGINE: &str = "datafusion";
/// Alias for [`CENTRAL_ENGINE`] (legacy call sites / tests).
pub const ENGINE: &str = CENTRAL_ENGINE;
pub const SCHEMA_VERSION: &str = "analytics-envelope-v1";

pub const QV_RUNTIME: &str = "runtime-v1";
pub const QV_SENSOR_HEALTH: &str = "sensor-health-v1";
pub const QV_SCHEDULE: &str = "schedule-v1";
pub const QV_MECHANICAL_COOLING: &str = "mechanical-cooling-v1";
pub const QV_ECONOMIZER: &str = "economizer-diagnostics-v1";
pub const QV_RCX_AHU: &str = "rcx-ahu-v1";
pub const QV_RCX_VAV: &str = "rcx-vav-v1";
pub const QV_METERING: &str = "metering-v1";
/// Thin IPMVP Option C monthly DD-OLS twin (Wave S4 Soft-OPEN).
pub const QV_MV_CHANGE_POINT: &str = "mv-change-point-v1";
pub const QV_SETPOINTS: &str = "setpoints-v1";
pub const QV_DIURNAL: &str = "sensor-diurnal-v1";
pub const QV_TOPOLOGY: &str = "topology-v1";
pub const QV_SENSOR_STATS: &str = "sensor-stats-v1";
pub const QV_SQL_ANOMALY: &str = "sql-anomaly-v1";

/// Shared query fields for `/api/analytics/*` requests.
#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct AnalyticsQuery {
    #[serde(default)]
    pub job_id: Option<String>,
    #[serde(default)]
    pub run_id: Option<String>,
    /// Site / building scope (OFDD-070). When set, historian analytics read only
    /// `building={id}/` under the parquet root so a site's Overview economizer
    /// (and other historian families) are not contaminated by other packages.
    #[serde(default)]
    pub building_id: Option<String>,
    #[serde(default)]
    pub equipment_ids: Option<Vec<String>>,
    #[serde(default)]
    pub start: Option<DateTime<Utc>>,
    #[serde(default)]
    pub end: Option<DateTime<Utc>>,
    #[serde(default)]
    pub max_points: Option<usize>,
    #[serde(default)]
    pub query_version: Option<String>,
}

/// Request body: query fields plus optional inline samples/series for compute.
#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct AnalyticsRequest {
    #[serde(flatten)]
    pub query: AnalyticsQuery,
    /// Runtime boolean samples (equipment_id, timestamp, on).
    #[serde(default)]
    pub samples: Option<Vec<runtime::RuntimeSample>>,
    /// Family-specific inline series / point payloads (JSON object or array).
    #[serde(default)]
    pub series: Option<Value>,
    /// Gap clip for runtime Δt integration (seconds).
    #[serde(default)]
    pub max_gap_seconds: Option<f64>,
    /// Economizer |OAT−RAT| identifiability gate (°F).
    #[serde(default)]
    pub dt_min_f: Option<f64>,
    /// Recompute even when the parquet result cache is fresh.
    #[serde(default)]
    pub refresh: bool,
    /// Session read tenant. Not a client field: routes set it from the JWT
    /// or the control-plane owner so the cache key matches the historian root.
    #[serde(default, skip)]
    pub read_tenant_id: Option<String>,
}

/// Hard ceiling for authenticated analytics windows (#1169). Override with
/// `OPENFDD_ANALYTICS_MAX_LOOKBACK_DAYS` (default 366).
pub fn analytics_max_lookback_days() -> i64 {
    std::env::var("OPENFDD_ANALYTICS_MAX_LOOKBACK_DAYS")
        .ok()
        .and_then(|value| value.parse().ok())
        .filter(|value| *value > 0)
        .unwrap_or(366)
}

/// Reject ZAP-shaped "scan the world" requests before DataFusion allocation.
pub fn validate_analytics_request(req: &AnalyticsRequest) -> Result<(), String> {
    let has_inline = req
        .samples
        .as_ref()
        .is_some_and(|samples| !samples.is_empty())
        || req.series.as_ref().is_some_and(|series| !series.is_null());
    let building = req
        .query
        .building_id
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty());
    if building.is_none() && !has_inline {
        return Err(
            "building_id is required for historian analytics (or provide inline samples/series)"
                .into(),
        );
    }
    let max_days = analytics_max_lookback_days();
    let end = req.query.end.unwrap_or_else(Utc::now);
    if let Some(start) = req.query.start {
        if end < start {
            return Err("query.end must be >= query.start".into());
        }
        if (end - start).num_days() > max_days {
            return Err(format!(
                "analytics lookback exceeds OPENFDD_ANALYTICS_MAX_LOOKBACK_DAYS={max_days}"
            ));
        }
    }
    if let Some(max_points) = req.query.max_points {
        if max_points > 500_000 {
            return Err("max_points exceeds 500000".into());
        }
    }
    Ok(())
}

/// Typed analytics response envelope (no Plotly JSON).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnalyticsEnvelope {
    pub schema_version: String,
    pub query_version: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub job_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub run_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub input_fingerprint: Option<String>,
    pub generated_at: DateTime<Utc>,
    pub engine: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub coverage: Option<Value>,
    #[serde(default)]
    pub warnings: Vec<String>,
    #[serde(default)]
    pub rows: Vec<Value>,
    #[serde(default)]
    pub equipment: Vec<Value>,
    #[serde(default)]
    pub points: Vec<Value>,
    #[serde(default)]
    pub skipped: Vec<Value>,
}

impl AnalyticsEnvelope {
    pub fn to_json(&self) -> Value {
        serde_json::to_value(self).unwrap_or_else(|_| json!({ "ok": false }))
    }
}

/// Build a populated envelope from query context (defaults to [`ENGINE`] / [`CENTRAL_ENGINE`]).
pub fn envelope(
    query_version: &str,
    query: &AnalyticsQuery,
    warnings: Vec<String>,
) -> AnalyticsEnvelope {
    envelope_with_engine(query_version, query, warnings, ENGINE)
}

/// Build an envelope with an explicit engine label (e.g. [`DF_ENGINE`]).
pub fn envelope_with_engine(
    query_version: &str,
    query: &AnalyticsQuery,
    warnings: Vec<String>,
    engine: &str,
) -> AnalyticsEnvelope {
    AnalyticsEnvelope {
        schema_version: SCHEMA_VERSION.into(),
        query_version: query_version.into(),
        job_id: query.job_id.clone(),
        run_id: query.run_id.clone(),
        input_fingerprint: None,
        generated_at: Utc::now(),
        engine: engine.into(),
        coverage: None,
        warnings,
        rows: Vec::new(),
        equipment: Vec::new(),
        points: Vec::new(),
        skipped: Vec::new(),
    }
}

/// Reject unknown query_version with a stable warning (still returns envelope).
pub fn version_mismatch_warning(expected: &str, got: Option<&str>) -> Option<String> {
    match got {
        None => None,
        Some(v) if v == expected => None,
        Some(v) => Some(format!(
            "unknown or unsupported query_version '{v}'; responding with '{expected}'"
        )),
    }
}

pub fn resolve_query_version(req: &AnalyticsRequest, expected: &str) -> (String, Vec<String>) {
    let mut warnings = Vec::new();
    if let Some(w) = version_mismatch_warning(expected, req.query.query_version.as_deref()) {
        warnings.push(w);
    }
    (expected.to_string(), warnings)
}

/// Merge request context (query_version, job/run ids, version warnings) into an
/// envelope produced by a historian DataFusion path. Request-derived warnings
/// are prepended so provenance stays honest.
pub fn finalize_historian(
    req: &AnalyticsRequest,
    mut env: AnalyticsEnvelope,
    expected_qv: &str,
) -> AnalyticsEnvelope {
    let (qv, mut warnings) = resolve_query_version(req, expected_qv);
    env.query_version = qv;
    env.job_id = req.query.job_id.clone().or(env.job_id);
    env.run_id = req.query.run_id.clone().or(env.run_id);
    warnings.append(&mut env.warnings);
    env.warnings = warnings;
    env
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn envelope_has_stable_field_names() {
        let q = AnalyticsQuery {
            job_id: Some("job-1".into()),
            run_id: Some("run-1".into()),
            ..Default::default()
        };
        let env = envelope(QV_RUNTIME, &q, vec!["note".into()]);
        let v = env.to_json();
        for key in [
            "schema_version",
            "query_version",
            "job_id",
            "run_id",
            "generated_at",
            "engine",
            "warnings",
            "rows",
            "equipment",
            "points",
            "skipped",
        ] {
            assert!(v.get(key).is_some(), "missing {key}");
        }
        assert_eq!(v["engine"], CENTRAL_ENGINE);
        assert_eq!(ENGINE, CENTRAL_ENGINE);
        assert_eq!(v["query_version"], QV_RUNTIME);
        assert!(v.get("plotly").is_none());
    }

    #[test]
    fn envelope_with_engine_sets_datafusion() {
        let q = AnalyticsQuery::default();
        let env = envelope_with_engine(QV_RUNTIME, &q, vec![], DF_ENGINE);
        assert_eq!(env.engine, DF_ENGINE);
        assert_eq!(env.to_json()["engine"], DF_ENGINE);
    }

    #[test]
    fn missing_inline_data_warns_honestly() {
        let env = sensor_health::handle(&AnalyticsRequest {
            query: AnalyticsQuery::default(),
            ..Default::default()
        });
        assert!(env.equipment.is_empty());
        assert!(env.warnings.iter().any(|w| w.contains("no inline")));
        assert_eq!(env.engine, CENTRAL_ENGINE);
    }

    #[test]
    fn unknown_query_version_warns() {
        let w = version_mismatch_warning(QV_RUNTIME, Some("runtime-v99"));
        assert!(w.unwrap().contains("runtime-v99"));
        assert!(version_mismatch_warning(QV_RUNTIME, Some(QV_RUNTIME)).is_none());
    }

    #[test]
    fn validate_rejects_missing_building_without_inline() {
        let err = validate_analytics_request(&AnalyticsRequest::default()).unwrap_err();
        assert!(err.contains("building_id"));
    }

    #[test]
    fn validate_rejects_unbounded_lookback() {
        let req = AnalyticsRequest {
            query: AnalyticsQuery {
                building_id: Some("BUILDING_100".into()),
                start: Some(Utc::now() - chrono::Duration::days(500)),
                end: Some(Utc::now()),
                ..Default::default()
            },
            ..Default::default()
        };
        let err = validate_analytics_request(&req).unwrap_err();
        assert!(err.contains("lookback"));
    }

    #[test]
    fn validate_accepts_scoped_short_window() {
        let req = AnalyticsRequest {
            query: AnalyticsQuery {
                building_id: Some("BUILDING_100".into()),
                start: Some(Utc::now() - chrono::Duration::days(14)),
                end: Some(Utc::now()),
                ..Default::default()
            },
            ..Default::default()
        };
        assert!(validate_analytics_request(&req).is_ok());
    }
}
