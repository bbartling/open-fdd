//! Deterministic historian rows for SQL engine / CI proof only — not OT driver data.
//!
//! Source tag `validation:fixture` distinguishes these from live BACnet/Modbus samples.
//! Do not reintroduce `simulation_phase`, `simulated_values`, or bench device IDs here.

use crate::historian::store;
use crate::validation::profile::SmokeProfile;
use chrono::{DateTime, Utc};
use serde_json::{json, Value};

fn phase_oa_t(phase: &str) -> f64 {
    match phase {
        "fault" | "fault_high" => 120.0,
        "fault_low" => 30.0,
        _ => 62.0,
    }
}

fn fixture_row(p: &SmokeProfile, ts: &str, phase: &str) -> Value {
    store::make_pivot_row(store::PivotSample {
        timestamp: ts,
        equipment_id: &p.equipment_id,
        oa_t: phase_oa_t(phase),
        oa_h: 45.0,
        duct_t: 55.0,
        zn_t: 72.0,
        source: &format!("validation:fixture:{phase}"),
        source_driver: "validation_fixture",
        is_simulated: false,
    })
}

pub fn inject_scenario_rows(
    p: &SmokeProfile,
    start: DateTime<Utc>,
    normal_min: u64,
    fault_min: u64,
    clear_min: u64,
) -> Vec<Value> {
    let mut rows = Vec::new();
    let mut minute = 0_u64;
    for _ in 0..normal_min {
        let ts = (start + chrono::Duration::minutes(minute as i64)).to_rfc3339();
        rows.push(fixture_row(p, &ts, "normal"));
        minute += 1;
    }
    for _ in 0..fault_min {
        let ts = (start + chrono::Duration::minutes(minute as i64)).to_rfc3339();
        rows.push(fixture_row(p, &ts, "fault"));
        minute += 1;
    }
    for _ in 0..clear_min {
        let ts = (start + chrono::Duration::minutes(minute as i64)).to_rfc3339();
        rows.push(fixture_row(p, &ts, "clear"));
        minute += 1;
    }
    rows
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::validation::profile;

    #[test]
    fn fixture_rows_are_not_ot_simulated() {
        let p = profile::active_profile();
        let rows = inject_scenario_rows(&p, Utc::now(), 2, 2, 1);
        assert_eq!(rows.len(), 5);
        for row in rows {
            assert_eq!(
                row.get("is_simulated").and_then(|v| v.as_bool()),
                Some(false)
            );
            let source = row.get("source").and_then(|v| v.as_str()).unwrap_or("");
            assert!(
                source.starts_with("validation:fixture:"),
                "unexpected source {source}"
            );
            assert!(
                !source.contains("simulation:"),
                "legacy simulation source must not return"
            );
        }
    }
}
