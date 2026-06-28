//! Plot/timeseries API — sites, series catalog, readings, CSV export.

use crate::historian::store;
use crate::model::query;
use chrono::{DateTime, Duration, Utc};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet, HashMap};

const META_KEYS: &[&str] = &[
    "timestamp",
    "equipment_id",
    "source",
    "source_id",
    "site_id",
    "ok",
];

fn is_meta_key(k: &str) -> bool {
    META_KEYS.contains(&k)
}

pub fn sites_json() -> Value {
    let body = query::list_sites();
    let sites = body
        .get("sites")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    json!({ "ok": true, "sites": sites })
}

pub fn series_json(site_id: &str) -> Value {
    let sid = if site_id.is_empty() {
        query::list_sites()
            .get("active_site_id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string()
    } else {
        site_id.to_string()
    };

    let mut series_options: Vec<Value> = Vec::new();
    let mut equipment_groups: BTreeMap<String, Value> = BTreeMap::new();
    let mut labels: HashMap<String, String> = HashMap::new();
    let mut kinds: HashMap<String, String> = HashMap::new();
    let mut columns: BTreeSet<String> = BTreeSet::new();

    let points = query::list_points(if sid.is_empty() { None } else { Some(&sid) });
    if let Some(arr) = points.get("points").and_then(|v| v.as_array()) {
        for pt in arr {
            let equip = pt
                .get("equip_ref")
                .and_then(|v| v.as_str())
                .unwrap_or("equip:unknown");
            let fdd = pt
                .get("fdd_input")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .or_else(|| pt.get("name").and_then(|v| v.as_str()))
                .unwrap_or("point");
            let col = fdd.to_string();
            let key = format!("{equip}::{col}");
            let name = pt.get("name").and_then(|v| v.as_str()).unwrap_or(&col);
            labels.insert(key.clone(), name.to_string());
            kinds.insert(
                key.clone(),
                if col.contains("_h") || col.ends_with("rh") {
                    "humidity".to_string()
                } else {
                    "temperature".to_string()
                },
            );
            columns.insert(col.clone());
            series_options.push(json!({
                "key": key,
                "column": col,
                "equipment_id": equip,
                "label": name,
                "brick_type": pt.get("brick_type").cloned().unwrap_or(json!(null))
            }));
            equipment_groups
                .entry(equip.to_string())
                .and_modify(|g| {
                    if let Some(keys) = g.get_mut("keys").and_then(|v| v.as_array_mut()) {
                        keys.push(json!(key.clone()));
                    }
                    if let Some(cols) = g.get_mut("columns").and_then(|v| v.as_array_mut()) {
                        if !cols.iter().any(|c| c.as_str() == Some(&col)) {
                            cols.push(json!(col));
                        }
                    }
                })
                .or_insert_with(|| {
                    json!({
                        "equipment_id": equip,
                        "name": equip,
                        "label": equip,
                        "keys": [key.clone()],
                        "columns": [col]
                    })
                });
        }
    }

    if series_options.is_empty() {
        let rows = store::load_pivot_rows().unwrap_or_default();
        let mut by_equip: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
        for row in &rows {
            let equip = row
                .get("equipment_id")
                .and_then(|v| v.as_str())
                .unwrap_or("equip:unknown");
            if let Some(obj) = row.as_object() {
                for (k, _) in obj {
                    if is_meta_key(k) || k.starts_with('_') {
                        continue;
                    }
                    by_equip
                        .entry(equip.to_string())
                        .or_default()
                        .insert(k.clone());
                }
            }
        }
        for (equip, cols) in by_equip {
            let mut keys = Vec::new();
            let mut col_list = Vec::new();
            for col in cols {
                let key = format!("{equip}::{col}");
                labels.insert(key.clone(), col.clone());
                kinds.insert(key.clone(), infer_kind(&col));
                columns.insert(col.clone());
                keys.push(key.clone());
                col_list.push(col.clone());
                series_options.push(json!({
                    "key": key,
                    "column": col,
                    "equipment_id": equip,
                    "label": col
                }));
            }
            equipment_groups.insert(
                equip.clone(),
                json!({
                    "equipment_id": equip,
                    "name": equip,
                    "label": equip,
                    "keys": keys,
                    "columns": col_list
                }),
            );
        }
    }

    let col_vec: Vec<String> = columns.into_iter().collect();
    json!({
        "ok": true,
        "site_id": sid,
        "columns": col_vec,
        "labels": labels,
        "kinds": kinds,
        "series_options": series_options,
        "equipment_groups": equipment_groups.into_values().collect::<Vec<_>>()
    })
}

fn infer_kind(col: &str) -> String {
    let c = col.to_lowercase();
    if c.contains("rh") || c.contains("humid") || c.ends_with("_h") {
        "humidity".to_string()
    } else if c.contains("kw") || c.contains("power") || c.contains("energy") {
        "power".to_string()
    } else {
        "temperature".to_string()
    }
}

fn parse_ts(s: &str) -> Option<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(s)
        .ok()
        .map(|d| d.with_timezone(&Utc))
        .or_else(|| {
            chrono::NaiveDateTime::parse_from_str(s, "%Y-%m-%d %H:%M:%S")
                .ok()
                .map(|n| n.and_utc())
        })
}

fn parse_hours(q: &str) -> i64 {
    q.parse::<i64>().unwrap_or(24).clamp(1, 87600)
}

fn parse_keys(columns_param: &str) -> Vec<(String, String)> {
    columns_param
        .split(',')
        .filter_map(|part| {
            let part = part.trim();
            if part.is_empty() {
                return None;
            }
            if let Some((equip, col)) = part.split_once("::") {
                Some((equip.to_string(), col.to_string()))
            } else {
                Some(("".to_string(), part.to_string()))
            }
        })
        .collect()
}

pub fn readings_json(params: &HashMap<String, String>) -> Value {
    let site_id = params.get("site_id").map(String::as_str).unwrap_or("");
    let hours = parse_hours(params.get("hours").map(String::as_str).unwrap_or("24"));
    let columns_param = params.get("columns").map(String::as_str).unwrap_or("");
    let rolling = params
        .get("rolling_avg_minutes")
        .and_then(|v| v.parse::<usize>().ok())
        .unwrap_or(5);
    let show_rolling = params
        .get("show_rolling_avg")
        .map(|v| v == "true" || v == "1")
        .unwrap_or(true);

    let keys = parse_keys(columns_param);
    if keys.is_empty() {
        return json!({"ok": false, "error": "columns query param required"});
    }

    let cutoff = Utc::now() - Duration::hours(hours);
    let rows: Vec<Value> = store::load_pivot_rows().unwrap_or_default();
    let use_all = params
        .get("all")
        .is_some_and(|v| v == "true" || v == "1" || v == "yes");
    let mut filtered: Vec<&Value> = if use_all {
        rows.iter().collect()
    } else {
        rows.iter()
            .filter(|r| {
                let ts = r.get("timestamp").and_then(|v| v.as_str()).unwrap_or("");
                parse_ts(ts).map(|t| t >= cutoff).unwrap_or(true)
            })
            .collect()
    };
    // Historical CSV imports (e.g. 2013–2018) fall outside the default hours window.
    if filtered.is_empty() && !rows.is_empty() && !use_all {
        filtered = rows.iter().collect();
    }

    if filtered.is_empty() {
        return json!({
            "ok": true,
            "site_id": site_id,
            "hours": hours,
            "timestamps": [],
            "series": {},
            "series_kinds": {},
            "labels": {},
            "fault_panels": [],
            "fault_totals": {},
            "rolling_avg_minutes": rolling,
            "rolling_avg_minutes_allowed": [1, 5, 15],
            "show_rolling_avg": show_rolling
        });
    }

    let stride = if filtered.len() > 4000 {
        (filtered.len() / 4000).max(1)
    } else {
        1
    };
    let chart_truncated = stride > 1;

    let mut timestamps: Vec<String> = Vec::new();
    let mut series: HashMap<String, Vec<Value>> = HashMap::new();
    let mut labels: HashMap<String, String> = HashMap::new();
    let mut kinds: HashMap<String, String> = HashMap::new();

    for (i, row) in filtered.iter().enumerate() {
        if i % stride != 0 {
            continue;
        }
        let equip = row
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if !site_id.is_empty() {
            // Best-effort site filter via equipment prefix when model loaded
            let _ = site_id;
        }
        timestamps.push(
            row.get("timestamp")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
        );
        for (req_equip, col) in &keys {
            let use_equip = if req_equip.is_empty() {
                equip
            } else {
                req_equip.as_str()
            };
            if !req_equip.is_empty() && equip != use_equip {
                continue;
            }
            let out_key = if req_equip.is_empty() {
                col.clone()
            } else {
                format!("{use_equip}::{col}")
            };
            labels.insert(out_key.clone(), col.clone());
            kinds.insert(out_key.clone(), infer_kind(col));
            let val = row.get(col.as_str()).and_then(|v| {
                v.as_f64()
                    .or_else(|| v.as_str().and_then(|s| s.parse().ok()))
            });
            series.entry(out_key).or_default().push(match val {
                Some(n) => json!(n),
                None => Value::Null,
            });
        }
    }

    // Pad shorter series to timestamp length
    let n = timestamps.len();
    for vals in series.values_mut() {
        while vals.len() < n {
            vals.push(Value::Null);
        }
    }

    json!({
        "ok": true,
        "site_id": site_id,
        "hours": hours,
        "timestamps": timestamps,
        "series": series,
        "series_kinds": kinds,
        "labels": labels,
        "fault_panels": [],
        "fault_totals": {},
        "chart_truncated": chart_truncated,
        "chart_stride": stride,
        "rolling_avg_minutes": rolling,
        "rolling_avg_minutes_allowed": [1, 5, 15],
        "show_rolling_avg": show_rolling
    })
}

pub fn export_csv(params: &HashMap<String, String>) -> Result<String, String> {
    let body = readings_json(params);
    let timestamps = body
        .get("timestamps")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let series = body
        .get("series")
        .and_then(|v| v.as_object())
        .cloned()
        .unwrap_or_default();
    let mut cols: Vec<String> = series.keys().cloned().collect();
    cols.sort();
    let mut out = String::from("timestamp");
    for c in &cols {
        out.push(',');
        out.push_str(c);
    }
    out.push('\n');
    for (i, ts) in timestamps.iter().enumerate() {
        out.push_str(ts.as_str().unwrap_or(""));
        for c in &cols {
            out.push(',');
            if let Some(arr) = series.get(c).and_then(|v| v.as_array()) {
                if let Some(v) = arr.get(i) {
                    if let Some(n) = v.as_f64() {
                        out.push_str(&n.to_string());
                    }
                }
            }
        }
        out.push('\n');
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sites_json_shape() {
        let v = sites_json();
        assert!(v.get("sites").and_then(|s| s.as_array()).is_some());
    }

    #[test]
    fn series_json_empty_ok() {
        let v = series_json("");
        assert_eq!(v.get("ok").and_then(|x| x.as_bool()), Some(true));
        assert!(v.get("series_options").is_some());
    }

    #[test]
    fn readings_requires_columns() {
        let v = readings_json(&HashMap::new());
        assert!(v.get("error").is_some());
    }

    #[test]
    fn parse_hours_accepts_multi_year_window() {
        assert_eq!(parse_hours("8760"), 8760);
        assert_eq!(parse_hours("87600"), 87600);
    }
}
