//! JSON persistence for FDD Wires graphs and assignments.

use super::schema;
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

pub fn workspace_dir() -> PathBuf {
    env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
}

pub fn wires_root() -> PathBuf {
    workspace_dir().join("data/fdd_wires")
}

pub fn graphs_dir(site_id: &str) -> PathBuf {
    wires_root().join("graphs").join(site_id)
}

pub fn graph_path(site_id: &str, graph_id: &str) -> PathBuf {
    graphs_dir(site_id).join(format!("{graph_id}.json"))
}

pub fn assignments_path(site_id: &str) -> PathBuf {
    wires_root()
        .join("assignments")
        .join(format!("{site_id}.json"))
}

pub fn ensure_layout(site_id: &str) {
    let _ = fs::create_dir_all(graphs_dir(site_id));
    let _ = fs::create_dir_all(wires_root().join("assignments"));
    let _ = fs::create_dir_all(wires_root().join("rules"));
}

pub fn list_graphs(site_id: &str) -> Value {
    ensure_layout(site_id);
    let mut graphs = Vec::new();
    let dir = graphs_dir(site_id);
    if let Ok(entries) = fs::read_dir(&dir) {
        for entry in entries.flatten() {
            if let Ok(text) = fs::read_to_string(entry.path()) {
                if let Ok(g) = serde_json::from_str::<Value>(&text) {
                    graphs.push(json!({
                        "graph_id": g.get("graph_id"),
                        "site_id": g.get("site_id"),
                        "review_status": g.get("review_status"),
                        "updated_at": g.get("updated_at"),
                        "node_count": g.get("nodes").and_then(|n| n.as_array()).map(|a| a.len()).unwrap_or(0),
                    }));
                }
            }
        }
    }
    json!({"ok": true, "site_id": site_id, "graphs": graphs})
}

pub fn read_graph(site_id: &str, graph_id: &str) -> Option<Value> {
    read_json_file(&graph_path(site_id, graph_id))
}

pub fn write_graph(site_id: &str, graph: &Value) -> Result<PathBuf, String> {
    ensure_layout(site_id);
    let graph_id = graph
        .get("graph_id")
        .and_then(|v| v.as_str())
        .ok_or("graph_id required")?;
    let path = graph_path(site_id, graph_id);
    write_json_file(&path, graph)
}

pub fn read_assignments(site_id: &str) -> Value {
    ensure_layout(site_id);
    read_json_file(&assignments_path(site_id)).unwrap_or_else(|| {
        json!({
            "ok": true,
            "site_id": site_id,
            "assignments": [],
            "review_status": "draft"
        })
    })
}

pub fn write_assignments(site_id: &str, doc: &Value) -> Result<PathBuf, String> {
    ensure_layout(site_id);
    write_json_file(&assignments_path(site_id), doc)
}

pub fn default_site_id() -> String {
    env::var("OPENFDD_SITE_ID").unwrap_or_else(|_| "site:demo".to_string())
}

fn read_json_file(path: &Path) -> Option<Value> {
    fs::read_to_string(path)
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
}

fn write_json_file(path: &Path, value: &Value) -> Result<PathBuf, String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    fs::write(
        path,
        serde_json::to_string_pretty(value).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    Ok(path.to_path_buf())
}

pub fn seed_demo_graph(site_id: &str, actor: &str) -> Value {
    let graph_id = "graph:live-fdd-validation";
    if read_graph(site_id, graph_id).is_some() {
        return read_graph(site_id, graph_id).unwrap();
    }
    let mut graph = schema::empty_graph(site_id, graph_id, actor);
    graph["review_status"] = json!("needs_review");
    graph["source"] = json!("ai_generated");
    graph["nodes"] = json!([
        {"id":"n-driver-oa","type":"driver_point","label":"BACnet OA-T","position":{"x":40,"y":80},"config":{"ref":"bacnet:validation:analog-input:1001","source_label":"simulated"},"source":"ai_generated","provenance":{"confidence":0.92},"validation":{"status":"ok"}},
        {"id":"n-model-oa","type":"model_point","label":"point:oa-t","position":{"x":220,"y":80},"config":{"haystack_id":"point:oa-t"},"source":"ai_generated","validation":{"status":"ok"}},
        {"id":"n-fdd-input","type":"fdd_input","label":"oa_t","position":{"x":400,"y":80},"config":{"fdd_input":"oa_t","unit":"degF"},"source":"ai_generated","validation":{"status":"ok"}},
        {"id":"n-sql-rule","type":"sql_rule","label":"OA Temperature Out Of Range","position":{"x":580,"y":80},"config":{"rule_id":"oa_temp_out_of_range","sql_mode":"builder"},"source":"ai_generated","validation":{"status":"ok"}},
        {"id":"n-confirm","type":"confirmation_timer","label":"5 min confirmation","position":{"x":760,"y":80},"config":{"confirmation_seconds":300},"source":"human_created","validation":{"status":"ok"}},
        {"id":"n-fault","type":"fault_output","label":"OA_TEMP_OUT_OF_RANGE","position":{"x":940,"y":80},"config":{"fault_code":"OA_TEMP_OUT_OF_RANGE","severity":"medium"},"source":"human_created","validation":{"status":"ok"}}
    ]);
    graph["edges"] = json!([
        {"id":"e1","type":"maps_to","from":"n-driver-oa","to":"n-model-oa"},
        {"id":"e2","type":"feeds","from":"n-model-oa","to":"n-fdd-input"},
        {"id":"e3","type":"rule_input","from":"n-fdd-input","to":"n-sql-rule"},
        {"id":"e4","type":"confirms","from":"n-sql-rule","to":"n-confirm"},
        {"id":"e5","type":"rule_output","from":"n-confirm","to":"n-fault"}
    ]);
    let _ = write_graph(site_id, &graph);
    graph
}
