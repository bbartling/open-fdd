//! Confirmation duration logic for raw faults → confirmed faults.

use serde_json::{json, Value};

pub fn apply_confirmation(raw_rows: &[Value], confirmation_seconds: i64) -> Value {
    if raw_rows.is_empty() {
        return json!({
            "ok": true,
            "raw_fault_count": 0,
            "confirmed_fault_count": 0,
            "confirmation_seconds": confirmation_seconds,
            "confirmed": []
        });
    }

    let mut confirmed = Vec::new();
    let mut streak_start: Option<i64> = None;
    let mut last_ts: Option<i64> = None;
    let mut raw_count = 0_i64;

    for row in raw_rows {
        let fault = row
            .get("fault_raw")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        if fault {
            raw_count += 1;
        }
        let ts = parse_ts(row.get("timestamp").or_else(|| row.get("ts")));
        if fault {
            if streak_start.is_none() {
                streak_start = Some(ts);
            }
            last_ts = Some(ts);
        } else {
            if let (Some(start), Some(end)) = (streak_start, last_ts) {
                if end - start >= confirmation_seconds {
                    confirmed.push(json!({
                        "start": start,
                        "end": end,
                        "duration_seconds": end - start,
                        "equipment_id": row.get("equipment_id").cloned().unwrap_or(json!(null)),
                    }));
                }
            }
            streak_start = None;
            last_ts = None;
        }
    }
    if let (Some(start), Some(end)) = (streak_start, last_ts) {
        if end - start >= confirmation_seconds {
            confirmed.push(json!({
                "start": start,
                "end": end,
                "duration_seconds": end - start,
                "confirmed_at_end": true
            }));
        }
    }

    json!({
        "ok": true,
        "raw_fault_count": raw_count,
        "confirmed_fault_count": confirmed.len(),
        "confirmation_seconds": confirmation_seconds,
        "confirmed": confirmed
    })
}

fn parse_ts(value: Option<&Value>) -> i64 {
    value
        .and_then(|v| v.as_str())
        .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
        .map(|dt| dt.timestamp())
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn confirms_after_duration() {
        let rows = vec![
            json!({"timestamp":"2026-06-21T00:00:00Z","fault_raw":true,"equipment_id":"AHU-1"}),
            json!({"timestamp":"2026-06-21T00:06:00Z","fault_raw":true,"equipment_id":"AHU-1"}),
            json!({"timestamp":"2026-06-21T00:11:00Z","fault_raw":false,"equipment_id":"AHU-1"}),
        ];
        let out = apply_confirmation(&rows, 300);
        assert_eq!(out["confirmed_fault_count"].as_u64(), Some(1));
    }
}
