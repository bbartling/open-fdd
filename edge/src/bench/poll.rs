//! BACnet polling for bench 5007 with live/simulated honesty.

use crate::bench::points::{bench5007_points, BenchPointSpec};
use crate::drivers::bacnet_live;
use crate::historian::bench_telemetry::TelemetrySample;
use chrono::{DateTime, Utc};
use serde_json::Value;
use std::collections::HashMap;

#[derive(Clone, Debug, Default)]
pub struct PollProof {
    pub requests_sent: u64,
    pub responses_received: u64,
    pub last_response_at: Option<DateTime<Utc>>,
    pub source: String,
    pub generated_from_demo_fixture: bool,
    pub simulated: bool,
}

#[derive(Clone, Debug)]
pub struct PollCycleResult {
    pub sample: TelemetrySample,
    pub proof: PollProof,
    pub point_values: HashMap<String, f64>,
}

pub fn is_live_mode() -> bool {
    bacnet_live::is_live_mode()
}

pub fn poll_cycle(
    device_instance: u32,
    poll_cycle_id: u64,
    allow_simulated: bool,
    live_required: bool,
) -> Result<PollCycleResult, String> {
    let live = is_live_mode();
    if live_required && !live {
        return Err(
            "live BACnet required but OPENFDD_BACNET_MODE is not live; set OPENFDD_BACNET_MODE=live or use --allow-simulated for labeled simulated runs".into(),
        );
    }
    if !live && !allow_simulated {
        return Err("simulated BACnet not allowed; pass --allow-simulated for CI/simulated runs".into());
    }

    let mut proof = PollProof {
        source: if live { "real" } else { "simulated" }.to_string(),
        generated_from_demo_fixture: !live,
        simulated: !live,
        ..Default::default()
    };

    let mut values: HashMap<String, f64> = HashMap::new();
    let points: Vec<BenchPointSpec> = bench5007_points()
        .into_iter()
        .filter(|p| p.device_instance == device_instance)
        .collect();

    for point in &points {
        proof.requests_sent += 1;
        let value = if live {
            read_live_point(point)?
        } else {
            read_simulated_point(point, poll_cycle_id)
        };
        proof.responses_received += 1;
        proof.last_response_at = Some(Utc::now());
        values.insert(point.fdd_input.to_string(), value);
    }

    let sample = TelemetrySample {
        ts: Utc::now(),
        device_instance,
        oa_t: values.get("oa-t").copied(),
        oa_h: values.get("oa-h").copied(),
        duct_t: values.get("duct-t").copied(),
        stat_zn_t: values.get("stat_zn-t").copied(),
        source: proof.source.clone(),
        poll_cycle_id,
    };

    Ok(PollCycleResult {
        sample,
        proof,
        point_values: values,
    })
}

fn read_live_point(point: &BenchPointSpec) -> Result<f64, String> {
    let value_json = bacnet_live::block_on(bacnet_live::read_present_value(
        point.device_instance,
        point.object_type,
        point.object_instance,
    ))?;
    json_to_f64(&value_json)
}

fn read_simulated_point(point: &BenchPointSpec, cycle: u64) -> f64 {
    // Small deterministic drift, still ~70°F bench OAT.
    let drift = ((cycle % 5) as f64) * 0.1;
    point.simulated_default + drift
}

fn json_to_f64(value: &Value) -> Result<f64, String> {
    if let Some(v) = value.get("value").and_then(|v| v.as_f64()) {
        return Ok(v);
    }
    value
        .get("present_value")
        .and_then(|v| v.as_f64())
        .ok_or_else(|| "BACnet response missing numeric present-value".to_string())
}

#[derive(Clone, Debug, Default)]
pub struct PollCadenceSummary {
    pub expected_interval_seconds: u64,
    pub tolerance_seconds: i64,
    pub observed_intervals: Vec<i64>,
    pub min_interval_seconds: Option<i64>,
    pub max_interval_seconds: Option<i64>,
    pub avg_interval_seconds: Option<f64>,
    pub missing_intervals: u64,
    pub duplicate_timestamps: u64,
    pub stale_samples: u64,
}

pub fn summarize_poll_cadence(
    poll_times: &[DateTime<Utc>],
    expected_seconds: u64,
    tolerance_seconds: i64,
) -> PollCadenceSummary {
    let mut summary = PollCadenceSummary {
        expected_interval_seconds: expected_seconds,
        tolerance_seconds,
        ..Default::default()
    };

    if poll_times.len() < 2 {
        summary.missing_intervals = if poll_times.is_empty() { 1 } else { 0 };
        return summary;
    }

    let mut sorted = poll_times.to_vec();
    sorted.sort();
    summary.duplicate_timestamps = (sorted.len() as u64).saturating_sub({
        let mut uniq = sorted.clone();
        uniq.dedup();
        uniq.len() as u64
    });

    for w in sorted.windows(2) {
        let delta = (w[1] - w[0]).num_seconds();
        summary.observed_intervals.push(delta);
        let lo = expected_seconds as i64 - tolerance_seconds;
        let hi = expected_seconds as i64 + tolerance_seconds;
        if delta < lo || delta > hi {
            summary.missing_intervals += 1;
        }
        if delta > hi * 2 {
            summary.stale_samples += 1;
        }
    }

    if !summary.observed_intervals.is_empty() {
        summary.min_interval_seconds = summary.observed_intervals.iter().copied().min();
        summary.max_interval_seconds = summary.observed_intervals.iter().copied().max();
        let sum: i64 = summary.observed_intervals.iter().sum();
        summary.avg_interval_seconds =
            Some(sum as f64 / summary.observed_intervals.len() as f64);
    }

    summary
}

pub fn cadence_credible(summary: &PollCadenceSummary) -> bool {
    !summary.observed_intervals.is_empty()
        && summary.missing_intervals == 0
        && summary.duplicate_timestamps == 0
}
