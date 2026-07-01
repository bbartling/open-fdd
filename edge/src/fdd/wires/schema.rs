//! Versioned FDD Wires graph schema constants.

pub const SCHEMA_VERSION: &str = "1.0.0";

pub const NODE_TYPES: &[&str] = &[
    "model_site",
    "model_equipment",
    "model_point",
    "driver_point",
    "fdd_input",
    "unit_conversion",
    "quality_check",
    "sql_rule",
    "confirmation_timer",
    "fault_output",
    "recommendation",
    "report_section",
    "comment",
    "group",
];

pub const EDGE_TYPES: &[&str] = &[
    "maps_to",
    "feeds",
    "converts_to",
    "validates",
    "assigned_to",
    "rule_input",
    "rule_output",
    "confirms",
    "reports_to",
];

pub const REVIEW_STATUSES: &[&str] = &[
    "draft",
    "needs_review",
    "approved",
    "rejected",
    "active",
    "proposed",
    "human_modified",
    "disabled",
];

pub fn empty_graph(site_id: &str, graph_id: &str, actor: &str) -> serde_json::Value {
    let now = chrono::Utc::now().to_rfc3339();
    serde_json::json!({
        "schema_version": SCHEMA_VERSION,
        "graph_id": graph_id,
        "site_id": site_id,
        "building_id": format!("building:{site_id}"),
        "created_at": now,
        "updated_at": now,
        "created_by": actor,
        "updated_by": actor,
        "source": "human_created",
        "review_status": "draft",
        "nodes": [],
        "edges": [],
        "validation_errors": [],
        "validation_warnings": [],
        "execution_status": "idle",
        "last_test_result": null,
        "provenance": {"product": "Open-FDD FDD Wires", "inspiration_note": "Internal dev notes only — flow/wiresheet UX patterns"}
    })
}
