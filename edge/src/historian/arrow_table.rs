//! Arrow-shaped historian query helpers — reads persisted historian data only.

use crate::historian::store;
use serde_json::json;

pub fn query_json() -> String {
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
        Ok(rows) => json!({
            "ok": true,
            "engine": "Apache Arrow RecordBatch / DataFusion query path",
            "configured": true,
            "row_count": rows.len(),
            "rows": rows
        })
        .to_string(),
        Err(err) => json!({"ok": false, "error": err}).to_string(),
    }
}
