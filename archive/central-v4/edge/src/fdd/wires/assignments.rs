//! Deterministic model-to-rule assignment proposal engine.

use serde_json::{json, Value};

use crate::model::scope;

const AHU_MAPPINGS: &[(&str, &str, f64)] = &[
    ("OA temperature", "oa_t", 0.95),
    ("Supply Air Temp", "sat", 0.93),
    ("Discharge Air Temp", "duct_t", 0.90),
    ("Zone Temp", "zn_t", 0.88),
    ("Outside Air Humidity", "oa_h", 0.86),
    ("SAT Setpoint", "sat_sp", 0.92),
    ("Fan Command", "fan_cmd", 0.94),
];

pub fn propose_assignments(payload: &Value) -> Value {
    let site_id = payload
        .get("site_id")
        .and_then(|v| v.as_str())
        .map(str::to_string)
        .or_else(scope::active_site_id);
    let equipment_type = payload
        .get("equipment_type")
        .and_then(|v| v.as_str())
        .unwrap_or("ahu");

    let driver_points = collect_driver_points(payload);
    let mut proposals = Vec::new();
    let mut missing = Vec::new();
    let mut ambiguous = Vec::new();

    for (label, fdd_input, confidence) in AHU_MAPPINGS {
        let matches: Vec<&Value> = driver_points
            .iter()
            .filter(|p| point_matches(p, label, fdd_input))
            .collect();
        if matches.is_empty() {
            missing.push(json!({"fdd_input": fdd_input, "label": label}));
            continue;
        }
        if matches.len() > 1 {
            ambiguous.push(json!({
                "fdd_input": fdd_input,
                "candidates": matches.len(),
                "note": "multiple driver points match; human review required"
            }));
        }
        let chosen = matches[0];
        let haystack_id = chosen
            .get("haystack_id")
            .or_else(|| chosen.get("id"))
            .cloned()
            .unwrap_or(json!(null));
        proposals.push(json!({
            "fdd_input": fdd_input,
            "label": label,
            "haystack_id": haystack_id,
            "driver_ref": chosen.get("ref").or_else(|| chosen.get("id")).cloned().unwrap_or(json!(null)),
            "confidence": confidence,
            "explanation": format!("Mapped {label} to FDD input {fdd_input} via name/tag similarity"),
            "source": "agent_proposed",
            "review_status": "proposed"
        }));
    }

    let rule_bindings = vec![json!({
        "rule_id": "oa_temp_out_of_range",
        "name": "OA Temperature Out Of Range",
        "required_inputs": ["oa_t"],
        "confidence": 0.91,
        "source": "agent_proposed",
        "review_status": "proposed"
    })];

    json!({
        "ok": true,
        "site_id": site_id,
        "equipment_type": equipment_type,
        "source": "agent_proposed",
        "review_status": "needs_review",
        "proposals": proposals,
        "rule_bindings": rule_bindings,
        "missing_points": missing,
        "ambiguous_points": ambiguous,
        "validation_warnings": if ambiguous.is_empty() { json!([]) } else { json!(["ambiguous driver point matches require human review"]) },
        "note": "AI suggestions are draft-only until integrator approval"
    })
}

fn collect_driver_points(payload: &Value) -> Vec<Value> {
    if let Some(points) = payload.get("driver_points").and_then(|v| v.as_array()) {
        return points.clone();
    }
    if let Some(drivers) = payload.get("drivers").and_then(|v| v.as_array()) {
        let mut out = Vec::new();
        for driver in drivers {
            if let Some(devices) = driver.get("devices").and_then(|v| v.as_array()) {
                for device in devices {
                    if let Some(points) = device.get("points").and_then(|v| v.as_array()) {
                        for point in points {
                            let mut p = point.clone();
                            if p.get("ref").is_none() {
                                p["ref"] = point.get("id").cloned().unwrap_or(json!(null));
                            }
                            out.push(p);
                        }
                    }
                }
            }
        }
        return out;
    }
    scope::driver_points_from_model()
}

fn point_matches(point: &Value, label: &str, fdd_input: &str) -> bool {
    let name = point.get("name").and_then(|v| v.as_str()).unwrap_or("");
    let haystack = point
        .get("haystack_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let input = point
        .get("fdd_input")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    name.to_ascii_lowercase()
        .contains(&label.to_ascii_lowercase())
        || haystack.contains(fdd_input)
        || input == fdd_input
        || (fdd_input == "oa_t" && (name.contains("OA") || name.contains("Outside Air")))
        || (fdd_input == "sat" && name.contains("SAT"))
        || (fdd_input == "fan_cmd" && name.to_ascii_lowercase().contains("fan"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn proposes_oa_t_assignment_from_payload_points() {
        let out = propose_assignments(&json!({
            "equipment_type":"ahu",
            "driver_points": [
                {"id":"point:1","name":"OA temperature","haystack_id":"point:1","fdd_input":"oa_t","ref":"csv:src:oa_t"}
            ]
        }));
        let proposals = out["proposals"].as_array().unwrap();
        assert!(proposals.iter().any(|p| p["fdd_input"] == "oa_t"));
        assert_eq!(out["review_status"], "needs_review");
    }
}
