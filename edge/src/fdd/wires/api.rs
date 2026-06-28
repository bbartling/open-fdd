//! HTTP API handlers for FDD Wires and SQL rules.

use super::assignments;
use super::persistence;
use super::validation;
use crate::fdd::execution;
use crate::fdd::rules;
use chrono::Utc;
use serde_json::{json, Value};

pub fn list_graphs(site_id: Option<&str>) -> String {
    let site = site_id
        .map(String::from)
        .unwrap_or_else(persistence::default_site_id);
    serde_json::to_string(&persistence::list_graphs(&site)).unwrap_or_else(|_| "{}".to_string())
}

pub fn get_graph(site_id: &str, graph_id: &str) -> String {
    let graph = persistence::read_graph(site_id, graph_id).unwrap_or_else(|| {
        super::schema::empty_graph(site_id, graph_id, "system")
    });
    serde_json::to_string(&json!({"ok": true, "graph": graph})).unwrap()
}

pub fn create_graph(payload: &Value, actor: &str) -> Value {
    let site_id = payload
        .get("site_id")
        .and_then(|v| v.as_str())
        .unwrap_or(&persistence::default_site_id())
        .to_string();
    let graph_id = payload
        .get("graph_id")
        .and_then(|v| v.as_str())
        .unwrap_or(&format!("graph:{}", Utc::now().timestamp()))
        .to_string();
    let mut graph = if payload.get("nodes").is_some() {
        payload.clone()
    } else {
        super::schema::empty_graph(&site_id, &graph_id, actor)
    };
    graph["graph_id"] = json!(graph_id);
    graph["site_id"] = json!(site_id);
    graph["updated_at"] = json!(Utc::now().to_rfc3339());
    graph["updated_by"] = json!(actor);
    if graph.get("review_status").is_none() {
        graph["review_status"] = json!("draft");
    }
    match persistence::write_graph(&site_id, &graph) {
        Ok(path) => json!({"ok": true, "graph": graph, "path": path.display().to_string()}),
        Err(err) => json!({"ok": false, "error": err}),
    }
}

pub fn update_graph(site_id: &str, graph_id: &str, payload: &Value, actor: &str) -> Value {
    let mut graph = persistence::read_graph(site_id, graph_id)
        .unwrap_or_else(|| super::schema::empty_graph(site_id, graph_id, actor));
    if let Some(nodes) = payload.get("nodes") {
        graph["nodes"] = nodes.clone();
    }
    if let Some(edges) = payload.get("edges") {
        graph["edges"] = edges.clone();
    }
    if let Some(review) = payload.get("review_status") {
        graph["review_status"] = review.clone();
    }
    graph["updated_at"] = json!(Utc::now().to_rfc3339());
    graph["updated_by"] = json!(actor);
    if payload.get("source").and_then(|v| v.as_str()) == Some("ai_generated") {
        graph["review_status"] = json!("needs_review");
    }
    match persistence::write_graph(site_id, &graph) {
        Ok(path) => json!({"ok": true, "graph": graph, "path": path.display().to_string()}),
        Err(err) => json!({"ok": false, "error": err}),
    }
}

pub fn validate_graph(site_id: &str, graph_id: &str) -> Value {
    let graph = persistence::read_graph(site_id, graph_id);
    match graph {
        Some(g) => {
            let result = validation::validate_graph(&g);
            json!({"ok": result["ok"], "validation": result, "graph_id": graph_id})
        }
        None => json!({"ok": false, "error": "graph not found"}),
    }
}

pub fn test_graph(site_id: &str, graph_id: &str) -> Value {
    let graph = match persistence::read_graph(site_id, graph_id) {
        Some(g) => g,
        None => return json!({"ok": false, "error": "graph not found"}),
    };
    let validation = validation::validate_graph(&graph);
    let sql_node = graph
        .get("nodes")
        .and_then(|n| n.as_array())
        .and_then(|nodes| {
            nodes
                .iter()
                .find(|n| n.get("type").and_then(|t| t.as_str()) == Some("sql_rule"))
        });
    let confirm_secs = graph
        .get("nodes")
        .and_then(|n| n.as_array())
        .and_then(|nodes| {
            nodes
                .iter()
                .find(|n| n.get("type").and_then(|t| t.as_str()) == Some("confirmation_timer"))
        })
        .and_then(|n| n.get("config"))
        .and_then(|c| c.get("confirmation_seconds"))
        .and_then(|v| v.as_i64())
        .unwrap_or(300);
    let sql = match sql_node
        .and_then(|n| n.get("config"))
        .and_then(|c| c.get("sql"))
        .and_then(|v| v.as_str())
        .filter(|s| !s.trim().is_empty())
    {
        Some(s) => s.to_string(),
        None => {
            if let Some(builder) = sql_node
                .and_then(|n| n.get("config"))
                .and_then(|c| c.get("builder"))
            {
                execution::builder_to_sql(builder)
            } else {
                return json!({
                    "ok": false,
                    "error": "graph has no SQL rule configured",
                    "validation": validation,
                    "graph_id": graph_id,
                    "site_id": site_id
                });
            }
        }
    };
    let exec = execution::run_rule_sql(&sql, confirm_secs, &json!({}));
    json!({
        "ok": validation["ok"].as_bool().unwrap_or(false) && exec.get("ok").and_then(|v| v.as_bool()).unwrap_or(false),
        "validation": validation,
        "execution": exec,
        "graph_id": graph_id,
        "site_id": site_id
    })
}

pub fn approve_graph(site_id: &str, graph_id: &str, actor: &str, role: &str) -> Value {
    if !crate::auth::rbac::is_integrator_tier(role) {
        return json!({"ok": false, "error": "integrator or agent role required to approve graphs", "role": role});
    }
    let mut graph = match persistence::read_graph(site_id, graph_id) {
        Some(g) => g,
        None => return json!({"ok": false, "error": "graph not found"}),
    };
    let validation = validation::validate_graph(&graph);
    if validation.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        return json!({"ok": false, "error": "graph validation failed", "validation": validation});
    }
    graph["review_status"] = json!("approved");
    graph["updated_at"] = json!(Utc::now().to_rfc3339());
    graph["updated_by"] = json!(actor);
    let _ = persistence::write_graph(site_id, &graph);
    json!({"ok": true, "approved": true, "graph_id": graph_id, "approved_by": actor})
}

pub fn activate_graph(site_id: &str, graph_id: &str, actor: &str, role: &str) -> Value {
    if !crate::auth::rbac::is_integrator_tier(role) {
        return json!({"ok": false, "error": "integrator or agent role required to activate graphs", "role": role});
    }
    let mut graph = match persistence::read_graph(site_id, graph_id) {
        Some(g) => g,
        None => return json!({"ok": false, "error": "graph not found"}),
    };
    let status = graph
        .get("review_status")
        .and_then(|v| v.as_str())
        .unwrap_or("draft");
    if status != "approved" {
        return json!({"ok": false, "error": "graph must be approved before activation", "review_status": status});
    }
    let validation = validation::validate_graph(&graph);
    if validation.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        return json!({"ok": false, "error": "graph validation failed", "validation": validation});
    }
    graph["review_status"] = json!("active");
    graph["execution_status"] = json!("scheduled");
    graph["updated_at"] = json!(Utc::now().to_rfc3339());
    graph["updated_by"] = json!(actor);
    let _ = persistence::write_graph(site_id, &graph);
    json!({"ok": true, "activated": true, "graph_id": graph_id, "activated_by": actor})
}

pub fn propose_assignments(payload: &Value, role: &str) -> Value {
    if !["integrator", "agent"].contains(&role) {
        return json!({"ok": false, "error": "integrator or agent role required"});
    }
    assignments::propose_assignments(payload)
}

pub fn schema_tables_json() -> String {
    serde_json::to_string(&execution::schema_tables_json()).unwrap_or_else(|_| "{}".to_string())
}

pub fn schema_fdd_inputs_json() -> String {
    serde_json::to_string(&execution::fdd_inputs_json()).unwrap_or_else(|_| "{}".to_string())
}

pub fn schema_equipment_types_json() -> String {
    serde_json::to_string(&execution::equipment_types_json()).unwrap_or_else(|_| "{}".to_string())
}

pub fn list_rules_json() -> String {
    serde_json::to_string(&rules::list_rules()).unwrap_or_else(|_| "{}".to_string())
}

pub fn get_rule_json(rule_id: &str) -> String {
    serde_json::to_string(&rules::get_rule(rule_id)).unwrap_or_else(|_| "{}".to_string())
}

pub fn save_rule(payload: &Value, actor: &str) -> Value {
    rules::save_rule(payload, actor)
}

pub fn validate_rule_sql(payload: &Value) -> Value {
    rules::validate_rule_sql(payload)
}

pub fn test_rule_sql(payload: &Value) -> Value {
    rules::test_rule_sql(payload)
}

pub fn activate_rule(rule_id: &str, actor: &str, role: &str) -> Value {
    rules::activate_rule(rule_id, actor, role)
}

pub fn builder_sql(payload: &Value) -> Value {
    let sql = execution::builder_to_sql(payload);
    json!({
        "ok": true,
        "sql": sql,
        "sql_mode": "builder",
        "validation": crate::fdd::sql_safety::validate_sql(&sql)
    })
}
