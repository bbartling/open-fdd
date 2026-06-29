//! Commissioning import validation tests.

use open_fdd_edge_prototype::ingest::validate_commissioning;
use serde_json::json;

#[test]
fn rejects_unknown_fdd_input() {
    let out = validate_commissioning(&json!({
        "points": [{
            "id": "point:bad",
            "fdd_input": "not_a_real_fdd_input_xyz"
        }]
    }));
    assert_eq!(out["verdict"], "fail");
    assert!(out["checks"]
        .as_array()
        .is_some_and(|a| a.iter().any(|c| c["code"] == "FDD_INPUT_UNKNOWN")));
}

#[test]
fn rejects_unsafe_rule_sql() {
    let out = validate_commissioning(&json!({
        "sites": [{"id": "site:t", "dis": "T", "site": "M"}],
        "fdd_rules": [{
            "rule_id": "bad",
            "sql": "DROP TABLE telemetry_pivot"
        }]
    }));
    assert_eq!(out["verdict"], "fail");
}
