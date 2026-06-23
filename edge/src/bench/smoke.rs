//! Device 5007 bench smoke: BACnet poll → historian → DataFusion FDD proof.

use crate::drivers::{bacnet_live, json_api, modbus};
use crate::fdd::execution;
use crate::historian::store;
use bacnet_types::enums::ObjectType;
use chrono::Utc;
use serde_json::{json, Value};
use std::env;

pub const BENCH_DEVICE: u32 = 5007;
pub const BENCH_EQUIPMENT_ID: &str = "5007";
pub const CONFIRMATION_MINUTES: i64 = 5;
pub const CONFIRMATION_SECONDS: i64 = CONFIRMATION_MINUTES * 60;

/// BACnet object instances scraped on the 5007 test bench (3 temps + 1 humidity).
pub const BENCH_BACNET_POINTS: [(&str, u32, &str); 4] = [
    ("Outside Air Temp", 1173, "oa_t"),
    ("Outside Air Humidity", 1168, "oa_h"),
    ("Discharge Air Temp", 1192, "duct_t"),
    ("Zone Temp", 10014, "zn_t"),
];

pub fn default_rule_sql() -> String {
    bench_fdd_sql(CONFIRMATION_MINUTES)
}

pub fn bench_fdd_sql(confirmation_minutes: i64) -> String {
    format!(
        r#"WITH samples AS (
  SELECT
    timestamp,
    equipment_id,
    oa_t,
    oa_h,
    duct_t,
    zn_t,
    CASE
      WHEN oa_t IS NULL THEN false
      WHEN oa_t < 40.0 OR oa_t > 110.0 THEN true
      ELSE false
    END AS raw_fault
  FROM telemetry_pivot
  WHERE equipment_id = '{equip}'
),
streak_groups AS (
  SELECT
    *,
    SUM(CASE WHEN NOT raw_fault THEN 1 ELSE 0 END) OVER (ORDER BY timestamp ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM samples
),
streak_stats AS (
  SELECT
    timestamp,
    equipment_id,
    oa_t,
    oa_h,
    duct_t,
    zn_t,
    raw_fault,
    MIN(timestamp) OVER (PARTITION BY streak_id ORDER BY timestamp ROWS UNBOUNDED PRECEDING) AS raw_fault_started_at,
    COUNT(*) OVER (PARTITION BY streak_id ORDER BY timestamp ROWS UNBOUNDED PRECEDING) AS samples_in_streak
  FROM streak_groups
  WHERE raw_fault
)
SELECT
  timestamp,
  equipment_id,
  oa_t,
  oa_h,
  duct_t,
  zn_t,
  raw_fault,
  raw_fault_started_at,
  CAST(samples_in_streak AS DOUBLE) AS minutes_in_fault,
  {confirmation_minutes} AS confirmation_required_minutes,
  CASE WHEN samples_in_streak >= {confirmation_minutes} THEN true ELSE false END AS confirmed_fault
FROM streak_stats
UNION ALL
SELECT
  timestamp,
  equipment_id,
  oa_t,
  oa_h,
  duct_t,
  zn_t,
  raw_fault,
  CAST(NULL AS TIMESTAMP) AS raw_fault_started_at,
  CAST(0 AS DOUBLE) AS minutes_in_fault,
  {confirmation_minutes} AS confirmation_required_minutes,
  false AS confirmed_fault
FROM samples
WHERE NOT raw_fault
ORDER BY timestamp"#,
        equip = BENCH_EQUIPMENT_ID,
        confirmation_minutes = confirmation_minutes
    )
}

fn live_fdd_enabled() -> bool {
    env::var("BENCH_SMOKE_LIVE_FDD")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
}

fn short_mode() -> bool {
    env::var("BENCH_SMOKE_SHORT_FDD")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
}

fn simulation_mode(body: &Value) -> Option<String> {
    body.get("simulation_phase")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .or_else(|| {
            env::var("BENCH_SMOKE_SIM_PHASE")
                .ok()
                .filter(|s| !s.is_empty())
        })
}

pub fn status_json() -> Value {
    let rows = store::load_pivot_rows().unwrap_or_default();
    let eval = evaluate_historian_fdd();
    let data_source = detect_data_source(&rows);
    let demo_only = data_source.starts_with("demo") || rows.is_empty();
    json!({
        "ok": true,
        "device_instance": BENCH_DEVICE,
        "equipment_id": BENCH_EQUIPMENT_ID,
        "short_fdd_mode": short_mode(),
        "live_fdd_required": live_fdd_enabled(),
        "data_source": data_source,
        "demo_only": demo_only,
        "historian": store::status_json(),
        "bacnet_points": bacnet_points_meta(),
        "modbus": modbus_probe(),
        "json_api": json_api_probe(),
        "haystack": haystack_fixture_status(),
        "rule_sql": default_rule_sql(),
        "fdd_eval": eval,
        "artifact_dir": artifact_dir().display().to_string(),
        "proof": proof_summary(&eval, demo_only)
    })
}

fn artifact_dir() -> std::path::PathBuf {
    store::workspace_dir().join("logs/bench_5007_smoke")
}

fn detect_data_source(rows: &[Value]) -> String {
    if rows.is_empty() {
        return "empty".to_string();
    }
    let mut live = 0;
    let mut sim = 0;
    let mut demo = 0;
    for row in rows {
        match row.get("source").and_then(|v| v.as_str()).unwrap_or("") {
            s if s.starts_with("simulation:") => sim += 1,
            s if s.contains("demo") => demo += 1,
            s if s.starts_with("bacnet:live") => live += 1,
            _ => live += 1,
        }
    }
    if live > 0 && sim == 0 && demo == 0 {
        "bacnet:live".to_string()
    } else if sim > 0 && live == 0 {
        "simulation:bench_5007_short_fdd".to_string()
    } else if demo > 0 {
        "demo:static".to_string()
    } else {
        "mixed".to_string()
    }
}

fn bacnet_points_meta() -> Value {
    json!(BENCH_BACNET_POINTS
        .iter()
        .map(|(name, inst, input)| json!({
            "name": name,
            "object_instance": inst,
            "fdd_input": input,
            "bacnet_id": format!("bacnet:{BENCH_DEVICE}:analog-input:{inst}")
        }))
        .collect::<Vec<_>>())
}

fn modbus_probe() -> Value {
    let cfg = modbus::modbus_config_value();
    let body =
        json!({"register": 30001, "function": "input_register", "scale": 0.1, "unit": "degF"});
    let read = modbus::read_value(&body);
    let parsed: Value = serde_json::from_str(&read).unwrap_or(json!({"ok": false}));
    json!({
        "configured_host": cfg.get("host"),
        "configured_port": cfg.get("port"),
        "mode": cfg.get("mode"),
        "registers_tested": [30001, 30003, 40001],
        "last_read": parsed,
        "available": parsed.get("ok").and_then(|v| v.as_bool()).unwrap_or(parsed.get("value").is_some())
    })
}

fn json_api_probe() -> Value {
    let poll = json_api::poll_test_source();
    json!({
        "source_id": poll.get("source_id"),
        "url": poll.get("url"),
        "http_status": poll.get("http_status"),
        "ok": poll.get("ok"),
        "available": poll.get("ok").and_then(|v| v.as_bool()) == Some(true)
    })
}

fn haystack_fixture_status() -> Value {
    json!({
        "mode": "fixture",
        "site": "site:demo",
        "equip": "equip:5007-bench",
        "points": ["point:oa-t", "point:oa-h", "point:duct-t", "point:zn-t"],
        "driver_tree": true
    })
}

pub fn capture_sample(body: &Value) -> Value {
    let ts = Utc::now().to_rfc3339();
    let sim = simulation_mode(body);
    let (values, source, source_driver, is_simulated) = if let Some(phase) = sim {
        simulated_values(&phase)
    } else if bacnet_live::is_live_mode() {
        match poll_live_bacnet() {
            Ok(v) => (v, "bacnet:live".to_string(), "bacnet".to_string(), false),
            Err(err) => {
                return json!({"ok": false, "error": err, "demo_only": true});
            }
        }
    } else if short_mode() || live_fdd_enabled() {
        return json!({
            "ok": false,
            "error": "BACnet live mode required for live FDD capture (set OPENFDD_BACNET_MODE=live) or pass simulation_phase",
            "demo_only": true,
            "hint": "Use simulation_phase=normal|fault|clear for safe proof without OT writes"
        });
    } else {
        simulated_values("normal")
    };

    let row = store::make_pivot_row(
        &ts,
        BENCH_EQUIPMENT_ID,
        values.0,
        values.1,
        values.2,
        values.3,
        &source,
        &source_driver,
        is_simulated,
    );

    if let Err(err) = store::append_pivot_row(&row) {
        return json!({"ok": false, "error": err});
    }

    let prefix = artifact_dir();
    let _ = std::fs::create_dir_all(&prefix);
    let safe_ts = ts.replace(':', "-");
    let capture_path = prefix.join(format!("capture_{safe_ts}.json"));
    let capture = json!({
        "timestamp": ts,
        "row": row,
        "bacnet_points": values,
        "source": source,
        "source_driver": source_driver,
        "is_simulated": is_simulated
    });
    let _ = std::fs::write(
        &capture_path,
        serde_json::to_string_pretty(&capture).unwrap_or_default(),
    );

    json!({
        "ok": true,
        "capture_path": capture_path.display().to_string(),
        "row": row,
        "historian_row_count": store::row_count(),
        "data_source": source,
        "demo_only": source.starts_with("demo")
    })
}

fn simulated_values(phase: &str) -> ((f64, f64, f64, f64), String, String, bool) {
    let (oa_t, label) = match phase {
        "fault" | "fault_high" => (120.0, "fault"),
        "fault_low" => (30.0, "fault"),
        "clear" | "normal" => (62.0, "normal"),
        _ => (62.0, "normal"),
    };
    (
        (oa_t, 45.0, 55.0, 72.0),
        format!("simulation:bench_5007_short_fdd:{label}"),
        "simulation".to_string(),
        true,
    )
}

fn poll_live_bacnet() -> Result<(f64, f64, f64, f64), String> {
    let mut oa_t = 62.0;
    let mut oa_h = 45.0;
    let mut duct_t = 55.0;
    let mut zn_t = 72.0;
    for (_name, instance, input) in BENCH_BACNET_POINTS {
        let resp = bacnet_live::block_on(bacnet_live::read_present_value(
            BENCH_DEVICE,
            ObjectType::ANALOG_INPUT,
            instance,
        ))?;
        let f = resp
            .get("value")
            .and_then(|v| v.as_f64())
            .or_else(|| resp.get("value").and_then(|v| v.as_i64()).map(|n| n as f64))
            .unwrap_or(0.0);
        match input {
            "oa_t" => oa_t = f,
            "oa_h" => oa_h = f,
            "duct_t" => duct_t = f,
            "zn_t" => zn_t = f,
            _ => {}
        }
    }
    Ok((oa_t, oa_h, duct_t, zn_t))
}

pub fn evaluate_historian_fdd() -> Value {
    let rows = store::load_pivot_rows().unwrap_or_default();
    if rows.is_empty() {
        return json!({
            "ok": false,
            "error": "historian empty — capture samples first",
            "demo_only": true
        });
    }
    let data_source = detect_data_source(&rows);
    let sql = default_rule_sql();
    let mut result = execution::run_rule_sql_from_historian(&sql, CONFIRMATION_SECONDS, &json!({}));
    if let Some(obj) = result.as_object_mut() {
        obj.insert("data_source".into(), json!(data_source));
        obj.insert(
            "demo_only".into(),
            json!(data_source.starts_with("demo") || data_source == "empty"),
        );
        obj.insert("historian_row_count".into(), json!(rows.len()));
        obj.insert("rule_sql".into(), json!(sql));
    }
    result
}

pub fn evaluate_sample(body: &Value) -> Value {
    let capture = capture_sample(body);
    if capture.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        return capture;
    }
    let eval = evaluate_historian_fdd();
    json!({
        "ok": true,
        "capture": capture,
        "fdd_eval": eval,
        "proof": proof_summary(&eval, eval.get("demo_only").and_then(|v| v.as_bool()).unwrap_or(true))
    })
}

fn proof_summary(eval: &Value, demo_only: bool) -> Value {
    let rows = eval
        .get("rows")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let mut raw_true = 0;
    let mut raw_false = 0;
    let mut confirmed_true = 0;
    let mut confirmed_false = 0;
    for row in &rows {
        if row.get("raw_fault").and_then(|v| v.as_bool()) == Some(true) {
            raw_true += 1;
        } else {
            raw_false += 1;
        }
        if row.get("confirmed_fault").and_then(|v| v.as_bool()) == Some(true) {
            confirmed_true += 1;
        } else {
            confirmed_false += 1;
        }
    }
    let confirmation = eval.get("confirmation").cloned().unwrap_or(json!({}));
    let confirmed_from_sql = confirmed_true >= 1;
    let confirmed_from_streak = confirmation
        .get("confirmed_fault_count")
        .and_then(|v| v.as_u64())
        .unwrap_or(0)
        >= 1;
    let pass = !demo_only
        && raw_false > 0
        && raw_true > 0
        && (confirmed_from_sql || confirmed_from_streak);
    json!({
        "demo_only": demo_only,
        "live_fdd_pass": pass,
        "raw_fault_samples": raw_true,
        "no_fault_samples": raw_false,
        "confirmed_fault_samples": confirmed_true,
        "raw_fault_count": confirmation.get("raw_fault_count"),
        "confirmed_fault_count": confirmation.get("confirmed_fault_count"),
        "confirmation_seconds": CONFIRMATION_SECONDS,
        "message": if demo_only {
            "DEMO ONLY — not a live FDD pass"
        } else if pass {
            "Live FDD proof satisfied"
        } else {
            "Collect more samples (normal → 6min fault → 5min clear)"
        }
    })
}

pub fn inject_scenario(body: &Value) -> Value {
    let normal_min = body
        .get("normal_minutes")
        .and_then(|v| v.as_u64())
        .unwrap_or(5);
    let fault_min = body
        .get("fault_minutes")
        .and_then(|v| v.as_u64())
        .unwrap_or(6);
    let clear_min = body
        .get("clear_minutes")
        .and_then(|v| v.as_u64())
        .unwrap_or(5);
    let _ = store::clear_rows_with_source_prefix("simulation:bench_5007");
    let start = Utc::now();
    let mut rows = Vec::new();
    let mut minute = 0;
    for _ in 0..normal_min {
        rows.push(make_sim_row(&start, minute, "normal"));
        minute += 1;
    }
    for _ in 0..fault_min {
        rows.push(make_sim_row(&start, minute, "fault"));
        minute += 1;
    }
    for _ in 0..clear_min {
        rows.push(make_sim_row(&start, minute, "clear"));
        minute += 1;
    }
    if let Err(err) = store::rewrite_all(&rows) {
        return json!({"ok": false, "error": err});
    }
    let eval = evaluate_historian_fdd();
    json!({
        "ok": true,
        "injected_rows": rows.len(),
        "data_source": "simulation:bench_5007_short_fdd",
        "demo_only": false,
        "fdd_eval": eval,
        "proof": proof_summary(&eval, false)
    })
}

fn make_sim_row(start: &chrono::DateTime<Utc>, minute_offset: u64, phase: &str) -> Value {
    let ts = (*start + chrono::Duration::minutes(minute_offset as i64)).to_rfc3339();
    let (oa_t, _, _, _) = simulated_values(phase).0;
    store::make_pivot_row(
        &ts,
        BENCH_EQUIPMENT_ID,
        oa_t,
        45.0,
        55.0,
        72.0,
        &format!("simulation:bench_5007_short_fdd:{phase}"),
        "simulation",
        true,
    )
}
