//! Graph and assignment validation for FDD Wires workspace.

use super::schema::{EDGE_TYPES, NODE_TYPES};
use crate::fdd::sql_safety;
use serde_json::{json, Value};

fn is_agent_proposed_source(source: &str) -> bool {
    matches!(source, "agent_proposed" | "ai_generated")
}

pub fn validate_graph(graph: &Value) -> Value {
    let mut errors: Vec<String> = Vec::new();
    let mut warnings: Vec<String> = Vec::new();

    if graph.get("schema_version").is_none() {
        errors.push("missing schema_version".into());
    }
    let nodes = graph.get("nodes").and_then(|v| v.as_array());
    let edges = graph.get("edges").and_then(|v| v.as_array());
    if nodes.is_none() {
        errors.push("nodes array required".into());
    }
    if edges.is_none() {
        errors.push("edges array required".into());
    }

    let node_ids: Vec<String> = nodes
        .cloned()
        .unwrap_or_default()
        .iter()
        .filter_map(|n| {
            let id = n.get("id")?.as_str()?.to_string();
            let ty = n.get("type")?.as_str()?;
            if !NODE_TYPES.contains(&ty) {
                errors.push(format!("unknown node type: {ty}"));
            }
            if n.get("source")
                .and_then(|s| s.as_str())
                .is_some_and(is_agent_proposed_source)
                && graph.get("review_status").and_then(|s| s.as_str()) == Some("active")
            {
                errors.push("Agent-proposed graph cannot be active without human approval".into());
            }
            if let Some(label) = n
                .get("config")
                .and_then(|c| c.get("source_label"))
                .and_then(|v| v.as_str())
            {
                if label == "simulated"
                    && graph.get("review_status").and_then(|s| s.as_str()) == Some("active")
                {
                    warnings.push(format!(
                        "node {id} uses simulated source in active graph — confirm explicitly"
                    ));
                }
            }
            Some(id)
        })
        .collect();

    for edge in edges.cloned().unwrap_or_default() {
        let ty = edge.get("type").and_then(|v| v.as_str()).unwrap_or("");
        if !EDGE_TYPES.contains(&ty) {
            errors.push(format!("unknown edge type: {ty}"));
        }
        let from = edge.get("from").and_then(|v| v.as_str()).unwrap_or("");
        let to = edge.get("to").and_then(|v| v.as_str()).unwrap_or("");
        if !node_ids.contains(&from.to_string()) {
            errors.push(format!("edge from missing node: {from}"));
        }
        if !node_ids.contains(&to.to_string()) {
            errors.push(format!("edge to missing node: {to}"));
        }
    }

    let node_list = nodes.cloned().unwrap_or_default();
    let sql_nodes: Vec<Value> = node_list
        .iter()
        .filter(|n| n.get("type").and_then(|t| t.as_str()) == Some("sql_rule"))
        .cloned()
        .collect();
    for node in &sql_nodes {
        let sql = node
            .get("config")
            .and_then(|c| c.get("sql"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if !sql.is_empty() && !sql_safety::is_sql_safe(sql) {
            errors.push(format!(
                "unsafe SQL on node {}",
                node.get("id").and_then(|v| v.as_str()).unwrap_or("?")
            ));
        }
    }

    let has_confirm = node_list
        .iter()
        .any(|n| n.get("type").and_then(|t| t.as_str()) == Some("confirmation_timer"));
    if !sql_nodes.is_empty() && !has_confirm {
        warnings.push("SQL rule nodes present without confirmation timer".into());
    }

    let fault_codes: Vec<String> = nodes
        .cloned()
        .unwrap_or_default()
        .iter()
        .filter(|n| n.get("type").and_then(|t| t.as_str()) == Some("fault_output"))
        .filter_map(|n| {
            n.get("config")
                .and_then(|c| c.get("fault_code"))
                .and_then(|v| v.as_str())
                .map(String::from)
        })
        .collect();
    let mut seen = std::collections::HashSet::new();
    for code in fault_codes {
        if !seen.insert(code.clone()) {
            warnings.push(format!("duplicate fault code on graph: {code}"));
        }
    }

    json!({
        "ok": errors.is_empty(),
        "errors": errors,
        "warnings": warnings,
        "node_count": node_ids.len(),
        "edge_count": edges.as_ref().map(|e| e.len()).unwrap_or(0)
    })
}

pub fn validate_rule_object(rule: &Value) -> Value {
    let mut errors: Vec<String> = Vec::new();
    let mut warnings: Vec<String> = Vec::new();
    let sql = rule.get("sql").and_then(|v| v.as_str()).unwrap_or("");
    if sql.is_empty() {
        errors.push("sql required".into());
    } else {
        let safety = sql_safety::validate_sql(sql);
        if safety.get("safe").and_then(|v| v.as_bool()) != Some(true) {
            errors.push("unsafe or invalid SQL".into());
        }
        if let Some(w) = safety.get("warnings").and_then(|v| v.as_array()) {
            for item in w {
                warnings.push(item.as_str().unwrap_or("").to_string());
            }
        }
    }
    if rule.get("confirmation_seconds").is_none() {
        warnings.push("confirmation_seconds not set".into());
    }
    if rule.get("output_fault_code").is_none() {
        errors.push("output_fault_code required".into());
    }
    json!({"ok": errors.is_empty(), "errors": errors, "warnings": warnings})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn agent_proposed_graph_cannot_activate_without_approval() {
        let site = "site:test";
        let mut graph = super::super::schema::empty_graph(site, "graph:test", "tester");
        graph["nodes"] = json!([{
            "id": "n-driver",
            "type": "driver_point",
            "label": "oa sensor",
            "source": "agent_proposed",
            "config": {"source_label": "live", "ref": "bacnet:1:analog-input:1"}
        }]);
        graph["edges"] = json!([]);
        graph["review_status"] = json!("active");
        graph["source"] = json!("agent_proposed");
        let out = validate_graph(&graph);
        assert_eq!(out["ok"].as_bool(), Some(false));
    }
}
