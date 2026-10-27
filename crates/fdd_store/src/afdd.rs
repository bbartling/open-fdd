//! Continuous AFDD scheduling configuration contract.
//!
//! H8 keeps the scheduler policy explicit and provider-neutral. Bulk mode remains
//! the safe default. Continuous mode has an interval that is independent from
//! the rolling lookback window; runtime scheduling consumes this validated
//! contract rather than reparsing environment variables in multiple services.

use std::collections::BTreeSet;
use std::env;

use anyhow::{bail, Context, Result};
use chrono::{DateTime, NaiveTime, Utc};
use chrono_tz::Tz;
use serde::{Deserialize, Serialize};

pub const DEFAULT_AFDD_INTERVAL_MINUTES: u64 = 60;
pub const DEFAULT_AFDD_LOOKBACK_VALUE: u64 = 24;
pub const DEFAULT_AFDD_LOOKBACK_UNIT: AfddLookbackUnit = AfddLookbackUnit::Hours;

/// Operator UI allowlist: every 1 / 3 / 6 / 12 / 24 hours.
pub const OPERATOR_INTERVAL_MINUTES: [u64; 5] = [60, 180, 360, 720, 1440];
/// Operator UI allowlist: rolling lookback 1 / 2 / 3 days.
pub const OPERATOR_LOOKBACK_DAYS: [u64; 3] = [1, 2, 3];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum AfddScheduleKind {
    /// Next due is `last_completed_at + interval` (or now, when there is no checkpoint).
    #[default]
    Interval,
    /// Next due is a fixed local `HH:MM` in an IANA timezone, once per local day.
    WallClock,
}

impl AfddScheduleKind {
    pub fn parse(raw: &str) -> Result<Self> {
        match raw.trim().to_ascii_lowercase().as_str() {
            "interval" | "continuous_interval" => Ok(Self::Interval),
            "wall_clock" | "wall-clock" | "daily_wall_clock" => Ok(Self::WallClock),
            "all" | "update_all" | "full" | "history" => {
                bail!("AFDD schedule cannot rescan all retained history")
            }
            _ => bail!("OPENFDD_AFDD_SCHEDULE must be 'interval' or 'wall_clock'"),
        }
    }
}

/// `HH:MM` local time for a wall-clock schedule. Rejects unbounded tokens.
pub fn parse_wall_clock_hhmm(raw: &str) -> Result<NaiveTime> {
    let raw = raw.trim();
    if raw.is_empty() || token_is_unbounded_str(raw) {
        bail!("wall-clock time must be HH:MM");
    }
    NaiveTime::parse_from_str(raw, "%H:%M")
        .or_else(|_| NaiveTime::parse_from_str(raw, "%H:%M:%S"))
        .context("wall-clock time must be HH:MM")
}

/// IANA timezone name. Not a site or building id.
pub fn parse_wall_clock_timezone(raw: &str) -> Result<Tz> {
    let raw = raw.trim();
    if raw.is_empty() || token_is_unbounded_str(raw) {
        bail!("wall-clock timezone must be an IANA name");
    }
    raw.parse::<Tz>()
        .map_err(|_| anyhow::anyhow!("unknown IANA timezone '{raw}'"))
}

/// Format a UTC instant in the operator timezone for scheduler status.
pub fn wall_clock_local_rfc3339(utc: DateTime<Utc>, timezone: &str) -> Result<String> {
    let tz = parse_wall_clock_timezone(timezone)?;
    Ok(utc.with_timezone(&tz).to_rfc3339())
}

pub(crate) fn token_is_unbounded_str(raw: &str) -> bool {
    matches!(
        raw.trim().to_ascii_lowercase().as_str(),
        "all" | "*" | "full" | "history" | "retained" | "update_all" | "rescan" | "rescan_all"
    )
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AfddMode {
    Bulk,
    Continuous,
}

impl AfddMode {
    pub fn parse(raw: &str) -> Result<Self> {
        match raw.trim().to_ascii_lowercase().as_str() {
            "bulk" => Ok(Self::Bulk),
            "continuous" => Ok(Self::Continuous),
            _ => bail!("OPENFDD_AFDD_MODE must be 'bulk' or 'continuous'"),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AfddLookbackUnit {
    Minutes,
    Hours,
    Days,
}

impl AfddLookbackUnit {
    pub fn parse(raw: &str) -> Result<Self> {
        match raw.trim().to_ascii_lowercase().as_str() {
            "minute" | "minutes" => Ok(Self::Minutes),
            "hour" | "hours" => Ok(Self::Hours),
            "day" | "days" => Ok(Self::Days),
            _ => bail!("OPENFDD_AFDD_LOOKBACK_UNIT must be minutes, hours, or days"),
        }
    }

    pub fn seconds(self, value: u64) -> Result<u64> {
        let multiplier = match self {
            Self::Minutes => 60,
            Self::Hours => 60 * 60,
            Self::Days => 24 * 60 * 60,
        };
        value
            .checked_mul(multiplier)
            .ok_or_else(|| anyhow::anyhow!("AFDD lookback duration is too large"))
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AfddConfig {
    pub mode: AfddMode,
    pub interval_minutes: u64,
    pub lookback_value: u64,
    pub lookback_unit: AfddLookbackUnit,
    /// How continuous mode picks the next due instant. Default keeps interval cadence.
    #[serde(default)]
    pub schedule_kind: AfddScheduleKind,
    /// Local `HH:MM` when `schedule_kind` is `wall_clock`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub wall_clock_hhmm: Option<String>,
    /// IANA timezone when `schedule_kind` is `wall_clock`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub wall_clock_timezone: Option<String>,
    /// Single-site scope from `OPENFDD_AFDD_BUILDING_ID` (trimmed empty → unset).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub scope_building_id: Option<String>,
    /// Explicit multi-site scope from `OPENFDD_AFDD_BUILDING_IDS` (comma-separated).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub scope_building_ids: Vec<String>,
}

/// Persisted operator overrides (mode stays deployment/env-owned).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AfddOperatorSchedule {
    pub interval_minutes: u64,
    pub lookback_value: u64,
    pub lookback_unit: AfddLookbackUnit,
    #[serde(default)]
    pub schedule_kind: AfddScheduleKind,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub wall_clock_hhmm: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub wall_clock_timezone: Option<String>,
}

impl Default for AfddConfig {
    fn default() -> Self {
        Self {
            mode: AfddMode::Bulk,
            interval_minutes: DEFAULT_AFDD_INTERVAL_MINUTES,
            lookback_value: DEFAULT_AFDD_LOOKBACK_VALUE,
            lookback_unit: DEFAULT_AFDD_LOOKBACK_UNIT,
            schedule_kind: AfddScheduleKind::Interval,
            wall_clock_hhmm: None,
            wall_clock_timezone: None,
            scope_building_id: None,
            scope_building_ids: Vec::new(),
        }
    }
}

impl AfddConfig {
    pub fn from_env() -> Result<Self> {
        let mode = match env_var_nonempty("OPENFDD_AFDD_MODE")? {
            Some(raw) => AfddMode::parse(&raw)?,
            None => AfddMode::Bulk,
        };
        let interval_minutes = env_positive_u64(
            "OPENFDD_AFDD_INTERVAL_MINUTES",
            DEFAULT_AFDD_INTERVAL_MINUTES,
        )?;
        let lookback_value =
            env_positive_u64("OPENFDD_AFDD_LOOKBACK_VALUE", DEFAULT_AFDD_LOOKBACK_VALUE)?;
        let lookback_unit = match env_var_nonempty("OPENFDD_AFDD_LOOKBACK_UNIT")? {
            Some(raw) => AfddLookbackUnit::parse(&raw)?,
            None => DEFAULT_AFDD_LOOKBACK_UNIT,
        };
        let schedule_kind = match env_var_nonempty("OPENFDD_AFDD_SCHEDULE")? {
            Some(raw) => AfddScheduleKind::parse(&raw)?,
            None => AfddScheduleKind::Interval,
        };
        let wall_clock_hhmm = env::var("OPENFDD_AFDD_WALL_CLOCK_HHMM")
            .ok()
            .map(|raw| raw.trim().to_string())
            .filter(|raw| !raw.is_empty());
        let wall_clock_timezone = env::var("OPENFDD_AFDD_WALL_CLOCK_TIMEZONE")
            .ok()
            .map(|raw| raw.trim().to_string())
            .filter(|raw| !raw.is_empty());
        let scope_building_id = env_var_nonempty("OPENFDD_AFDD_BUILDING_ID")?;
        let scope_building_ids =
            parse_scope_building_ids(env_var_nonempty("OPENFDD_AFDD_BUILDING_IDS")?.as_deref())?;

        let config = Self {
            mode,
            interval_minutes,
            lookback_value,
            lookback_unit,
            schedule_kind,
            wall_clock_hhmm,
            wall_clock_timezone,
            scope_building_id,
            scope_building_ids,
        };
        config.validate()?;
        Ok(config)
    }

    /// Scheduled building ids for continuous AFDD.
    ///
    /// When `scope_building_ids` is non-empty it wins over `scope_building_id`.
    /// When both are unset, every id in `known_buildings` is scheduled (sorted).
    /// Each explicit id must appear in `known_buildings` or startup fails closed.
    pub fn resolve_scheduled_buildings(&self, known_buildings: &[String]) -> Result<Vec<String>> {
        let known: BTreeSet<&str> = known_buildings
            .iter()
            .map(|id| id.trim())
            .filter(|id| !id.is_empty())
            .collect();
        if !self.scope_building_ids.is_empty() {
            let mut out = Vec::new();
            for id in &self.scope_building_ids {
                let trimmed = id.trim();
                if trimmed.is_empty() {
                    continue;
                }
                if !known.contains(trimmed) {
                    bail!(
                        "OPENFDD_AFDD_BUILDING_IDS contains unknown building_id '{trimmed}'; known sites: {}",
                        format_known_buildings(&known)
                    );
                }
                if !out.iter().any(|existing: &String| existing == trimmed) {
                    out.push(trimmed.to_string());
                }
            }
            if out.is_empty() {
                bail!("OPENFDD_AFDD_BUILDING_IDS is set but contains no valid building ids");
            }
            out.sort();
            return Ok(out);
        }
        if let Some(single) = self
            .scope_building_id
            .as_deref()
            .map(str::trim)
            .filter(|id| !id.is_empty())
        {
            if !known.contains(single) {
                bail!(
                    "OPENFDD_AFDD_BUILDING_ID '{single}' is not a known site; known sites: {}",
                    format_known_buildings(&known)
                );
            }
            return Ok(vec![single.to_string()]);
        }
        let mut all: Vec<String> = known.iter().map(|id| (*id).to_string()).collect();
        all.sort();
        Ok(all)
    }

    pub fn validate(&self) -> Result<()> {
        if self.interval_minutes == 0 {
            bail!("OPENFDD_AFDD_INTERVAL_MINUTES must be greater than zero");
        }
        if self.lookback_value == 0 {
            bail!("OPENFDD_AFDD_LOOKBACK_VALUE must be greater than zero");
        }
        self.lookback_seconds()?;
        if self.schedule_kind == AfddScheduleKind::WallClock {
            parse_wall_clock_hhmm(self.wall_clock_hhmm.as_deref().unwrap_or(""))?;
            parse_wall_clock_timezone(self.wall_clock_timezone.as_deref().unwrap_or(""))?;
        }
        Ok(())
    }

    pub fn lookback_seconds(&self) -> Result<u64> {
        self.lookback_unit.seconds(self.lookback_value)
    }

    /// Apply operator schedule allowlist (frequency hours + lookback days). Mode unchanged.
    pub fn apply_operator_schedule(&mut self, schedule: &AfddOperatorSchedule) -> Result<()> {
        schedule.validate_allowlist()?;
        self.interval_minutes = schedule.interval_minutes;
        self.lookback_value = schedule.lookback_value;
        self.lookback_unit = schedule.lookback_unit;
        self.schedule_kind = schedule.schedule_kind;
        if schedule.schedule_kind == AfddScheduleKind::WallClock {
            self.wall_clock_hhmm = schedule.wall_clock_hhmm.clone();
            self.wall_clock_timezone = schedule.wall_clock_timezone.clone();
        } else {
            self.wall_clock_hhmm = None;
            self.wall_clock_timezone = None;
        }
        self.validate()
    }

    pub fn operator_schedule(&self) -> AfddOperatorSchedule {
        AfddOperatorSchedule {
            interval_minutes: self.interval_minutes,
            lookback_value: self.lookback_value,
            lookback_unit: self.lookback_unit,
            schedule_kind: self.schedule_kind,
            wall_clock_hhmm: self.wall_clock_hhmm.clone(),
            wall_clock_timezone: self.wall_clock_timezone.clone(),
        }
    }
}

impl AfddOperatorSchedule {
    pub fn validate_allowlist(&self) -> Result<()> {
        if !OPERATOR_INTERVAL_MINUTES.contains(&self.interval_minutes) {
            bail!(
                "interval_minutes must be one of {:?} (1/3/6/12/24 hours)",
                OPERATOR_INTERVAL_MINUTES
            );
        }
        if self.lookback_unit != AfddLookbackUnit::Days
            || !OPERATOR_LOOKBACK_DAYS.contains(&self.lookback_value)
        {
            bail!("lookback must be 1, 2, or 3 days");
        }
        if self.schedule_kind == AfddScheduleKind::WallClock {
            parse_wall_clock_hhmm(self.wall_clock_hhmm.as_deref().unwrap_or(""))?;
            parse_wall_clock_timezone(self.wall_clock_timezone.as_deref().unwrap_or(""))?;
        }
        AfddConfig {
            mode: AfddMode::Continuous,
            interval_minutes: self.interval_minutes,
            lookback_value: self.lookback_value,
            lookback_unit: self.lookback_unit,
            schedule_kind: self.schedule_kind,
            wall_clock_hhmm: self.wall_clock_hhmm.clone(),
            wall_clock_timezone: self.wall_clock_timezone.clone(),
            ..AfddConfig::default()
        }
        .validate()?;
        Ok(())
    }
}

/// Compose `${VAR:-}` forwards unset names as empty strings; treat those as absent.
fn env_var_nonempty(name: &str) -> Result<Option<String>> {
    match env::var(name) {
        Ok(raw) if raw.trim().is_empty() => Ok(None),
        Ok(raw) => Ok(Some(raw)),
        Err(env::VarError::NotPresent) => Ok(None),
        Err(err) => Err(err).with_context(|| format!("read {name}")),
    }
}

fn parse_scope_building_ids(raw: Option<&str>) -> Result<Vec<String>> {
    let Some(raw) = raw.map(str::trim).filter(|value| !value.is_empty()) else {
        return Ok(Vec::new());
    };
    let mut out = Vec::new();
    for part in raw.split(',') {
        let id = part.trim();
        if id.is_empty() {
            continue;
        }
        if !out.iter().any(|existing| existing == id) {
            out.push(id.to_string());
        }
    }
    Ok(out)
}

fn format_known_buildings(known: &BTreeSet<&str>) -> String {
    if known.is_empty() {
        return "(none)".into();
    }
    known.iter().copied().collect::<Vec<_>>().join(", ")
}

fn env_positive_u64(name: &str, default: u64) -> Result<u64> {
    match env::var(name) {
        Ok(raw) if raw.trim().is_empty() => Ok(default),
        Ok(raw) => raw
            .parse::<u64>()
            .with_context(|| format!("{name} must be a positive integer"))
            .and_then(|value| {
                if value == 0 {
                    bail!("{name} must be greater than zero");
                }
                Ok(value)
            }),
        Err(env::VarError::NotPresent) => Ok(default),
        Err(err) => Err(err).with_context(|| format!("read {name}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bulk_is_safe_default() {
        assert_eq!(AfddConfig::default().mode, AfddMode::Bulk);
    }

    #[test]
    fn mode_parser_is_strict() {
        assert_eq!(AfddMode::parse("bulk").unwrap(), AfddMode::Bulk);
        assert_eq!(AfddMode::parse("CONTINUOUS").unwrap(), AfddMode::Continuous);
        assert!(AfddMode::parse("scheduled").is_err());
    }

    #[test]
    fn empty_compose_forwarded_afdd_env_uses_defaults() {
        let keys = [
            "OPENFDD_AFDD_MODE",
            "OPENFDD_AFDD_INTERVAL_MINUTES",
            "OPENFDD_AFDD_LOOKBACK_VALUE",
            "OPENFDD_AFDD_LOOKBACK_UNIT",
            "OPENFDD_AFDD_SCHEDULE",
            "OPENFDD_AFDD_BUILDING_ID",
            "OPENFDD_AFDD_BUILDING_IDS",
        ];
        let saved: Vec<(String, Option<String>)> = keys
            .iter()
            .map(|key| (key.to_string(), env::var(key).ok()))
            .collect();
        for key in keys {
            env::set_var(key, "");
        }
        let config = AfddConfig::from_env().expect("empty forwarded vars must not fail startup");
        assert_eq!(config.mode, AfddMode::Bulk);
        assert_eq!(config.interval_minutes, DEFAULT_AFDD_INTERVAL_MINUTES);
        assert_eq!(config.lookback_value, DEFAULT_AFDD_LOOKBACK_VALUE);
        assert_eq!(config.lookback_unit, DEFAULT_AFDD_LOOKBACK_UNIT);
        assert!(config.scope_building_id.is_none());
        assert!(config.scope_building_ids.is_empty());
        for (key, value) in saved {
            match value {
                Some(v) => env::set_var(&key, v),
                None => env::remove_var(&key),
            }
        }
    }

    #[test]
    fn lookback_unit_parser_and_seconds_are_explicit() {
        assert_eq!(
            AfddLookbackUnit::parse("hours").unwrap(),
            AfddLookbackUnit::Hours
        );
        assert_eq!(AfddLookbackUnit::Hours.seconds(24).unwrap(), 86_400);
        assert_eq!(AfddLookbackUnit::Days.seconds(2).unwrap(), 172_800);
        assert!(AfddLookbackUnit::parse("weeks").is_err());
    }

    #[test]
    fn interval_and_lookback_are_independent() {
        let config = AfddConfig {
            mode: AfddMode::Continuous,
            interval_minutes: 15,
            lookback_value: 48,
            lookback_unit: AfddLookbackUnit::Hours,
            ..AfddConfig::default()
        };
        config.validate().unwrap();
        assert_eq!(config.interval_minutes, 15);
        assert_eq!(config.lookback_seconds().unwrap(), 172_800);
    }

    #[test]
    fn zero_values_fail_closed() {
        let zero_interval = AfddConfig {
            interval_minutes: 0,
            ..AfddConfig::default()
        };
        assert!(zero_interval.validate().is_err());

        let zero_lookback = AfddConfig {
            lookback_value: 0,
            ..AfddConfig::default()
        };
        assert!(zero_lookback.validate().is_err());
    }

    #[test]
    fn operator_schedule_allowlist_accepts_hours_and_days() {
        let mut config = AfddConfig {
            mode: AfddMode::Continuous,
            interval_minutes: 60,
            lookback_value: 24,
            lookback_unit: AfddLookbackUnit::Hours,
            ..AfddConfig::default()
        };
        let schedule = AfddOperatorSchedule {
            interval_minutes: 180,
            lookback_value: 2,
            lookback_unit: AfddLookbackUnit::Days,
            schedule_kind: AfddScheduleKind::Interval,
            wall_clock_hhmm: None,
            wall_clock_timezone: None,
        };
        config.apply_operator_schedule(&schedule).unwrap();
        assert_eq!(config.interval_minutes, 180);
        assert_eq!(config.lookback_seconds().unwrap(), 172_800);
    }

    #[test]
    fn operator_schedule_accepts_daily_interval() {
        let schedule = AfddOperatorSchedule {
            interval_minutes: 1440,
            lookback_value: 1,
            lookback_unit: AfddLookbackUnit::Days,
            schedule_kind: AfddScheduleKind::Interval,
            wall_clock_hhmm: None,
            wall_clock_timezone: None,
        };
        schedule.validate_allowlist().unwrap();
    }

    #[test]
    fn operator_schedule_rejects_arbitrary_intervals() {
        let schedule = AfddOperatorSchedule {
            interval_minutes: 15,
            lookback_value: 1,
            lookback_unit: AfddLookbackUnit::Days,
            schedule_kind: AfddScheduleKind::Interval,
            wall_clock_hhmm: None,
            wall_clock_timezone: None,
        };
        assert!(schedule.validate_allowlist().is_err());
    }

    #[test]
    fn legacy_config_json_stays_interval() {
        let cfg: AfddConfig = serde_json::from_str(
            r#"{"mode":"continuous","interval_minutes":60,"lookback_value":24,"lookback_unit":"hours"}"#,
        )
        .unwrap();
        assert_eq!(cfg.schedule_kind, AfddScheduleKind::Interval);
        assert!(cfg.wall_clock_hhmm.is_none());
        cfg.validate().unwrap();
    }

    #[test]
    fn wall_clock_requires_hhmm_and_iana_timezone() {
        let missing = AfddConfig {
            schedule_kind: AfddScheduleKind::WallClock,
            ..AfddConfig::default()
        };
        assert!(missing.validate().is_err());

        let unknown_tz = AfddConfig {
            schedule_kind: AfddScheduleKind::WallClock,
            wall_clock_hhmm: Some("05:00".into()),
            wall_clock_timezone: Some("Not/AZone".into()),
            ..AfddConfig::default()
        };
        assert!(unknown_tz.validate().is_err());

        let ok = AfddConfig {
            mode: AfddMode::Continuous,
            interval_minutes: 1440,
            lookback_value: 24,
            lookback_unit: AfddLookbackUnit::Hours,
            schedule_kind: AfddScheduleKind::WallClock,
            wall_clock_hhmm: Some("05:00".into()),
            wall_clock_timezone: Some("America/Chicago".into()),
            ..AfddConfig::default()
        };
        ok.validate().unwrap();
        assert_eq!(
            AfddScheduleKind::parse("wall_clock").unwrap(),
            AfddScheduleKind::WallClock
        );
        assert!(AfddScheduleKind::parse("all").is_err());
    }

    #[test]
    fn operator_wall_clock_allowlist_accepts_daily_local_time() {
        let schedule = AfddOperatorSchedule {
            interval_minutes: 1440,
            lookback_value: 1,
            lookback_unit: AfddLookbackUnit::Days,
            schedule_kind: AfddScheduleKind::WallClock,
            wall_clock_hhmm: Some("05:00".into()),
            wall_clock_timezone: Some("America/Chicago".into()),
        };
        schedule.validate_allowlist().unwrap();
    }

    #[test]
    fn scope_all_uses_known_buildings_sorted() {
        let config = AfddConfig::default();
        let sites = config
            .resolve_scheduled_buildings(&["site-c".into(), "site-a".into(), "site-b".into()])
            .unwrap();
        assert_eq!(sites, vec!["site-a", "site-b", "site-c"]);
    }

    #[test]
    fn explicit_building_ids_select_subset_and_reject_unknown() {
        let config = AfddConfig {
            scope_building_ids: vec!["site-b".into(), "site-a".into(), "site-b".into()],
            ..AfddConfig::default()
        };
        let sites = config
            .resolve_scheduled_buildings(&["site-a".into(), "site-b".into(), "site-c".into()])
            .unwrap();
        assert_eq!(sites, vec!["site-a", "site-b"]);
        let bad = AfddConfig {
            scope_building_ids: vec!["missing".into()],
            ..AfddConfig::default()
        };
        assert!(bad
            .resolve_scheduled_buildings(&["site-a".into()])
            .unwrap_err()
            .to_string()
            .contains("unknown building_id"));
    }

    #[test]
    fn single_scope_building_id_overrides_when_list_empty() {
        let config = AfddConfig {
            scope_building_id: Some("site-b".into()),
            ..AfddConfig::default()
        };
        let sites = config
            .resolve_scheduled_buildings(&["site-a".into(), "site-b".into()])
            .unwrap();
        assert_eq!(sites, vec!["site-b"]);
    }
}
