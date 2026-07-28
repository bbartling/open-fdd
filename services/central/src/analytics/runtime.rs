//! Motor / equipment runtime hours via actual timestamp Δt (not samples × poll).

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;

use super::{envelope, resolve_query_version, AnalyticsEnvelope, AnalyticsRequest, QV_RUNTIME};

/// One runtime boolean sample for inline compute.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RuntimeSample {
    pub equipment_id: String,
    pub timestamp: DateTime<Utc>,
    pub on: bool,
}

/// Per-equipment runtime rollup row.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RuntimeEquipmentRow {
    pub equipment_id: String,
    pub run_hours: f64,
    pub coverage_pct: f64,
    pub samples: u64,
    pub on_samples: u64,
}

/// Integrate on-hours from sorted timestamps using forward Δt with gap clipping.
///
/// For each consecutive pair `(i, i+1)`:
/// - `dt = min(ts[i+1] - ts[i], max_gap_seconds)` (lower-bounded at 0)
/// - if `on[i]` is true, add `dt` to run seconds
/// - always add `dt` to covered elapsed seconds
///
/// The last sample contributes no duration (forward-interval convention).
/// Duplicate timestamps yield `dt = 0` and do not inflate hours.
pub fn compute_runtime_hours(
    timestamps: &[DateTime<Utc>],
    on: &[bool],
    max_gap_seconds: f64,
) -> RuntimeEquipmentRow {
    assert_eq!(
        timestamps.len(),
        on.len(),
        "timestamps and on masks must be same length"
    );
    let n = timestamps.len();
    let samples = n as u64;
    let on_samples = on.iter().filter(|&&b| b).count() as u64;

    if n < 2 {
        return RuntimeEquipmentRow {
            equipment_id: String::new(),
            run_hours: 0.0,
            coverage_pct: 0.0,
            samples,
            on_samples,
        };
    }

    let cap = max_gap_seconds.max(0.0);
    let mut run_secs = 0.0_f64;
    let mut covered_secs = 0.0_f64;

    for i in 0..n - 1 {
        let raw = (timestamps[i + 1] - timestamps[i]).num_milliseconds() as f64 / 1000.0;
        let dt = raw.clamp(0.0, cap);
        covered_secs += dt;
        if on[i] {
            run_secs += dt;
        }
    }

    let span_secs = (timestamps[n - 1] - timestamps[0])
        .num_milliseconds()
        .max(0) as f64
        / 1000.0;
    let coverage_pct = if span_secs > 0.0 {
        100.0 * covered_secs / span_secs
    } else {
        0.0
    };

    RuntimeEquipmentRow {
        equipment_id: String::new(),
        run_hours: run_secs / 3600.0,
        coverage_pct,
        samples,
        on_samples,
    }
}

/// Group inline samples by equipment, sort by timestamp, compute rows.
pub fn compute_runtime_from_samples(
    samples: &[RuntimeSample],
    max_gap_seconds: f64,
) -> Vec<RuntimeEquipmentRow> {
    let mut by_eq: BTreeMap<String, Vec<(DateTime<Utc>, bool)>> = BTreeMap::new();
    for s in samples {
        by_eq
            .entry(s.equipment_id.clone())
            .or_default()
            .push((s.timestamp, s.on));
    }

    let mut rows = Vec::with_capacity(by_eq.len());
    for (eq_id, mut pts) in by_eq {
        pts.sort_by_key(|(ts, _)| *ts);
        let timestamps: Vec<_> = pts.iter().map(|(t, _)| *t).collect();
        let on: Vec<_> = pts.iter().map(|(_, o)| *o).collect();
        let mut row = compute_runtime_hours(&timestamps, &on, max_gap_seconds);
        row.equipment_id = eq_id;
        rows.push(row);
    }
    rows
}

pub fn handle(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    let (qv, mut warnings) = resolve_query_version(req, QV_RUNTIME);
    let max_gap = req.max_gap_seconds.unwrap_or(900.0);
    let mut env = envelope(&qv, &req.query, warnings.clone());

    match &req.samples {
        Some(samples) if !samples.is_empty() => {
            let mut rows = compute_runtime_from_samples(samples, max_gap);
            if let Some(ids) = &req.query.equipment_ids {
                if !ids.is_empty() {
                    rows.retain(|r| ids.contains(&r.equipment_id));
                }
            }
            env.equipment = rows
                .into_iter()
                .map(|r| {
                    json!({
                        "equipment_id": r.equipment_id,
                        "run_hours": round2(r.run_hours),
                        "coverage_pct": round2(r.coverage_pct),
                        "samples": r.samples,
                        "on_samples": r.on_samples,
                    })
                })
                .collect();
            env.rows = env.equipment.clone();
            env.coverage = Some(json!({
                "equipment_count": env.equipment.len(),
                "max_gap_seconds": max_gap,
            }));
        }
        _ => {
            warnings.push(
                "no inline samples provided; historian/job series load for runtime is next".into(),
            );
            env.warnings = warnings;
        }
    }
    env
}

fn round2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn ts(secs: i64) -> DateTime<Utc> {
        Utc.timestamp_opt(secs, 0).unwrap()
    }

    #[test]
    fn regular_five_minute_all_on_one_hour() {
        // t=0..3600 inclusive every 300s → 13 samples, 12 intervals × 300s = 1.0 h
        let timestamps: Vec<_> = (0..=12).map(|i| ts(i * 300)).collect();
        let on = vec![true; timestamps.len()];
        let row = compute_runtime_hours(&timestamps, &on, 900.0);
        assert!((row.run_hours - 1.0).abs() < 1e-9);
        assert_eq!(row.samples, 13);
        assert_eq!(row.on_samples, 13);
        assert!((row.coverage_pct - 100.0).abs() < 1e-6);
    }

    #[test]
    fn gap_clipping_limits_credited_hours() {
        // Two points 1 hour apart, on at first — without clip would be 1.0 h;
        // with max_gap=600s credits only 600/3600 h.
        let timestamps = vec![ts(0), ts(3600)];
        let on = vec![true, false];
        let row = compute_runtime_hours(&timestamps, &on, 600.0);
        assert!((row.run_hours - (600.0 / 3600.0)).abs() < 1e-9);
        // Covered seconds clipped; span is still 3600 → coverage 600/3600*100
        assert!((row.coverage_pct - (600.0 / 3600.0 * 100.0)).abs() < 1e-6);
    }

    #[test]
    fn duplicate_timestamps_do_not_inflate_runtime() {
        let timestamps = vec![ts(0), ts(0), ts(300), ts(300), ts(600)];
        let on = vec![true, true, true, true, true];
        let row = compute_runtime_hours(&timestamps, &on, 900.0);
        // Forward intervals: 0 + 300 + 0 + 300 = 600s = 1/6 h
        assert!((row.run_hours - (600.0 / 3600.0)).abs() < 1e-9);
        assert_eq!(row.samples, 5);
    }

    #[test]
    fn off_intervals_excluded_from_run_hours() {
        let timestamps: Vec<_> = (0..=4).map(|i| ts(i * 300)).collect();
        // on, off, on, off, on — credits intervals 0 and 2 only
        let on = vec![true, false, true, false, true];
        let row = compute_runtime_hours(&timestamps, &on, 900.0);
        assert!((row.run_hours - (600.0 / 3600.0)).abs() < 1e-9);
        assert_eq!(row.on_samples, 3);
    }

    #[test]
    fn handle_groups_by_equipment() {
        let req = AnalyticsRequest {
            samples: Some(vec![
                RuntimeSample {
                    equipment_id: "AHU-1".into(),
                    timestamp: ts(0),
                    on: true,
                },
                RuntimeSample {
                    equipment_id: "AHU-1".into(),
                    timestamp: ts(300),
                    on: true,
                },
                RuntimeSample {
                    equipment_id: "FAN-2".into(),
                    timestamp: ts(0),
                    on: false,
                },
                RuntimeSample {
                    equipment_id: "FAN-2".into(),
                    timestamp: ts(300),
                    on: false,
                },
            ]),
            max_gap_seconds: Some(900.0),
            ..Default::default()
        };
        let env = handle(&req);
        assert_eq!(env.query_version, QV_RUNTIME);
        assert_eq!(env.equipment.len(), 2);
        assert!(env.to_json().get("plotly").is_none());
    }
}
