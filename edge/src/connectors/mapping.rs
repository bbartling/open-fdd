//! Point mapping workflow for connector catalogs.

use crate::connectors::registry::{read_registry, write_registry};
use serde_json::{json, Value};

pub fn list_mappings(source_id: Option<&str>) -> Value {
    let reg = read_registry();
    let mappings: Vec<Value> = reg
        .get("mappings")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .filter(|m| {
            source_id
                .map(|sid| m.get("source_id").and_then(|v| v.as_str()) == Some(sid))
                .unwrap_or(true)
        })
        .collect();
    json!({"ok": true, "mappings": mappings})
}

pub fn upsert_mapping(body: &Value) -> Value {
    let source_id = match body.get("source_id").and_then(|v| v.as_str()) {
        Some(v) => v.to_string(),
        None => return json!({"ok": false, "error": "source_id required"}),
    };
    let point_id = match body.get("source_point_id").and_then(|v| v.as_str()) {
        Some(v) => v.to_string(),
        None => return json!({"ok": false, "error": "source_point_id required"}),
    };
    let review_status = body
        .get("review_status")
        .and_then(|v| v.as_str())
        .unwrap_or("pending");
    if review_status == "applied" && body.get("approved").and_then(|v| v.as_bool()) != Some(true) {
        return json!({"ok": false, "error": "human approval required before applied status"});
    }
    let mut reg = read_registry();
    if reg.get("mappings").is_none() {
        reg["mappings"] = json!([]);
    }
    if reg.get("backfill_jobs").is_none() {
        reg["backfill_jobs"] = json!([]);
    }
    let mappings = match reg.get_mut("mappings").and_then(|v| v.as_array_mut()) {
        Some(arr) => arr,
        None => return json!({"ok": false, "error": "invalid registry"}),
    };
    let entry = json!({
        "source_id": source_id,
        "source_point_id": point_id,
        "model_point_id": body.get("model_point_id").cloned().unwrap_or(json!("")),
        "site_id": body.get("site_id").cloned().unwrap_or(json!("site:demo")),
        "building_id": body.get("building_id").cloned().unwrap_or(json!("building:main")),
        "equipment_id": body.get("equipment_id").cloned().unwrap_or(json!("")),
        "review_status": review_status,
        "ai_suggested": body.get("ai_suggested").cloned().unwrap_or(json!(false)),
        "updated_at": chrono::Utc::now().to_rfc3339()
    });
    if let Some(existing) = mappings.iter_mut().find(|m| {
        m.get("source_id").and_then(|v| v.as_str()) == Some(&source_id)
            && m.get("source_point_id").and_then(|v| v.as_str()) == Some(&point_id)
    }) {
        *existing = entry.clone();
    } else {
        mappings.push(entry.clone());
    }
    if write_registry(&reg).is_err() {
        return json!({"ok": false, "error": "failed to persist mapping"});
    }
    json!({"ok": true, "mapping": entry})
}

pub fn export_mappings_csv(source_id: &str) -> String {
    let mappings = list_mappings(Some(source_id));
    let mut out = String::from(
        "source_id,source_point_id,model_point_id,site_id,building_id,equipment_id,review_status\n",
    );
    if let Some(arr) = mappings.get("mappings").and_then(|v| v.as_array()) {
        for m in arr {
            out.push_str(&format!(
                "{},{},{},{},{},{},{}\n",
                csv(m.get("source_id")),
                csv(m.get("source_point_id")),
                csv(m.get("model_point_id")),
                csv(m.get("site_id")),
                csv(m.get("building_id")),
                csv(m.get("equipment_id")),
                csv(m.get("review_status")),
            ));
        }
    }
    out
}

fn csv(v: Option<&Value>) -> String {
    v.and_then(|x| x.as_str()).unwrap_or("").replace(',', ";")
}
