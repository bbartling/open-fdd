//! Deterministic model-to-rule assignment proposal engine.

use serde_json::{json, Value};

const AHU_MAPPINGS: &[(&str, &str, &str, f64)] = &[
    ("Outside Air Temp", "oa_t", "point:oa-t", 0.95),
    ("Supply Air Temp", "sat", "point:sat", 0.93),
    ("Discharge Air Temp", "duct_t", "point:duct-t", 0.90),
    ("Zone Temp", "zn_t", "point:zn-t", 0.88),
    ("Outside Air Humidity", "oa_h", "point:oa-h", 0.86),
    ("SAT Setpoint", "sat_sp", "point:sat-sp", 0.92),
    ("Fan Command", "fan_cmd", "point:fan-cmd", 0.94),
];

pub fn propose_assignments(payload: &Value) -> Value {
    let site_id = payload
        .get("site_id")
        .and_then(|v| v.as_str())
        .unwrap_or("site:demo");
    let equipment_type = payload
        .get("equipment_type")
        .and_then(|v| v.as_str())
        .unwrap_or("ahu");

    let driver_points = collect_driver_points(payload);
    let mut proposals = Vec::new();
    let mut missing = Vec::new();
    let mut ambiguous = Vec::new();

    for (label, fdd_input, haystack_id, confidence) in AHU_MAPPINGS {
        let matches: Vec<&Value> = driver_points
            .iter()
            .filter(|p| point_matches(p, label, fdd_input))
            .collect();
        if matches.is_empty() {
            missing.push(
                json!({"fdd_input": fdd_input, "label": label, "expected_haystack": haystack_id}),
            );
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
        proposals.push(json!({
            "fdd_input": fdd_input,
            "label": label,
            "haystack_id": haystack_id,
            "driver_ref": chosen.get("ref").or_else(|| chosen.get("id")).cloned().unwrap_or(json!(null)),
            "confidence": confidence,
            "explanation": format!("Mapped {label} to FDD input {fdd_input} via name/tag similarity"),
            "source": "ai_generated",
            "review_status": "ai_suggested"
        }));
    }

    let rule_bindings = vec![json!({
        "rule_id": "oa_temp_out_of_range",
        "name": "OA Temperature Out Of Range",
        "required_inputs": ["oa_t"],
        "confidence": 0.91,
        "source": "ai_generated",
        "review_status": "ai_suggested"
    })];

    json!({
        "ok": true,
        "site_id": site_id,
        "equipment_type": equipment_type,
        "source": "ai_generated",
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
    demo_driver_points()
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

fn demo_driver_points() -> Vec<Value> {
    vec![
        json!({"id":"bacnet:validation:analog-input:1001","name":"Outside Air Temp","haystack_id":"point:oa-t","fdd_input":"oa_t","source_label":"simulated"}),
        json!({"id":"bacnet:validation:analog-input:1174","name":"Supply Air Temp","haystack_id":"point:sat","fdd_input":"sat","source_label":"simulated"}),
        json!({"id":"bacnet:validation:analog-value:1175","name":"SAT Setpoint","haystack_id":"point:sat-sp","fdd_input":"sat_sp","source_label":"simulated"}),
        json!({"id":"bacnet:validation:binary-output:1176","name":"Fan Command","haystack_id":"point:fan-cmd","fdd_input":"fan_cmd","source_label":"simulated"}),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn proposes_oa_t_assignment() {
        let out = propose_assignments(&json!({"equipment_type":"ahu"}));
        let proposals = out["proposals"].as_array().unwrap();
        assert!(proposals.iter().any(|p| p["fdd_input"] == "oa_t"));
        assert_eq!(out["review_status"], "needs_review");
    }
}
