//! Overview calendar → `occ_mode` for product SQL.
//!
//! The UI persists `occupancy_schedule` on session config. Historian rows often
//! have no BAS occupied point. When the calendar is saved, rule runs and RCx
//! fill a missing or blank `occ_mode` from that weekly window so VAV-1 (and
//! VAV-2) see the same occupied / unoccupied signal.

use std::path::PathBuf;

use anyhow::{Context, Result};
use datafusion::prelude::SessionContext;
use serde_json::Value;

const DAY_DOW: &[(&str, i32)] = &[
    ("sun", 0),
    ("mon", 1),
    ("tue", 2),
    ("wed", 3),
    ("thu", 4),
    ("fri", 5),
    ("sat", 6),
];

fn session_config_path() -> PathBuf {
    match std::env::var("OPENFDD_WORKSPACE") {
        Ok(ws) => PathBuf::from(ws).join("data").join("session_config.json"),
        Err(_) => PathBuf::from("workspace")
            .join("data")
            .join("session_config.json"),
    }
}

/// Saved Overview calendar, if the session file contains `occupancy_schedule`.
pub fn load_session_occupancy_schedule() -> Option<Value> {
    let text = std::fs::read_to_string(session_config_path()).ok()?;
    let v: Value = serde_json::from_str(&text).ok()?;
    let sched = v
        .get("occupancy_schedule")
        .or_else(|| v.get("config").and_then(|c| c.get("occupancy_schedule")))?;
    sched.as_object()?;
    Some(sched.clone())
}

fn tz_ok(tz: &str) -> bool {
    !tz.is_empty()
        && tz.len() <= 64
        && tz
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '/' | '+' | '-'))
}

fn hhmm_minutes(text: &str) -> Option<i32> {
    let mut parts = text.trim().split(':');
    let h: i32 = parts.next()?.parse().ok()?;
    let m: i32 = parts.next().unwrap_or("0").parse().ok()?;
    if (0..24).contains(&h) && (0..60).contains(&m) {
        Some(h * 60 + m)
    } else {
        None
    }
}

/// SQL expression that yields `'occupied'` or `'unoccupied'` from `ts_sql`.
///
/// `date_part('dow')` is Sunday = 0. The timestamp is read as UTC and shown in
/// the schedule timezone.
pub fn calendar_occ_mode_sql(schedule: &Value, ts_sql: &str) -> Option<String> {
    let days = schedule.get("days")?.as_object()?;
    let tz = schedule
        .get("timezone")
        .and_then(|v| v.as_str())
        .unwrap_or("UTC");
    if !tz_ok(tz) || !ident_ok(ts_sql) {
        return None;
    }
    let local =
        format!("(arrow_cast({ts_sql}, 'Timestamp(Nanosecond, \"UTC\")') AT TIME ZONE '{tz}')");
    let mins = format!("(date_part('hour', {local}) * 60 + date_part('minute', {local}))");
    let mut arms = Vec::new();
    for (name, dow) in DAY_DOW {
        let Some(day) = days.get(*name).and_then(|v| v.as_object()) else {
            continue;
        };
        if !day
            .get("occupied")
            .and_then(|v| v.as_bool())
            .unwrap_or(false)
        {
            continue;
        }
        let start = hhmm_minutes(day.get("start").and_then(|v| v.as_str()).unwrap_or("06:00"))?;
        let end = hhmm_minutes(day.get("end").and_then(|v| v.as_str()).unwrap_or("18:00"))?;
        let window = if end <= start {
            format!("({mins} >= {start} OR {mins} < {end})")
        } else {
            format!("({mins} >= {start} AND {mins} < {end})")
        };
        arms.push(format!("(date_part('dow', {local}) = {dow} AND {window})"));
    }
    if arms.is_empty() {
        return Some("'unoccupied'".to_string());
    }
    Some(format!(
        "CASE WHEN {} THEN 'occupied' ELSE 'unoccupied' END",
        arms.join(" OR ")
    ))
}

fn ident_ok(name: &str) -> bool {
    !name.is_empty() && name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
}

/// Replace `history` so blank `occ_mode` comes from the calendar.
///
/// A non-blank BAS `occ_mode` is kept. Returns false when history has no
/// timestamp column or the calendar SQL does not plan.
pub async fn overlay_history_occ_mode(ctx: &SessionContext, schedule: &Value) -> Result<bool> {
    let df = match ctx.table("history").await {
        Ok(df) => df,
        Err(_) => return Ok(false),
    };
    let names: Vec<String> = df
        .schema()
        .fields()
        .iter()
        .map(|f| f.name().to_string())
        .collect();
    let Some(ts) = names
        .iter()
        .find(|n| n.eq_ignore_ascii_case("timestamp_utc"))
    else {
        return Ok(false);
    };
    let Some(expr) = calendar_occ_mode_sql(schedule, ts) else {
        return Ok(false);
    };
    let sql = if let Some(occ) = names.iter().find(|n| n.eq_ignore_ascii_case("occ_mode")) {
        format!(
            "SELECT * EXCEPT ({occ}), CASE \
               WHEN {occ} IS NOT NULL AND trim(CAST({occ} AS VARCHAR)) <> '' \
               THEN CAST({occ} AS VARCHAR) ELSE {expr} END AS {occ} \
             FROM history"
        )
    } else {
        format!("SELECT *, CAST({expr} AS VARCHAR) AS occ_mode FROM history")
    };
    let view = match ctx.sql(&sql).await {
        Ok(view) => view,
        Err(_) => return Ok(false),
    };
    ctx.deregister_table("history")
        .context("deregister history for occupancy overlay")?;
    ctx.register_table("history", view.into_view())
        .context("register occupancy overlay")?;
    Ok(true)
}

/// Apply the saved Overview calendar when `occupancy_schedule` is present.
pub async fn apply_session_occupancy_schedule(ctx: &SessionContext) -> Result<bool> {
    let Some(schedule) = load_session_occupancy_schedule() else {
        return Ok(false);
    };
    overlay_history_occ_mode(ctx, &schedule).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::params::{rule_params, substitute_sql};
    use datafusion::arrow::array::{Float64Array, StringArray, TimestampMillisecondArray};
    use datafusion::arrow::datatypes::{DataType, Field, Schema, TimeUnit};
    use datafusion::arrow::record_batch::RecordBatch;
    use datafusion::prelude::SessionContext;
    use fdd_sql::run_sql;
    use std::sync::Arc;

    fn schedule() -> Value {
        serde_json::json!({
            "timezone": "America/Chicago",
            "days": {
                "mon": {"occupied": true, "start": "06:00", "end": "18:00"},
                "tue": {"occupied": true, "start": "06:00", "end": "18:00"},
                "wed": {"occupied": true, "start": "06:00", "end": "18:00"},
                "thu": {"occupied": true, "start": "06:00", "end": "18:00"},
                "fri": {"occupied": true, "start": "06:00", "end": "18:00"},
                "sat": {"occupied": false, "start": "06:00", "end": "18:00"},
                "sun": {"occupied": false, "start": "06:00", "end": "18:00"}
            }
        })
    }

    #[tokio::test]
    async fn overview_calendar_fills_occ_mode_and_vav1_skips_unoccupied() {
        // Monday 2026-01-05. 08:00Z = 02:00 Chicago (unoccupied), 16:00Z = 10:00, 17:00Z = 11:00.
        let schema = Arc::new(Schema::new(vec![
            Field::new(
                "timestamp_utc",
                DataType::Timestamp(TimeUnit::Millisecond, None),
                false,
            ),
            Field::new("equipment_id", DataType::Utf8, false),
            Field::new("zone_t", DataType::Float64, true),
        ]));
        let batch = RecordBatch::try_new(
            schema,
            vec![
                Arc::new(TimestampMillisecondArray::from(vec![
                    1_767_600_000_000,
                    1_767_628_800_000,
                    1_767_632_400_000,
                ])),
                Arc::new(StringArray::from(vec!["AC_FCU"; 3])),
                Arc::new(Float64Array::from(vec![80.0, 80.0, 72.0])),
            ],
        )
        .unwrap();
        let ctx = SessionContext::new();
        ctx.register_batch("history", batch).unwrap();
        assert!(overlay_history_occ_mode(&ctx, &schedule()).await.unwrap());
        let labels = run_sql(&ctx, "SELECT occ_mode FROM history ORDER BY timestamp_utc")
            .await
            .unwrap();
        let modes: Vec<&str> = labels
            .rows
            .iter()
            .map(|r| r.get("occ_mode").and_then(|v| v.as_str()).unwrap_or(""))
            .collect();
        assert_eq!(modes, vec!["unoccupied", "occupied", "occupied"]);

        let raw = std::fs::read_to_string(
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../..")
                .join("sql_rules/vav1_comfort_fault.sql"),
        )
        .unwrap();
        let mut params = rule_params(300.0, 300);
        params.insert("ZONE_T_LO".into(), "70".into());
        params.insert("ZONE_T_HI".into(), "75".into());
        params.insert("REQUIRE_OCCUPIED".into(), "1".into());
        let sql = substitute_sql(&raw, &params);
        let result = run_sql(&ctx, &sql).await.unwrap();
        let hours = result.rows[0]
            .get("fault_hours")
            .and_then(|v| v.as_f64())
            .unwrap();
        assert!((hours - 300.0 / 3600.0).abs() < 1e-9, "hours={hours}");
    }

    #[tokio::test]
    async fn bas_occ_mode_wins_over_calendar() {
        let schema = Arc::new(Schema::new(vec![
            Field::new(
                "timestamp_utc",
                DataType::Timestamp(TimeUnit::Millisecond, None),
                false,
            ),
            Field::new("equipment_id", DataType::Utf8, false),
            Field::new("occ_mode", DataType::Utf8, true),
        ]));
        let batch = RecordBatch::try_new(
            schema,
            vec![
                Arc::new(TimestampMillisecondArray::from(vec![1_767_628_800_000])),
                Arc::new(StringArray::from(vec!["jci_vav_12"])),
                Arc::new(StringArray::from(vec![Some("unoccupied")])),
            ],
        )
        .unwrap();
        let ctx = SessionContext::new();
        ctx.register_batch("history", batch).unwrap();
        assert!(overlay_history_occ_mode(&ctx, &schedule()).await.unwrap());
        let labels = run_sql(&ctx, "SELECT occ_mode FROM history").await.unwrap();
        assert_eq!(
            labels.rows[0].get("occ_mode").and_then(|v| v.as_str()),
            Some("unoccupied")
        );
    }
}
