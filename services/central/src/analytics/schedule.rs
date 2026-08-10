//! Schedule / occupancy hours — occupied mask + optional after-hours fan hours.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::json;

use super::{
    envelope, finalize_historian, historian, resolve_query_version, AnalyticsEnvelope,
    AnalyticsRequest, QV_SCHEDULE,
};

/// Occupied-mask sample (boolean occupancy at a timestamp).
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct OccupiedSample {
    pub timestamp: DateTime<Utc>,
    pub occupied: bool,
}

/// Optional fan status sample aligned to the same timeline (or nearby).
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct FanSample {
    pub timestamp: DateTime<Utc>,
    pub fan_on: bool,
    #[serde(default)]
    pub equipment_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ScheduleRollup {
    pub occupied_hours: f64,
    pub unoccupied_hours: f64,
    pub coverage_hours: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub after_hours_fan_hours: Option<f64>,
    pub occupied_samples: u64,
    pub total_samples: u64,
}

/// Integrate occupied / unoccupied hours from sorted occupied mask via forward Δt.
///
/// Gap clipping mirrors runtime: `dt = min(ts[i+1]-ts[i], max_gap_seconds)`.
pub fn compute_occupied_hours(occupied: &[OccupiedSample], max_gap_seconds: f64) -> ScheduleRollup {
    let mut pts = occupied.to_vec();
    pts.sort_by_key(|p| p.timestamp);
    let n = pts.len();
    let occupied_samples = pts.iter().filter(|p| p.occupied).count() as u64;
    if n < 2 {
        return ScheduleRollup {
            occupied_hours: 0.0,
            unoccupied_hours: 0.0,
            coverage_hours: 0.0,
            after_hours_fan_hours: None,
            occupied_samples,
            total_samples: n as u64,
        };
    }

    let cap = max_gap_seconds.max(0.0);
    let mut occ_secs = 0.0_f64;
    let mut unocc_secs = 0.0_f64;
    for i in 0..n - 1 {
        let raw = (pts[i + 1].timestamp - pts[i].timestamp).num_milliseconds() as f64 / 1000.0;
        let dt = raw.clamp(0.0, cap);
        if pts[i].occupied {
            occ_secs += dt;
        } else {
            unocc_secs += dt;
        }
    }

    ScheduleRollup {
        occupied_hours: occ_secs / 3600.0,
        unoccupied_hours: unocc_secs / 3600.0,
        coverage_hours: (occ_secs + unocc_secs) / 3600.0,
        after_hours_fan_hours: None,
        occupied_samples,
        total_samples: n as u64,
    }
}

/// After-hours fan hours: intervals where fan is on and occupancy is false.
///
/// For each consecutive fan sample pair, look up occupancy at the start of the
/// interval (last occupied mask sample with `ts <= fan_ts`, else nearest).
pub fn compute_after_hours_fan_hours(
    occupied: &[OccupiedSample],
    fan: &[FanSample],
    max_gap_seconds: f64,
) -> f64 {
    if occupied.is_empty() || fan.len() < 2 {
        return 0.0;
    }
    let mut occ = occupied.to_vec();
    occ.sort_by_key(|p| p.timestamp);
    let mut fans = fan.to_vec();
    fans.sort_by_key(|p| p.timestamp);

    let cap = max_gap_seconds.max(0.0);
    let mut secs = 0.0_f64;
    for i in 0..fans.len() - 1 {
        if !fans[i].fan_on {
            continue;
        }
        let raw = (fans[i + 1].timestamp - fans[i].timestamp).num_milliseconds() as f64 / 1000.0;
        let dt = raw.clamp(0.0, cap);
        let is_occ = occupancy_at(&occ, fans[i].timestamp);
        if !is_occ {
            secs += dt;
        }
    }
    secs / 3600.0
}

fn occupancy_at(occupied: &[OccupiedSample], ts: DateTime<Utc>) -> bool {
    // Last sample at or before ts; if none, use first sample.
    match occupied.iter().rfind(|p| p.timestamp <= ts) {
        Some(p) => p.occupied,
        None => occupied.first().map(|p| p.occupied).unwrap_or(false),
    }
}

pub fn handle(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    let (qv, mut warnings) = resolve_query_version(req, QV_SCHEDULE);
    let max_gap = req.max_gap_seconds.unwrap_or(900.0);
    let mut env = envelope(&qv, &req.query, warnings.clone());

    let (occ, fan) = parse_series(req);
    match occ {
        Some(occupied) if !occupied.is_empty() => {
            let mut rollup = compute_occupied_hours(&occupied, max_gap);
            if let Some(fan_samples) = fan {
                if !fan_samples.is_empty() {
                    let ah = compute_after_hours_fan_hours(&occupied, &fan_samples, max_gap);
                    rollup.after_hours_fan_hours = Some(round4(ah));
                }
            }
            rollup.occupied_hours = round4(rollup.occupied_hours);
            rollup.unoccupied_hours = round4(rollup.unoccupied_hours);
            rollup.coverage_hours = round4(rollup.coverage_hours);

            let row = serde_json::to_value(&rollup).unwrap_or(json!({}));
            env.rows = vec![row.clone()];
            env.equipment = vec![row];
            env.coverage = Some(json!({
                "max_gap_seconds": max_gap,
                "occupied_samples": rollup.occupied_samples,
                "total_samples": rollup.total_samples,
            }));
            warnings.push(
                "schedule: minimal central-analytics-v1 occupied-mask integration (not full DF port)"
                    .into(),
            );
            env.warnings = warnings;
        }
        _ => {
            warnings.push(
                "no inline occupied mask provided; historian/job schedule load is next".into(),
            );
            env.warnings = warnings;
        }
    }
    env
}

/// Async handler: prefer historian DataFusion occupied-mask Δt integration when
/// no inline series is provided and `occ_mode` exists; else inline central path.
pub async fn handle_async(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    if req.series.is_none() {
        let max_gap = req.max_gap_seconds.unwrap_or(900.0);
        match historian::schedule_from_history(
            req.query.equipment_ids.as_deref(),
            max_gap,
            req.query.building_id.as_deref(),
        )
        .await
        {
            Ok(Some(env)) => return finalize_historian(req, env, QV_SCHEDULE),
            Ok(None) => {}
            Err(e) => {
                tracing::warn!(error = %e, "historian schedule path failed; using inline/empty fallback");
            }
        }
    }
    handle(req)
}

fn parse_series(req: &AnalyticsRequest) -> (Option<Vec<OccupiedSample>>, Option<Vec<FanSample>>) {
    let Some(series) = req.series.as_ref() else {
        return (None, None);
    };

    let occ_arr = series
        .get("occupied")
        .and_then(|v| v.as_array())
        .or_else(|| series.get("points").and_then(|v| v.as_array()))
        .or_else(|| series.as_array());

    let occupied = occ_arr.map(|arr| {
        arr.iter()
            .filter_map(|v| serde_json::from_value::<OccupiedSample>(v.clone()).ok())
            .collect::<Vec<_>>()
    });

    let fan = series.get("fan").and_then(|v| v.as_array()).map(|arr| {
        arr.iter()
            .filter_map(|v| serde_json::from_value::<FanSample>(v.clone()).ok())
            .collect::<Vec<_>>()
    });

    (occupied, fan)
}

fn round4(x: f64) -> f64 {
    (x * 10_000.0).round() / 10_000.0
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn ts(secs: i64) -> DateTime<Utc> {
        Utc.timestamp_opt(secs, 0).unwrap()
    }

    #[test]
    fn occupied_hours_from_mask() {
        // 0–3600 occupied, 3600–7200 unoccupied → 1.0 h each
        let occ = vec![
            OccupiedSample {
                timestamp: ts(0),
                occupied: true,
            },
            OccupiedSample {
                timestamp: ts(3600),
                occupied: false,
            },
            OccupiedSample {
                timestamp: ts(7200),
                occupied: false,
            },
        ];
        let r = compute_occupied_hours(&occ, 9000.0);
        assert!((r.occupied_hours - 1.0).abs() < 1e-9);
        assert!((r.unoccupied_hours - 1.0).abs() < 1e-9);
    }

    #[test]
    fn after_hours_fan_when_unoccupied() {
        let occ = vec![
            OccupiedSample {
                timestamp: ts(0),
                occupied: false,
            },
            OccupiedSample {
                timestamp: ts(3600),
                occupied: false,
            },
        ];
        let fan = vec![
            FanSample {
                timestamp: ts(0),
                fan_on: true,
                equipment_id: Some("AHU-1".into()),
            },
            FanSample {
                timestamp: ts(1800),
                fan_on: true,
                equipment_id: Some("AHU-1".into()),
            },
        ];
        let ah = compute_after_hours_fan_hours(&occ, &fan, 9000.0);
        assert!((ah - 0.5).abs() < 1e-9);
    }

    #[test]
    fn handle_with_fan_series() {
        let req = AnalyticsRequest {
            series: Some(json!({
                "occupied": [
                    {"timestamp": "2024-01-01T00:00:00Z", "occupied": false},
                    {"timestamp": "2024-01-01T01:00:00Z", "occupied": false}
                ],
                "fan": [
                    {"timestamp": "2024-01-01T00:00:00Z", "fan_on": true},
                    {"timestamp": "2024-01-01T01:00:00Z", "fan_on": false}
                ]
            })),
            max_gap_seconds: Some(7200.0),
            ..Default::default()
        };
        let env = handle(&req);
        assert_eq!(env.query_version, QV_SCHEDULE);
        assert_eq!(env.rows.len(), 1);
        assert!(env.rows[0].get("after_hours_fan_hours").is_some());
    }
}
