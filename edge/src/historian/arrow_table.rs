//! Arrow-shaped historian query helpers — reads persisted historian data only.

use crate::historian::store;
use serde_json::{json, Value};

pub fn query_json() -> String {
    query_json_from_body(&json!({}))
}

pub fn query_json_from_body(body: &Value) -> String {
    let limit = body
        .get("limit")
        .and_then(|v| v.as_u64())
        .unwrap_or(500)
        .clamp(1, 10_000) as usize;
    let site_id = body.get("site_id").and_then(|v| v.as_str());
    let equipment_id = body.get("equipment_id").and_then(|v| v.as_str());
    match store::load_pivot_rows() {
        Ok(rows) if rows.is_empty() => json!({
            "ok": true,
            "engine": "Apache Arrow RecordBatch / DataFusion query path",
            "configured": false,
            "row_count": 0,
            "rows": [],
            "message": "historian has no rows — import CSV or capture telemetry first"
        })
        .to_string(),
        Ok(mut rows) => {
            if let Some(site) = site_id {
                rows.retain(|r| {
                    r.get("site_id")
                        .or_else(|| r.get("site"))
                        .and_then(|v| v.as_str())
                        == Some(site)
                });
            }
            if let Some(equip) = equipment_id {
                rows.retain(|r| {
                    r.get("equipment_id")
                        .or_else(|| r.get("device_id"))
                        .and_then(|v| v.as_str())
                        == Some(equip)
                });
            }
            let total = rows.len();
            rows.truncate(limit);
            json!({
                "ok": true,
                "engine": "Apache Arrow RecordBatch / DataFusion query path",
                "configured": true,
                "row_count": total,
                "returned": rows.len(),
                "truncated": total > rows.len(),
                "rows": rows
            })
            .to_string()
        }
        Err(err) => json!({"ok": false, "error": err}).to_string(),
    }
}
