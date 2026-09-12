//! Wave M M2 — SQL anomaly screening (lab-safe flag).
//!
//! Disabled by default. Enable only with OPENFDD_SQL_ANOMALY_SCREENING=1 on
//! isolated/lab candidates. Never enable unbounded against live OT hubs.

use std::sync::Arc;

use axum::extract::State;
use axum::http::StatusCode;
use axum::middleware;
use axum::routing::get;
use axum::{Json, Router};
use serde_json::{json, Value};

use crate::auth;
use crate::state::AppState;

fn screening_enabled() -> bool {
    matches!(
        std::env::var("OPENFDD_SQL_ANOMALY_SCREENING")
            .unwrap_or_default()
            .trim()
            .to_ascii_lowercase()
            .as_str(),
        "1" | "true" | "yes" | "on"
    )
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
    if !enabled {
        return Err((
            StatusCode::NOT_FOUND,
            Json(json!({
                "ok": false,
                "enabled": false,
                "error": "sql anomaly screening disabled (set OPENFDD_SQL_ANOMALY_SCREENING=1 on lab only)"
            })),
        ));
    }
    Ok(Json(json!({
        "ok": true,
        "enabled": true,
        "mode": "lab",
        "note": "Wave M M2 lab-safe surface; full self/peer anomaly execution remains gated — no OT DoS",
        "endpoints": {
            "status": "/api/analytics/sql-anomaly/status"
        }
    })))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_env_lock::lock_env;

    #[test]
    fn flag_defaults_off() {
        let _g = lock_env();
        std::env::remove_var("OPENFDD_SQL_ANOMALY_SCREENING");
        assert!(!screening_enabled());
        std::env::set_var("OPENFDD_SQL_ANOMALY_SCREENING", "1");
        assert!(screening_enabled());
        std::env::remove_var("OPENFDD_SQL_ANOMALY_SCREENING");
    }
}
