//! Per-role PID and sensor diagnostic rows.
//!
//! Timescale returns one observation per equipment role. The matrix keeps that
//! identity (site, equipment, role) and the proxy flag. A repeated identity
//! collapses to one row; an OK flag never replaces a fault or hunt flag.

use serde_json::{json, Map, Value};

pub const DIAGNOSTIC_MATRIX_SCHEMA: &str = "diagnostic_matrix_v1";
pub const DIAGNOSTIC_MATRIX_QUERY_VERSION: &str = "diagnostic-matrix-v1";

const ROW_KEY_SEP: char = '\u{1f}';

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DiagnosticFlagKind {
    Fault,
    Hunt,
}

impl DiagnosticFlagKind {
    fn as_str(self) -> &'static str {
        match self {
            Self::Fault => "fault",
            Self::Hunt => "hunt",
        }
    }
}

#[derive(Debug)]
pub struct DiagnosticObservation {
    pub equipment_id: String,
    pub role: String,
    pub flag: String,
    pub n: Option<i64>,
    pub last_ts: Option<String>,
    pub min_val: Option<f64>,
    pub max_val: Option<f64>,
    pub avg_val: Option<f64>,
    pub stddev_val: Option<f64>,
}

pub fn diagnostic_row_key(site_id: &str, equipment_id: &str, role: &str) -> String {
    format!("{site_id}{ROW_KEY_SEP}{equipment_id}{ROW_KEY_SEP}{role}")
}

fn is_ok_flag(flag: &str) -> bool {
    flag.eq_ignore_ascii_case("OK")
}

/// A real proxy flag replaces OK. OK never hides a flag already kept.
fn incoming_replaces(existing: &str, incoming: &str) -> bool {
    is_ok_flag(existing) && !is_ok_flag(incoming)
}

pub fn diagnostic_rows_json(
    site_id: &str,
    kind: DiagnosticFlagKind,
    mut observations: Vec<DiagnosticObservation>,
) -> Vec<Value> {
    observations.sort_by(|left, right| {
        left.equipment_id
            .cmp(&right.equipment_id)
            .then_with(|| left.role.cmp(&right.role))
    });
    let mut kept: Vec<DiagnosticObservation> = Vec::new();
    for observation in observations {
        if let Some(previous) = kept.last_mut() {
            if previous.equipment_id == observation.equipment_id
                && previous.role == observation.role
            {
                if incoming_replaces(&previous.flag, &observation.flag) {
                    *previous = observation;
                }
                continue;
            }
        }
        kept.push(observation);
    }
    kept.into_iter()
        .map(|observation| row_json(site_id, kind, observation))
        .collect()
}

fn insert_opt_f64(obj: &mut Map<String, Value>, key: &str, value: Option<f64>) {
    if let Some(value) = value {
        obj.insert(key.to_string(), json!(value));
    }
}

fn insert_opt_string(obj: &mut Map<String, Value>, key: &str, value: Option<String>) {
    if let Some(value) = value {
        obj.insert(key.to_string(), json!(value));
    }
}

fn row_json(site_id: &str, kind: DiagnosticFlagKind, observation: DiagnosticObservation) -> Value {
    let DiagnosticObservation {
        equipment_id,
        role,
        flag,
        n,
        last_ts,
        min_val,
        max_val,
        avg_val,
        stddev_val,
    } = observation;
    let mut row = Map::new();
    row.insert(
        "row_key".to_string(),
        json!(diagnostic_row_key(site_id, &equipment_id, &role)),
    );
    row.insert(
        "schema_version".to_string(),
        json!(DIAGNOSTIC_MATRIX_SCHEMA),
    );
    row.insert("site_id".to_string(), json!(site_id));
    row.insert("building_id".to_string(), json!(site_id));
    row.insert("equipment_id".to_string(), json!(equipment_id));
    row.insert("role".to_string(), json!(role));
    row.insert("flag".to_string(), json!(&flag));
    row.insert("flag_kind".to_string(), json!(kind.as_str()));
    row.insert("n".to_string(), json!(n));
    match kind {
        DiagnosticFlagKind::Fault => {
            row.insert("fault_flag".to_string(), json!(flag));
        }
        DiagnosticFlagKind::Hunt => {
            row.insert("hunt_flag".to_string(), json!(flag));
        }
    }
    insert_opt_string(&mut row, "last_ts", last_ts);
    insert_opt_f64(&mut row, "min_val", min_val);
    insert_opt_f64(&mut row, "max_val", max_val);
    insert_opt_f64(&mut row, "avg_val", avg_val);
    insert_opt_f64(&mut row, "stddev_val", stddev_val);
    Value::Object(row)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn obs(equipment: &str, role: &str, flag: &str) -> DiagnosticObservation {
        DiagnosticObservation {
            equipment_id: equipment.into(),
            role: role.into(),
            flag: flag.into(),
            n: Some(12),
            last_ts: None,
            min_val: None,
            max_val: None,
            avg_val: None,
            stddev_val: None,
        }
    }

    #[test]
    fn duplicate_identity_keeps_one_row_and_the_proxy_flag() {
        let rows = diagnostic_rows_json(
            "site-a",
            DiagnosticFlagKind::Fault,
            vec![
                obs("flat_unit", "sat", "OK"),
                obs("flat_unit", "sat", "FLATLINE"),
                obs("flat_unit", "zone_t", "OK"),
                obs("flat_unit", "sat", "OK"),
            ],
        );
        assert_eq!(rows.len(), 2);
        let sat = rows
            .iter()
            .find(|row| row["role"] == json!("sat"))
            .expect("sat row");
        assert_eq!(sat["equipment_id"], json!("flat_unit"));
        assert_eq!(sat["fault_flag"], json!("FLATLINE"));
        assert_eq!(sat["flag"], json!("FLATLINE"));
        assert_eq!(sat["flag_kind"], json!("fault"));
        assert_eq!(
            sat["row_key"],
            json!(diagnostic_row_key("site-a", "flat_unit", "sat"))
        );
        assert_eq!(sat["site_id"], json!("site-a"));
        assert!(sat.get("hunt_flag").is_none());
        let keys: Vec<_> = rows
            .iter()
            .map(|row| row["row_key"].as_str().unwrap_or_default())
            .collect();
        let mut unique = keys.clone();
        unique.sort_unstable();
        unique.dedup();
        assert_eq!(unique.len(), keys.len());
    }

    #[test]
    fn hunt_rows_keep_hunt_flag() {
        let rows = diagnostic_rows_json(
            "site-b",
            DiagnosticFlagKind::Hunt,
            vec![obs("hunt_unit", "zone_t", "HUNT_PROXY")],
        );
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0]["hunt_flag"], json!("HUNT_PROXY"));
        assert_eq!(rows[0]["flag_kind"], json!("hunt"));
        assert!(rows[0].get("fault_flag").is_none());
        assert_eq!(
            rows[0]["row_key"],
            json!("site-b\u{1f}hunt_unit\u{1f}zone_t")
        );
    }
}
