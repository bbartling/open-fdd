//! Continuous AFDD scheduling configuration contract.
//!
//! H8 keeps the scheduler policy explicit and provider-neutral. Bulk mode remains
//! the safe default. Continuous mode has an interval that is independent from
//! the rolling lookback window; runtime scheduling consumes this validated
//! contract rather than reparsing environment variables in multiple services.

use std::env;

use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};

pub const DEFAULT_AFDD_INTERVAL_MINUTES: u64 = 60;
pub const DEFAULT_AFDD_LOOKBACK_VALUE: u64 = 24;
pub const DEFAULT_AFDD_LOOKBACK_UNIT: AfddLookbackUnit = AfddLookbackUnit::Hours;

/// Operator UI allowlist: every 1 / 3 / 6 / 12 hours.
pub const OPERATOR_INTERVAL_MINUTES: [u64; 4] = [60, 180, 360, 720];
/// Operator UI allowlist: rolling lookback 1 / 2 / 3 days.
pub const OPERATOR_LOOKBACK_DAYS: [u64; 3] = [1, 2, 3];

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
}

/// Persisted operator overrides (mode stays deployment/env-owned).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AfddOperatorSchedule {
    pub interval_minutes: u64,
    pub lookback_value: u64,
    pub lookback_unit: AfddLookbackUnit,
}

impl Default for AfddConfig {
    fn default() -> Self {
        Self {
            mode: AfddMode::Bulk,
            interval_minutes: DEFAULT_AFDD_INTERVAL_MINUTES,
            lookback_value: DEFAULT_AFDD_LOOKBACK_VALUE,
            lookback_unit: DEFAULT_AFDD_LOOKBACK_UNIT,
        }
    }
}

impl AfddConfig {
    pub fn from_env() -> Result<Self> {
        let mode = env::var("OPENFDD_AFDD_MODE")
            .map(|raw| AfddMode::parse(&raw))
            .unwrap_or(Ok(AfddMode::Bulk))?;
        let interval_minutes = env_positive_u64(
            "OPENFDD_AFDD_INTERVAL_MINUTES",
            DEFAULT_AFDD_INTERVAL_MINUTES,
        )?;
        let lookback_value =
            env_positive_u64("OPENFDD_AFDD_LOOKBACK_VALUE", DEFAULT_AFDD_LOOKBACK_VALUE)?;
        let lookback_unit = env::var("OPENFDD_AFDD_LOOKBACK_UNIT")
            .map(|raw| AfddLookbackUnit::parse(&raw))
            .unwrap_or(Ok(DEFAULT_AFDD_LOOKBACK_UNIT))?;

        let config = Self {
            mode,
            interval_minutes,
            lookback_value,
            lookback_unit,
        };
        config.validate()?;
        Ok(config)
    }

    pub fn validate(&self) -> Result<()> {
        if self.interval_minutes == 0 {
            bail!("OPENFDD_AFDD_INTERVAL_MINUTES must be greater than zero");
        }
        if self.lookback_value == 0 {
            bail!("OPENFDD_AFDD_LOOKBACK_VALUE must be greater than zero");
        }
        self.lookback_seconds()?;
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
        self.validate()
    }

    pub fn operator_schedule(&self) -> AfddOperatorSchedule {
        AfddOperatorSchedule {
            interval_minutes: self.interval_minutes,
            lookback_value: self.lookback_value,
            lookback_unit: self.lookback_unit,
        }
    }
}

impl AfddOperatorSchedule {
    pub fn validate_allowlist(&self) -> Result<()> {
        if !OPERATOR_INTERVAL_MINUTES.contains(&self.interval_minutes) {
            bail!(
                "interval_minutes must be one of {:?} (1/3/6/12 hours)",
                OPERATOR_INTERVAL_MINUTES
            );
        }
        if self.lookback_unit != AfddLookbackUnit::Days
            || !OPERATOR_LOOKBACK_DAYS.contains(&self.lookback_value)
        {
            bail!("lookback must be 1, 2, or 3 days");
        }
        AfddConfig {
            mode: AfddMode::Continuous,
            interval_minutes: self.interval_minutes,
            lookback_value: self.lookback_value,
            lookback_unit: self.lookback_unit,
        }
        .validate()?;
        Ok(())
    }
}

fn env_positive_u64(name: &str, default: u64) -> Result<u64> {
    match env::var(name) {
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
        };
        let schedule = AfddOperatorSchedule {
            interval_minutes: 180,
            lookback_value: 2,
            lookback_unit: AfddLookbackUnit::Days,
        };
        config.apply_operator_schedule(&schedule).unwrap();
        assert_eq!(config.interval_minutes, 180);
        assert_eq!(config.lookback_seconds().unwrap(), 172_800);
    }

    #[test]
    fn operator_schedule_rejects_arbitrary_intervals() {
        let schedule = AfddOperatorSchedule {
            interval_minutes: 15,
            lookback_value: 1,
            lookback_unit: AfddLookbackUnit::Days,
        };
        assert!(schedule.validate_allowlist().is_err());
    }
}
