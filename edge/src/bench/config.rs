//! Bench 5007 DataFusion smoke configuration.

use clap::Parser;
use std::env;

#[derive(Clone, Debug, Parser)]
pub struct SmokeConfig {
    /// Total smoke duration in minutes.
    #[arg(long, default_value_t = 60)]
    pub duration_minutes: u64,

    /// Rule parameter phase length in minutes.
    #[arg(long, default_value_t = 15)]
    pub phase_minutes: u64,

    /// Expected BACnet poll interval in seconds.
    #[arg(long, default_value_t = 60)]
    pub poll_interval_seconds: u64,

    /// Confirmation duration in seconds before fault_confirmed is true.
    #[arg(long, default_value_t = 300)]
    pub confirmation_seconds: i64,

    /// Fault phase high limit (°F).
    #[arg(long, default_value_t = 50.0)]
    pub fault_high_f: f64,

    /// Normal phase high limit (°F).
    #[arg(long, default_value_t = 150.0)]
    pub normal_high_f: f64,

    /// Low limit (°F).
    #[arg(long, default_value_t = -50.0)]
    pub low_f: f64,

    /// FDD input / SQL column base (oa-t -> oa_t).
    #[arg(long, default_value = "oa-t")]
    pub point_fdd_input: String,

    /// BACnet device instance.
    #[arg(long, default_value_t = 5007)]
    pub device_instance: u32,

    /// Require live BACnet; fail if unavailable.
    #[arg(long, default_value_t = true)]
    pub live_required: bool,

    /// Allow simulated BACnet samples (must be labeled in reports).
    #[arg(long, default_value_t = false)]
    pub allow_simulated: bool,

    /// Poll interval tolerance in seconds (±).
    #[arg(long, default_value_t = 20)]
    pub poll_tolerance_seconds: i64,

    /// Output report directory.
    #[arg(long, default_value = "workspace/reports/bench_5007_datafusion_smoke")]
    pub report_dir: String,
}

impl SmokeConfig {
    pub fn from_env_and_cli() -> Self {
        let mut cfg = Self::parse();
        if env::var("OPENFDD_BENCH_5007_LIVE")
            .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
            .unwrap_or(false)
        {
            cfg.live_required = true;
            cfg.allow_simulated = false;
        }
        if let Ok(v) = env::var("OPENFDD_BENCH_DEVICE_INSTANCE") {
            if let Ok(n) = v.parse() {
                cfg.device_instance = n;
            }
        }
        cfg
    }

    pub fn point_column(&self) -> String {
        crate::historian::bench_telemetry::fdd_input_to_column(&self.point_fdd_input)
            .unwrap_or("oa_t")
            .to_string()
    }

    pub fn phase_count(&self) -> u64 {
        if self.phase_minutes == 0 {
            return 1;
        }
        (self.duration_minutes + self.phase_minutes - 1) / self.phase_minutes
    }

    pub fn limits_for_phase_index(&self, phase: u64) -> crate::fdd::datafusion_engine::RuleLimits {
        let fault_phase = phase % 4;
        let high = if fault_phase == 1 || fault_phase == 3 {
            self.fault_high_f
        } else {
            self.normal_high_f
        };
        crate::fdd::datafusion_engine::RuleLimits {
            high_limit: high,
            low_limit: self.low_f,
        }
    }

    pub fn phase_label(phase: u64) -> &'static str {
        match phase % 4 {
            0 => "normal_limits_0_15",
            1 => "fault_limits_15_30",
            2 => "normal_limits_30_45",
            3 => "fault_limits_45_60",
            _ => "unknown",
        }
    }
}
