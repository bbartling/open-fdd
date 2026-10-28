//! Weekly occupancy calendar (Overview session parity) for VAV-1 / SCHED overlays.

use anyhow::{Context, Result};
use chrono::{DateTime, Datelike, Timelike, Utc};
use serde_json::Value;
use sqlx::PgConnection;
use sqlx::Row;
use std::fmt;

const WEEKDAYS: [&str; 7] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OccupancyScheduleError {
    pub message: String,
}

impl OccupancyScheduleError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl fmt::Display for OccupancyScheduleError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for OccupancyScheduleError {}

/// Whether the run payload carried a usable site occupancy schedule.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OccupancyScheduleResolution {
    Absent,
    Valid(OccupancySchedule),
    Invalid(OccupancyScheduleError),
}

#[derive(Debug, Clone)]
pub struct DaySchedule {
    pub occupied: bool,
    pub start: String,
    pub end: String,
    start_minutes: u32,
    end_minutes: u32,
}

impl DaySchedule {
    fn from_parts(
        occupied: bool,
        start: String,
        end: String,
    ) -> Result<Self, OccupancyScheduleError> {
        let (sh, sm) = parse_hhmm(&start)
            .map_err(|e| OccupancyScheduleError::new(format!("day start `{start}`: {e}")))?;
        let (eh, em) = parse_hhmm(&end)
            .map_err(|e| OccupancyScheduleError::new(format!("day end `{end}`: {e}")))?;
        Ok(Self {
            occupied,
            start,
            end,
            start_minutes: sh * 60 + sm,
            end_minutes: eh * 60 + em,
        })
    }
}

#[derive(Debug, Clone)]
pub struct OccupancySchedule {
    pub timezone: String,
    pub days: std::collections::HashMap<String, DaySchedule>,
}

/// Parse wall-clock `HH:MM` (one colon, numeric hour 0–23, minute 0–59).
pub fn parse_hhmm(text: &str) -> Result<(u32, u32), OccupancyScheduleError> {
    let s = text.trim();
    if s.is_empty() {
        return Err(OccupancyScheduleError::new(
            "time must be HH:MM, got empty string",
        ));
    }
    let parts: Vec<&str> = s.split(':').collect();
    if parts.len() != 2 {
        return Err(OccupancyScheduleError::new(format!(
            "time must be exactly HH:MM, got `{s}`"
        )));
    }
    let (hour_text, minute_text) = (parts[0], parts[1]);
    if hour_text.is_empty() || minute_text.is_empty() {
        return Err(OccupancyScheduleError::new(format!(
            "time must be exactly HH:MM, got `{s}`"
        )));
    }
    if !hour_text.chars().all(|c| c.is_ascii_digit())
        || !minute_text.chars().all(|c| c.is_ascii_digit())
    {
        return Err(OccupancyScheduleError::new(format!(
            "time must be numeric HH:MM, got `{s}`"
        )));
    }
    let hour: u32 = hour_text
        .parse()
        .map_err(|_| OccupancyScheduleError::new(format!("invalid hour in `{s}`")))?;
    let minute: u32 = minute_text
        .parse()
        .map_err(|_| OccupancyScheduleError::new(format!("invalid minute in `{s}`")))?;
    if hour > 23 {
        return Err(OccupancyScheduleError::new(format!(
            "hour must be 0–23, got {hour} in `{s}`"
        )));
    }
    if minute > 59 {
        return Err(OccupancyScheduleError::new(format!(
            "minute must be 0–59, got {minute} in `{s}`"
        )));
    }
    Ok((hour, minute))
}

impl OccupancySchedule {
    pub fn try_from_json(value: &Value) -> Result<Self, OccupancyScheduleError> {
        let obj = value.as_object().ok_or_else(|| {
            OccupancyScheduleError::new("occupancy_schedule must be a JSON object")
        })?;
        let timezone = obj
            .get("timezone")
            .and_then(Value::as_str)
            .unwrap_or("America/Chicago")
            .to_string();
        timezone
            .parse::<chrono_tz::Tz>()
            .map_err(|_| OccupancyScheduleError::new(format!("invalid timezone `{timezone}`")))?;
        let raw_days = obj.get("days").and_then(Value::as_object);
        let mut days = std::collections::HashMap::new();
        for key in WEEKDAYS {
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
            let day = DaySchedule::from_parts(occupied, start, end)
                .map_err(|e| OccupancyScheduleError::new(format!("{key}: {}", e.message)))?;
            days.insert(key.to_string(), day);
        }
        Ok(Self { timezone, days })
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

    pub fn timestamp_occupied(&self, ts: DateTime<Utc>) -> bool {
        let Ok(tz) = self.timezone.parse::<chrono_tz::Tz>() else {
            return false;
        };
        let local = ts.with_timezone(&tz);
        let key = Self::weekday_key(local.weekday());
        let Some(day) = self.days.get(key) else {
            return false;
        };
        if !day.occupied {
            return false;
        }
        let start_m = day.start_minutes;
        let end_m = day.end_minutes;
        let mins = local.hour() * 60 + local.minute();
        if end_m <= start_m {
            mins >= start_m || mins < end_m
        } else {
            start_m <= mins && mins < end_m
        }
    }
}

pub fn resolve_occupancy_schedule_from_payload(payload: &Value) -> OccupancyScheduleResolution {
    const KEY: &str = "occupancy_schedule";
    for sched in [
        payload.get(KEY),
        payload
            .get("params")
            .and_then(|p| p.get(KEY))
            .or_else(|| payload.get("config").and_then(|c| c.get(KEY))),
    ]
    .into_iter()
    .flatten()
    {
        match OccupancySchedule::try_from_json(sched) {
            Ok(parsed) => return OccupancyScheduleResolution::Valid(parsed),
            Err(err) => return OccupancyScheduleResolution::Invalid(err),
        }
    }
    OccupancyScheduleResolution::Absent
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
        let sched = OccupancySchedule::try_from_json(&serde_json::json!({
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

    #[test]
    fn rejects_malformed_schedule_time() {
        let err = OccupancySchedule::try_from_json(&serde_json::json!({
            "timezone": "UTC",
            "days": {
                "mon": { "occupied": true, "start": "7:xx", "end": "18:00" }
            }
        }))
        .expect_err("malformed start");
        assert!(err.message.contains("7:xx"), "{err}");

        let empty = parse_hhmm("").expect_err("empty");
        assert!(empty.message.contains("empty"), "{empty}");

        let resolution = resolve_occupancy_schedule_from_payload(&serde_json::json!({
            "occupancy_schedule": {
                "timezone": "UTC",
                "days": { "tue": { "occupied": true, "start": "", "end": "18:00" } }
            }
        }));
        assert!(matches!(
            resolution,
            OccupancyScheduleResolution::Invalid(_)
        ));
    }
}
