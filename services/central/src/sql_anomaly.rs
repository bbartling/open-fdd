//! Wave UX Soft — SQL statistical anomaly screening (DataFusion rolling Z-score).
//!
//! Default-on for CSV/Overview; set `OPENFDD_SQL_ANOMALY_SCREENING=0` on live OT hubs.

use std::sync::Arc;

use axum::extract::State;
use axum::http::StatusCode;
use axum::middleware;
use axum::routing::get;
use axum::{Json, Router};
use serde_json::{json, Value};

use crate::analytics::{self, AnalyticsRequest};
use crate::auth;
use crate::state::AppState;

/// When unset, screening runs (CSV-safe default). Explicit `0`/`false` disables (OT hubs).
pub fn screening_enabled() -> bool {
    match std::env::var("OPENFDD_SQL_ANOMALY_SCREENING")
        .unwrap_or_default()
        .trim()
        .to_ascii_lowercase()
        .as_str()
    {
        "" | "1" | "true" | "yes" | "on" => true,
        "0" | "false" | "no" | "off" => false,
        _ => true,
    }
}

#[derive(Debug, Clone)]
pub struct SqlAnomalyParams {
    pub window_rows: u32,
    pub z_threshold: f64,
    pub method: String,
    pub transition_events: bool,
}

impl Default for SqlAnomalyParams {
    fn default() -> Self {
        Self {
            window_rows: 24,
            z_threshold: 3.0,
            method: "zscore".into(),
            transition_events: true,
        }
    }
}

pub fn params_from_request(req: &AnalyticsRequest) -> SqlAnomalyParams {
    let mut p = SqlAnomalyParams::default();
    let Some(series) = req.series.as_ref().and_then(|s| s.as_object()) else {
        return p;
    };
    if let Some(w) = series.get("window_rows").and_then(|v| v.as_u64()) {
        p.window_rows = w.min(168) as u32;
    }
    if let Some(t) = series.get("z_threshold").and_then(|v| v.as_f64()) {
        p.z_threshold = t;
    }
    if let Some(m) = series.get("method").and_then(|v| v.as_str()) {
        p.method = m.to_string();
    }
    if let Some(b) = series.get("transition_events").and_then(|v| v.as_bool()) {
        p.transition_events = b;
    }
    p
}

pub async fn handle_analytics(req: &AnalyticsRequest) -> analytics::AnalyticsEnvelope {
    if !screening_enabled() {
        return analytics::envelope(
            analytics::QV_SQL_ANOMALY,
            &req.query,
            vec!["sql anomaly screening disabled (OPENFDD_SQL_ANOMALY_SCREENING=0)".into()],
        );
    }
    let p = params_from_request(req);
    match analytics::historian::sql_anomaly_from_history(
        req.query.equipment_ids.as_deref(),
        req.query.building_id.as_deref(),
        p.window_rows,
        p.z_threshold,
        &p.method,
        p.transition_events,
    )
    .await
    {
        Ok(Some(env)) => analytics::finalize_historian(req, env, analytics::QV_SQL_ANOMALY),
        Ok(None) => analytics::envelope_with_engine(
            analytics::QV_SQL_ANOMALY,
            &req.query,
            vec!["sql-anomaly — no mapped SAT/OAT/zone sensor columns".into()],
            analytics::DF_ENGINE,
        ),
        Err(e) => analytics::envelope(
            analytics::QV_SQL_ANOMALY,
            &req.query,
            vec![format!("sql-anomaly failed: {e}")],
        ),
    }
}

pub fn router(state: Arc<AppState>) -> Router {
    Router::new()
        .route("/api/analytics/sql-anomaly/status", get(status))
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            auth::jwt_middleware,
        ))
        .with_state(state)
}

async fn status(
    State(_state): State<Arc<AppState>>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let enabled = screening_enabled();
    Ok(Json(json!({
        "ok": true,
        "enabled": enabled,
        "mode": if enabled { "default-on" } else { "disabled" },
        "note": "Rolling Z-score / robust MAD screening over historian Parquet; set OPENFDD_SQL_ANOMALY_SCREENING=0 on OT hubs",
        "endpoints": {
            "status": "/api/analytics/sql-anomaly/status",
            "run": "POST /api/analytics/sql-anomaly"
        }
    })))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analytics::AnalyticsQuery;
    use crate::test_env_lock::lock_env;

    #[test]
    fn flag_defaults_on_unless_explicit_off() {
        let _g = lock_env();
        std::env::remove_var("OPENFDD_SQL_ANOMALY_SCREENING");
        assert!(screening_enabled());
        std::env::set_var("OPENFDD_SQL_ANOMALY_SCREENING", "0");
        assert!(!screening_enabled());
        std::env::remove_var("OPENFDD_SQL_ANOMALY_SCREENING");
    }

    #[test]
    fn zscore_params_defaults_and_series_override() {
        let req = AnalyticsRequest {
            query: AnalyticsQuery {
                building_id: Some("B1".into()),
                ..Default::default()
            },
            series: Some(json!({
                "window_rows": 48,
                "z_threshold": 2.5,
                "method": "zscore",
                "transition_events": false
            })),
            ..Default::default()
        };
        let p = params_from_request(&req);
        assert_eq!(p.window_rows, 48);
        assert!((p.z_threshold - 2.5).abs() < 1e-9);
        assert_eq!(p.method, "zscore");
        assert!(!p.transition_events);
    }
}
