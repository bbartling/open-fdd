//! Deterministic simulation source for demos and tests.

use crate::connectors::historian;
use crate::connectors::registry::{update_source_health, update_source_poll_time};
use crate::connectors::types::{NormalizedRow, SourceHealth};
use chrono::{Local, Utc};
use serde_json::{json, Value};

pub fn poll_once(source_id: &str, run_id: &str) -> Value {
    let now = Utc::now();
    let rows = vec![NormalizedRow {
        timestamp_utc: now.to_rfc3339(),
        timestamp_local: now
            .with_timezone(&Local)
            .format("%Y-%m-%d %H:%M:%S")
            .to_string(),
        timezone: "UTC".into(),
        site_id: "site:demo".into(),
        building_id: "building:main".into(),
        equipment_id: "equip:sim".into(),
        source_id: source_id.into(),
        source_type: "simulation".into(),
        source_protocol: "simulation".into(),
        device_id: "sim:1".into(),
        point_id: "point:sim_temp".into(),
        point_name: "Simulated Temp".into(),
        value: Some(70.0),
        value_text: "70".into(),
        units: "degF".into(),
        quality: "simulated".into(),
        source_path: "simulation://demo".into(),
        raw_ref: "sim".into(),
        ingested_at: now.to_rfc3339(),
        run_id: run_id.into(),
    }];
    let (written, skipped) = historian::append_rows(&rows).unwrap_or((0, 0));
    let count = historian::row_count_for_source(source_id);
    let _ = update_source_health(
        source_id,
        SourceHealth {
            status: "online".into(),
            message: "simulation poll".into(),
            last_error: None,
        },
        Some(count),
    );
    let _ = update_source_poll_time(source_id);
    json!({
        "ok": true,
        "source_id": source_id,
        "rows_written": written,
        "rows_deduped": skipped,
        "points_extracted": rows.len(),
        "run_id": run_id
    })
}

pub fn health(source_id: &str) -> Value {
    json!({
        "ok": true,
        "source_id": source_id,
        "status": "online",
        "message": "deterministic simulation source"
    })
}
