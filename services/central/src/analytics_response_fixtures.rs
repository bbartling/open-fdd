//! Helpers for tests asserting on `/api/analytics/*` POST bodies.

use serde_json::Value;

/// Product analytics POSTs return `{ ok, analytics, cache }`; older tests used a flat envelope.
pub fn analytics_envelope(body: &Value) -> Value {
    body.get("analytics")
        .cloned()
        .unwrap_or_else(|| body.clone())
}

/// Row-only Timescale responses omit plot `points`; cached envelopes may include `points: []`.
pub fn points_absent_or_empty(body: &Value) -> bool {
    match analytics_envelope(body).get("points") {
        None => true,
        Some(v) => v.as_array().is_some_and(|rows| rows.is_empty()),
    }
}
