//! Weekly occupancy calendar (Overview session parity) for VAV-1 / SCHED overlays.

use anyhow::{Context, Result};
use chrono::{DateTime, Datelike, Timelike, Utc};
use serde_json::Value;
use sqlx::PgConnection;

const WEEKDAYS: [&str; 7] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

#[derive(Debug, Clone)]
pub struct DaySchedule {
    pub occupied: bool,
    pub start: String,
    pub end: String,
}

#[derive(Debug, Clone)]
pub struct OccupancySchedule {
    pub timezone: String,
    pub days: std::collections::HashMap<String, DaySchedule>,
}

impl OccupancySchedule {
    pub fn from_json(value: &Value) -> Option<Self> {
        let obj = value.as_object()?;
        let timezone = obj
            .get("timezone")
            .and_then(Value::as_str)
            .unwrap_or("America/Chicago")
            .to_string();
        let raw_days = obj.get("days").and_then(Value::as_object);
        let mut days = std::collections::HashMap::new();
        for (idx, key) in WEEKDAYS.iter().enumerate() {
            let row = raw_days
                .and_then(|d| d.get(*key))
                .and_then(Value::as_object);
            let legacy_sat = if *key == "sat" {
                raw_days.and_then(|d| d.get("discharge-air-temp"))
            } else {
                None
            };
            let row = row.or_else(|| legacy_sat.and_then(Value::as_object));
            let occupied = row
                .and_then(|r| r.get("occupied"))
                .and_then(Value::as_bool)
                .unwrap_or(!matches!(*key, "sat" | "sun"));
            let start = row
                .and_then(|r| r.get("start"))
                .and_then(Value::as_str)
                .unwrap_or("06:00")
                .to_string();
            let end = row
                .and_then(|r| r.get("end"))
                .and_then(Value::as_str)
                .unwrap_or("18:00")
                .to_string();
            days.insert(
                key.to_string(),
                DaySchedule {
                    occupied,
                    start,
                    end,
                },
            );
            let _ = idx;
        }
        Some(Self { timezone, days })
    }

    fn weekday_key(weekday: chrono::Weekday) -> &'static str {
        match weekday {
            chrono::Weekday::Mon => "mon",
            chrono::Weekday::Tue => "tue",
            chrono::Weekday::Wed => "wed",
            chrono::Weekday::Thu => "thu",
            chrono::Weekday::Fri => "fri",
            chrono::Weekday::Sat => "sat",
            chrono::Weekday::Sun => "sun",
        }
    }

    fn parse_hhmm(text: &str) -> (u32, u32) {
        let parts: Vec<&str> = text.trim().split(':').collect();
        let h = parts.first().and_then(|p| p.parse().ok()).unwrap_or(0);
        let m = parts.get(1).and_then(|p| p.parse().ok()).unwrap_or(0);
        (h, m)
    }

    pub fn timestamp_occupied(&self, ts: DateTime<Utc>) -> bool {
        let tz: chrono_tz::Tz = self.timezone.parse().unwrap_or(chrono_tz::UTC);
        let local = ts.with_timezone(&tz);
        let key = Self::weekday_key(local.weekday());
        let day = self.days.get(key).cloned().unwrap_or_else(|| DaySchedule {
            occupied: false,
            start: "06:00".into(),
            end: "18:00".into(),
        });
        if !day.occupied {
            return false;
        }
        let (sh, sm) = Self::parse_hhmm(&day.start);
        let (eh, em) = Self::parse_hhmm(&day.end);
        let start_m = sh * 60 + sm;
        let end_m = eh * 60 + em;
        let mins = local.hour() * 60 + local.minute();
        if end_m <= start_m {
            mins >= start_m || mins < end_m
        } else {
            start_m <= mins && mins < end_m
        }
    }
}

pub fn occupancy_schedule_from_payload(payload: &Value) -> Option<OccupancySchedule> {
    for key in ["occupancy_schedule"] {
        if let Some(sched) = payload.get(key) {
            if let Some(parsed) = OccupancySchedule::from_json(sched) {
                return Some(parsed);
            }
        }
        if let Some(sched) = payload
            .get("params")
            .and_then(|p| p.get(key))
            .or_else(|| payload.get("config").and_then(|c| c.get(key)))
        {
            if let Some(parsed) = OccupancySchedule::from_json(sched) {
                return Some(parsed);
            }
        }
    }
    None
}

pub async fn history_has_modeled_occ_mode(conn: &mut PgConnection) -> Result<bool> {
    let count: i64 =
        sqlx::query_scalar("SELECT COUNT(*)::bigint FROM history WHERE occ_mode IS NOT NULL")
            .fetch_one(&mut *conn)
            .await
            .context("history occ_mode count")?;
    Ok(count > 0)
}

pub async fn synthesize_occ_mode_from_schedule(
    conn: &mut PgConnection,
    schedule: &OccupancySchedule,
) -> Result<()> {
    let rows = sqlx::query("SELECT timestamp_utc FROM history ORDER BY timestamp_utc")
        .fetch_all(&mut *conn)
        .await
        .context("history timestamps")?;
    for row in rows {
        let ts: DateTime<Utc> = row.try_get("timestamp_utc")?;
        let val = if schedule.timestamp_occupied(ts) {
            1.0
        } else {
            0.0
        };
        sqlx::query("UPDATE history SET occ_mode = $1 WHERE timestamp_utc = $2")
            .bind(val)
            .bind(ts)
            .execute(&mut *conn)
            .await
            .context("update occ_mode")?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    #[test]
    fn parses_default_calendar_json() {
        let sched = OccupancySchedule::from_json(&serde_json::json!({
            "timezone": "UTC",
            "days": {
                "mon": { "occupied": true, "start": "06:00", "end": "18:00" }
            }
        }))
        .expect("schedule");
        let ts = Utc.with_ymd_and_hms(2026, 1, 5, 12, 0, 0).unwrap();
        assert!(sched.timestamp_occupied(ts));
        let night = Utc.with_ymd_and_hms(2026, 1, 5, 2, 0, 0).unwrap();
        assert!(!sched.timestamp_occupied(night));
    }
}
