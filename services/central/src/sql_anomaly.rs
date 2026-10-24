//! Request parameters and screening flag for the anomaly event table.
//!
//! The product calculation is the Timescale route. Default-on for CSV/Overview;
//! set `OPENFDD_SQL_ANOMALY_SCREENING=0` to skip the scan.

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
            // Every flagged timestamp stays in the event table unless the
            // caller asks for rising edges.
            transition_events: false,
        }
    }
}

fn json_u32(value: &Value) -> Option<u32> {
    if let Some(n) = value.as_u64() {
        return u32::try_from(n).ok();
    }
    let number = value.as_f64()?;
    if !number.is_finite() || number < 0.0 || number > f64::from(u32::MAX) {
        return None;
    }
    let whole = number.trunc();
    if whole != number {
        return None;
    }
    u32::try_from(whole as u64).ok()
}

pub fn params_from_request(req: &AnalyticsRequest) -> SqlAnomalyParams {
    let mut p = SqlAnomalyParams::default();
    let Some(series) = req.series.as_ref().and_then(|s| s.as_object()) else {
        return p;
    };
    if let Some(w) = series.get("window_rows").and_then(json_u32) {
        p.window_rows = w.clamp(3, 168);
    }
    if let Some(t) = series.get("z_threshold").and_then(Value::as_f64) {
        if t.is_finite() && t > 0.0 {
            p.z_threshold = t.min(1.0e6);
        }
    }
    if let Some(m) = series.get("method").and_then(Value::as_str) {
        let method = m.trim();
        if !method.is_empty() {
            p.method = method.to_string();
        }
    }
    if let Some(b) = series.get("transition_events").and_then(Value::as_bool) {
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
    match analytics::historian::sql_anomaly_from_history(analytics::historian::SqlAnomalyRequest {
        equipment_filter: req.query.equipment_ids.as_deref(),
        building_id: req.query.building_id.as_deref(),
        window_rows: p.window_rows,
        z_threshold: p.z_threshold,
        method: &p.method,
        transition_events: p.transition_events,
        start: req.query.start,
        end: req.query.end,
    })
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
        "note": "Rolling prior-window z-score event table on the Timescale historian. Set OPENFDD_SQL_ANOMALY_SCREENING=0 to skip the scan.",
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

    #[test]
    fn event_defaults_keep_every_flag_and_clamp_the_window() {
        let defaults = params_from_request(&AnalyticsRequest::default());
        assert_eq!(defaults.window_rows, 24);
        assert!((defaults.z_threshold - 3.0).abs() < 1e-9);
        assert_eq!(defaults.method, "zscore");
        assert!(!defaults.transition_events);

        let req = AnalyticsRequest {
            series: Some(json!({
                "window_rows": 1,
                "z_threshold": 0.0,
                "method": " robust ",
                "transition_events": true
            })),
            ..Default::default()
        };
        let clamped = params_from_request(&req);
        assert_eq!(clamped.window_rows, 3);
        assert!((clamped.z_threshold - 3.0).abs() < 1e-9);
        assert_eq!(clamped.method, "robust");
        assert!(clamped.transition_events);

        let wide = AnalyticsRequest {
            series: Some(json!({ "window_rows": 500, "z_threshold": 30.0 })),
            ..Default::default()
        };
        let wide = params_from_request(&wide);
        assert_eq!(wide.window_rows, 168);
        assert!((wide.z_threshold - 30.0).abs() < 1e-9);
    }
}
