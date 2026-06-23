//! JSON path extraction for array, flat, and nested payloads.

use serde_json::Value;

pub fn extract_path<'a>(value: &'a Value, path: &str) -> Option<&'a Value> {
    if path.trim().is_empty() {
        return Some(value);
    }
    let mut current = value;
    for segment in path.split('.') {
        if let Some(idx) = parse_index(segment) {
            current = current.get(idx)?;
        } else {
            current = current.get(segment)?;
        }
    }
    Some(current)
}

pub fn extract_string(value: &Value, path: &str) -> Option<String> {
    extract_path(value, path).map(value_to_string)
}

pub fn extract_f64(value: &Value, path: &str) -> Option<f64> {
    extract_path(value, path).and_then(|v| v.as_f64().or_else(|| v.as_str()?.parse().ok()))
}

pub fn extract_points_from_payload(
    payload: &Value,
    shape: &str,
    endpoint_path: &str,
    mappings: &[(String, String, String, Option<String>, Option<String>)],
) -> Vec<(String, String, String, Option<f64>, String, String)> {
    let root = extract_path(payload, endpoint_path).unwrap_or(payload);
    match shape {
        "array" => extract_from_array(root, mappings),
        "nested" => extract_from_nested(root, mappings),
        _ => extract_from_flat(root, mappings),
    }
}

fn extract_from_flat(
    root: &Value,
    mappings: &[(String, String, String, Option<String>, Option<String>)],
) -> Vec<(String, String, String, Option<f64>, String, String)> {
    mappings
        .iter()
        .filter_map(|(pid, pname, vpath, upath, default_units)| {
            let val = extract_f64(root, vpath)?;
            let units = upath
                .as_ref()
                .and_then(|p| extract_string(root, p))
                .or_else(|| default_units.clone())
                .unwrap_or_default();
            let quality = extract_string(root, "quality").unwrap_or_else(|| "good".into());
            Some((
                pid.clone(),
                pname.clone(),
                vpath.clone(),
                Some(val),
                units,
                quality,
            ))
        })
        .collect()
}

fn extract_from_array(
    root: &Value,
    mappings: &[(String, String, String, Option<String>, Option<String>)],
) -> Vec<(String, String, String, Option<f64>, String, String)> {
    let Some(arr) = root.as_array() else {
        return Vec::new();
    };
    let mut out = Vec::new();
    for item in arr {
        for (pid, pname, vpath, upath, default_units) in mappings {
            if let Some(val) = extract_f64(item, vpath) {
                let units = upath
                    .as_ref()
                    .and_then(|p| extract_string(item, p))
                    .or_else(|| default_units.clone())
                    .unwrap_or_default();
                let quality = extract_string(item, "quality").unwrap_or_else(|| "good".into());
                out.push((
                    pid.clone(),
                    pname.clone(),
                    vpath.clone(),
                    Some(val),
                    units,
                    quality,
                ));
            }
        }
    }
    out
}

fn extract_from_nested(
    root: &Value,
    mappings: &[(String, String, String, Option<String>, Option<String>)],
) -> Vec<(String, String, String, Option<f64>, String, String)> {
    extract_from_flat(root, mappings)
}

fn parse_index(segment: &str) -> Option<usize> {
    if segment.starts_with('[') && segment.ends_with(']') {
        segment[1..segment.len() - 1].parse().ok()
    } else {
        None
    }
}

fn value_to_string(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        Value::Bool(b) => b.to_string(),
        _ => v.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn extracts_flat_path() {
        let payload = json!({"main":{"temp":72.5,"unit":"degF"}});
        assert_eq!(extract_f64(&payload, "main.temp"), Some(72.5));
    }

    #[test]
    fn extracts_array_shape() {
        let payload = json!({"points":[{"id":"oat","value":55.2,"unit":"degF"}]});
        let maps = vec![(
            "oat".into(),
            "Outside Air Temp".into(),
            "value".into(),
            Some("unit".into()),
            None,
        )];
        let pts = extract_points_from_payload(&payload, "array", "points", &maps);
        assert_eq!(pts.len(), 1);
        assert_eq!(pts[0].3, Some(55.2));
    }

    #[test]
    fn extracts_nested_shape() {
        let payload = json!({"data":{"sensor":{"temperature":{"value":68.0}}}});
        let maps = vec![(
            "temp".into(),
            "Temp".into(),
            "data.sensor.temperature.value".into(),
            None,
            Some("degF".into()),
        )];
        let pts = extract_points_from_payload(&payload, "nested", "", &maps);
        assert_eq!(pts[0].3, Some(68.0));
    }
}
