//! Generic live FDD validation profiles and smoke-run configuration.

pub mod audit;
pub mod dev_profile;
pub mod profile;

use serde_json::{json, Value};

/// Exposed for dashboard/ops — surfaces audit helpers without dead-code warnings in release builds.
pub fn audit_status_json() -> Value {
    json!({
        "ok": true,
        "confirmation_delay_proof": audit::confirmation_met(5.0, 5),
        "phase_fault": audit::expected_phase_fault_state("fault"),
        "phase_normal": audit::expected_phase_fault_state("normal"),
    })
}
