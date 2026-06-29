//! Build FDD wiresheet graph nodes/edges from Haystack assignments + SQL rules.

use super::persistence;
use super::schema;
use crate::fdd::rules;
use crate::model::assignments;
use chrono::Utc;
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};

pub const DEFAULT_GRAPH_ID: &str = "graph:live-fdd-validation";

/// Rebuild wiresheet graph from persisted Haystack assignments.
pub fn sync_from_assignments(site_id: &str, graph_id: &str, actor: &str) -> Value {
    let doc = assignments::load_assignments_value();
    sync_from_doc(
        &doc,
        site_id,
        graph_id,
        actor,
        "human_modified",
        "needs_review",
    )
}

/// Merge AI proposal output into the wiresheet graph.
pub fn sync_from_proposal(proposal: &Value, site_id: &str, graph_id: &str, actor: &str) -> Value {
    let mut doc = assignments::load_assignments_value();
    if let Some(proposals) = proposal.get("proposals").and_then(|v| v.as_array()) {
        if doc.get("points").is_none() {
            doc["points"] = json!([]);
        }
        if let Some(points) = doc.get_mut("points").and_then(|v| v.as_array_mut()) {
            for p in proposals {
                let haystack = p.get("haystack_id").cloned().unwrap_or(json!(null));
                let driver = p.get("driver_ref").cloned().unwrap_or(json!(null));
                let fdd_input = p.get("fdd_input").and_then(|v| v.as_str()).unwrap_or("");
                points.push(json!({
                    "point_id": haystack,
                    "haystack_ref": haystack,
                    "driver_ref": driver,
                    "fdd_input": fdd_input,
                    "source": "ai_generated",
                    "review_status": "ai_suggested"
                }));
            }
        }
    }
    if let Some(bindings) = proposal.get("rule_bindings").and_then(|v| v.as_array()) {
        if doc.get("fault_equation_bindings").is_none() {
            doc["fault_equation_bindings"] = json!([]);
        }
        if let Some(target) = doc
            .get_mut("fault_equation_bindings")
            .and_then(|v| v.as_array_mut())
        {
            for b in bindings {
                target.push(b.clone());
            }
        }
    }
    sync_from_doc(
        &doc,
        site_id,
        graph_id,
        actor,
        "ai_generated",
        "needs_review",
    )
}

fn sync_from_doc(
    doc: &Value,
    site_id: &str,
    graph_id: &str,
    actor: &str,
    source: &str,
    review_status: &str,
) -> Value {
    let existing = persistence::read_graph(site_id, graph_id);
    let positions = existing_positions(existing.as_ref());
    let (nodes, edges) = build_nodes_edges(doc, site_id, &positions);
    let now = Utc::now().to_rfc3339();
    let mut graph = existing.unwrap_or_else(|| schema::empty_graph(site_id, graph_id, actor));
    graph["graph_id"] = json!(graph_id);
    graph["site_id"] = json!(site_id);
    graph["nodes"] = json!(nodes);
    graph["edges"] = json!(edges);
    graph["updated_at"] = json!(now);
    graph["updated_by"] = json!(actor);
    graph["source"] = json!(source);
    graph["review_status"] = json!(review_status);
    graph["validation_warnings"] = if nodes.is_empty() {
        json!(["No assignment bindings — add points or run AI propose"])
    } else {
        json!([])
    };
    match persistence::write_graph(site_id, &graph) {
        Ok(path) => json!({
            "ok": true,
            "synced": true,
            "graph_id": graph_id,
            "site_id": site_id,
            "node_count": nodes.len(),
            "edge_count": edges.len(),
            "path": path.display().to_string(),
            "review_status": review_status
        }),
        Err(err) => json!({"ok": false, "error": err}),
    }
}

fn existing_positions(graph: Option<&Value>) -> HashMap<String, (i64, i64)> {
    let mut out = HashMap::new();
    if let Some(g) = graph {
        if let Some(nodes) = g.get("nodes").and_then(|v| v.as_array()) {
            for n in nodes {
                let id = n.get("id").and_then(|v| v.as_str()).unwrap_or("");
                if id.is_empty() {
                    continue;
                }
                let x = n
                    .get("position")
                    .and_then(|p| p.get("x"))
                    .and_then(|v| v.as_i64())
                    .unwrap_or(0);
                let y = n
                    .get("position")
                    .and_then(|p| p.get("y"))
                    .and_then(|v| v.as_i64())
                    .unwrap_or(0);
                out.insert(id.to_string(), (x, y));
            }
        }
    }
    out
}

fn build_nodes_edges(
    doc: &Value,
    site_id: &str,
    positions: &HashMap<String, (i64, i64)>,
) -> (Vec<Value>, Vec<Value>) {
    let mut nodes = Vec::new();
    let mut edges = Vec::new();
    let mut row = 0i64;
    let rules_by_id = rules_index();

    if nodes.is_empty() {
        let site_node_id = format!("site:{site_id}");
        nodes.push(node(
            &site_node_id,
            "model_site",
            &format!("Site {site_id}"),
            pos(positions, &site_node_id, 0, 0),
            json!({"site_id": site_id}),
            "human_created",
        ));
    }

    let points = doc
        .get("points")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let mut rule_inputs: HashMap<String, String> = HashMap::new();

    for pt in &points {
        let haystack = pt
            .get("haystack_ref")
            .or_else(|| pt.get("point_id"))
            .or_else(|| pt.get("haystack_id"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if haystack.is_empty() {
            continue;
        }
        let label = pt
            .get("name")
            .and_then(|v| v.as_str())
            .or_else(|| pt.get("label").and_then(|v| v.as_str()))
            .unwrap_or(haystack);
        let driver_ref = pt.get("driver_ref").and_then(|v| v.as_str()).unwrap_or("");
        let fdd_input = pt.get("fdd_input").and_then(|v| v.as_str()).unwrap_or("");
        let y = row * 120;
        row += 1;

        let driver_id = if !driver_ref.is_empty() {
            format!("driver:{driver_ref}")
        } else {
            format!("driver:{haystack}")
        };
        nodes.push(node(
            &driver_id,
            "driver_point",
            label,
            pos(positions, &driver_id, 0, y),
            json!({"ref": driver_ref, "haystack_id": haystack}),
            pt_source(pt),
        ));

        let haystack_node_id = format!("point:{haystack}");
        nodes.push(node(
            &haystack_node_id,
            "model_point",
            label,
            pos(positions, &haystack_node_id, 220, y),
            json!({"haystack_id": haystack}),
            pt_source(pt),
        ));
        edges.push(edge(
            &format!("e-{driver_id}-maps-{haystack_node_id}"),
            "maps_to",
            &driver_id,
            &haystack_node_id,
        ));

        if !fdd_input.is_empty() {
            let input_id = format!("fdd_input:{fdd_input}");
            if !nodes.iter().any(|n| n["id"] == input_id) {
                nodes.push(node(
                    &input_id,
                    "fdd_input",
                    fdd_input,
                    pos(positions, &input_id, 440, y),
                    json!({"input_id": fdd_input}),
                    pt_source(pt),
                ));
            }
            rule_inputs.insert(fdd_input.to_string(), input_id.clone());
            edges.push(edge(
                &format!("e-{haystack_node_id}-feeds-{input_id}"),
                "feeds",
                &haystack_node_id,
                &input_id,
            ));
        }

        let rule_ids = point_rule_ids(pt);
        for rule_id in rule_ids {
            add_rule_chain(
                &mut nodes,
                &mut edges,
                &rule_id,
                fdd_input,
                &rule_inputs,
                y,
                positions,
                &rules_by_id,
            );
        }
    }

    if let Some(bindings) = doc
        .get("fault_equation_bindings")
        .and_then(|v| v.as_array())
    {
        for b in bindings {
            let rule_id = b.get("rule_id").and_then(|v| v.as_str()).unwrap_or("");
            if rule_id.is_empty() {
                continue;
            }
            let fdd_input = b
                .get("required_inputs")
                .and_then(|v| v.as_array())
                .and_then(|a| a.first())
                .and_then(|v| v.as_str())
                .unwrap_or("");
            add_rule_chain(
                &mut nodes,
                &mut edges,
                rule_id,
                fdd_input,
                &rule_inputs,
                row * 120,
                positions,
                &rules_by_id,
            );
            row += 1;
        }
    }

    (nodes, edges)
}

#[allow(clippy::too_many_arguments)]
fn add_rule_chain(
    nodes: &mut Vec<Value>,
    edges: &mut Vec<Value>,
    rule_id: &str,
    fdd_input: &str,
    rule_inputs: &HashMap<String, String>,
    y: i64,
    positions: &HashMap<String, (i64, i64)>,
    rules_by_id: &HashMap<String, Value>,
) {
    let rule_node_id = format!("rule:{rule_id}");
    if !nodes.iter().any(|n| n["id"] == rule_node_id) {
        let meta = rules_by_id.get(rule_id);
        let name = meta
            .and_then(|r| r.get("name").and_then(|v| v.as_str()))
            .unwrap_or(rule_id);
        let sql = meta
            .and_then(|r| r.get("sql").and_then(|v| v.as_str()))
            .unwrap_or("");
        nodes.push(node(
            &rule_node_id,
            "sql_rule",
            name,
            pos(positions, &rule_node_id, 660, y),
            json!({"rule_id": rule_id, "sql": sql}),
            "human_created",
        ));
        let fault_id = format!("fault:{rule_id}");
        nodes.push(node(
            &fault_id,
            "fault_output",
            &format!("Fault: {name}"),
            pos(positions, &fault_id, 880, y),
            json!({"rule_id": rule_id}),
            "human_created",
        ));
        edges.push(edge(
            &format!("e-{rule_node_id}-out-{fault_id}"),
            "rule_output",
            &rule_node_id,
            &fault_id,
        ));
    }
    if !fdd_input.is_empty() {
        if let Some(input_id) = rule_inputs.get(fdd_input) {
            edges.push(edge(
                &format!("e-{input_id}-rule-{rule_node_id}"),
                "rule_input",
                input_id,
                &rule_node_id,
            ));
        }
    }
}

fn point_rule_ids(pt: &Value) -> Vec<String> {
    let mut ids = HashSet::new();
    if let Some(arr) = pt.get("fdd_rule_ids").and_then(|v| v.as_array()) {
        for v in arr {
            if let Some(s) = v.as_str() {
                ids.insert(s.to_string());
            }
        }
    }
    if let Some(s) = pt.get("rule_id").and_then(|v| v.as_str()) {
        ids.insert(s.to_string());
    }
    ids.into_iter().collect()
}

fn rules_index() -> HashMap<String, Value> {
    let mut out = HashMap::new();
    if let Some(rules) = rules::list_rules().get("rules").and_then(|v| v.as_array()) {
        for r in rules {
            if let Some(id) = r.get("rule_id").and_then(|v| v.as_str()) {
                out.insert(id.to_string(), r.clone());
            }
        }
    }
    out
}

fn pt_source(pt: &Value) -> &str {
    pt.get("source")
        .and_then(|v| v.as_str())
        .unwrap_or("human_created")
}

fn pos(positions: &HashMap<String, (i64, i64)>, id: &str, default_x: i64, default_y: i64) -> Value {
    let (x, y) = positions.get(id).copied().unwrap_or((default_x, default_y));
    json!({"x": x, "y": y})
}

fn node(
    id: &str,
    node_type: &str,
    label: &str,
    position: Value,
    config: Value,
    source: &str,
) -> Value {
    json!({
        "id": id,
        "type": node_type,
        "label": label,
        "position": position,
        "config": config,
        "source": source,
        "review_status": if source == "ai_generated" { "ai_suggested" } else { "draft" }
    })
}

fn edge(id: &str, edge_type: &str, from: &str, to: &str) -> Value {
    json!({
        "id": id,
        "type": edge_type,
        "from": from,
        "to": to
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::with_temp_workspace;
    use serde_json::json;

    #[test]
    fn builds_graph_from_assignments_doc() {
        with_temp_workspace(|_| {
            let doc = json!({
                "points": [{
                    "haystack_ref": "point:oa",
                    "driver_ref": "csv:oa_t",
                    "fdd_input": "oa_t",
                    "fdd_rule_ids": ["oa_temp_out_of_range"],
                    "source": "ai_generated"
                }],
                "fault_equation_bindings": []
            });
            let (nodes, edges) = build_nodes_edges(&doc, "site:test", &HashMap::new());
            assert!(nodes.iter().any(|n| n["type"] == "driver_point"));
            assert!(nodes.iter().any(|n| n["type"] == "sql_rule"));
            assert!(!edges.is_empty());
        });
    }
}
