//! Sensor health matrix — per-series coverage, flatline, missingness, stats.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::collections::BTreeMap;

use super::{
    envelope, finalize_historian, historian, resolve_query_version, AnalyticsEnvelope,
    AnalyticsRequest, QV_SENSOR_HEALTH,
};

/// Default minimum sample count before flatline flag can fire.
pub const DEFAULT_FLATLINE_MIN_N: usize = 5;
/// Std-dev below this (and n > min_n) → flatline.
pub const DEFAULT_FLATLINE_STD_EPS: f64 = 1e-9;

/// One sensor series sample for inline compute.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SensorPoint {
    pub equipment_id: String,
    pub role: String,
    pub timestamp: DateTime<Utc>,
    /// Null / missing values may be omitted or sent as JSON null (parsed as None).
    #[serde(default)]
    pub value: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SensorSeriesRow {
    pub equipment_id: String,
    pub role: String,
    pub n: u64,
    pub n_finite: u64,
    pub coverage_pct: f64,
    pub missingness: f64,
    pub flatline_flag: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub min: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mean: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub std: Option<f64>,
}

/// Compute per-(equipment_id, role) health stats from inline points.
pub fn compute_sensor_health(
    points: &[SensorPoint],
    flatline_min_n: usize,
    flatline_std_eps: f64,
) -> Vec<SensorSeriesRow> {
    let mut by_key: BTreeMap<(String, String), Vec<Option<f64>>> = BTreeMap::new();
    for p in points {
        by_key
            .entry((p.equipment_id.clone(), p.role.clone()))
            .or_default()
            .push(p.value.filter(|v| v.is_finite()));
    }

    let mut rows = Vec::with_capacity(by_key.len());
    for ((equipment_id, role), vals) in by_key {
        let n = vals.len() as u64;
        let finite: Vec<f64> = vals.into_iter().flatten().collect();
        let n_finite = finite.len() as u64;
        let coverage_pct = if n > 0 {
            100.0 * n_finite as f64 / n as f64
        } else {
            0.0
        };
        let missingness = if n > 0 {
            1.0 - (n_finite as f64 / n as f64)
        } else {
            0.0
        };

        let (min, max, mean, std) = if finite.is_empty() {
            (None, None, None, None)
        } else {
            let min_v = finite.iter().copied().fold(f64::INFINITY, f64::min);
            let max_v = finite.iter().copied().fold(f64::NEG_INFINITY, f64::max);
            let mean_v = finite.iter().sum::<f64>() / finite.len() as f64;
            let var = if finite.len() > 1 {
                finite
                    .iter()
                    .map(|v| {
                        let d = v - mean_v;
                        d * d
                    })
                    .sum::<f64>()
                    / (finite.len() as f64)
            } else {
                0.0
            };
            let std_v = var.sqrt();
            (
                Some(round4(min_v)),
                Some(round4(max_v)),
                Some(round4(mean_v)),
                Some(round6(std_v)),
            )
        };

        let flatline_flag = n_finite as usize > flatline_min_n
            && std.map(|s| s <= flatline_std_eps).unwrap_or(false);

        rows.push(SensorSeriesRow {
            equipment_id,
            role,
            n,
            n_finite,
            coverage_pct: round2(coverage_pct),
            missingness: round4(missingness),
            flatline_flag,
            min,
            max,
            mean,
            std,
        });
    }
    rows
}

pub fn handle(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    let (qv, mut warnings) = resolve_query_version(req, QV_SENSOR_HEALTH);
    let mut env = envelope(&qv, &req.query, warnings.clone());

    let points = parse_points(req);
    match points {
        Some(pts) if !pts.is_empty() => {
            let mut filtered = pts;
            if let Some(ids) = &req.query.equipment_ids {
                if !ids.is_empty() {
                    filtered.retain(|p| ids.contains(&p.equipment_id));
                }
            }
            let rows =
                compute_sensor_health(&filtered, DEFAULT_FLATLINE_MIN_N, DEFAULT_FLATLINE_STD_EPS);
            env.rows = rows
                .iter()
                .map(|r| serde_json::to_value(r).unwrap_or(json!({})))
                .collect();
            env.equipment = env.rows.clone();
            env.coverage = Some(json!({
                "series_count": env.rows.len(),
                "point_count": filtered.len(),
            }));
            warnings.push(
                "sensor_health: minimal central-analytics-v1 stats (not full DF MemTable port)"
                    .into(),
            );
            env.warnings = warnings;
        }
        _ => {
            warnings.push(
                "no inline series points provided; historian/job sensor-health load is next".into(),
            );
            env.warnings = warnings;
        }
    }
    env
}

/// Async handler: prefer historian DataFusion aggregate SQL when no inline
/// series is provided; otherwise inline central-analytics-v1 compute.
pub async fn handle_async(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    if req.series.is_none() {
        match historian::sensor_health_from_history(
            req.query.equipment_ids.as_deref(),
            req.query.building_id.as_deref(),
        )
        .await
        {
            Ok(Some(env)) => return finalize_historian(req, env, QV_SENSOR_HEALTH),
            Ok(None) => {}
            Err(e) => {
                tracing::warn!(error = %e, "historian sensor_health path failed; using inline/empty fallback");
            }
        }
    }
    handle(req)
}

fn parse_points(req: &AnalyticsRequest) -> Option<Vec<SensorPoint>> {
    let series = req.series.as_ref()?;
    let arr = if let Some(a) = series.as_array() {
        a.clone()
    } else if let Some(a) = series.get("points").and_then(|v| v.as_array()) {
        a.clone()
    } else {
        return None;
    };
    let mut out = Vec::new();
    for v in arr {
        if let Ok(p) = serde_json::from_value::<SensorPoint>(v) {
            out.push(p);
        }
    }
    Some(out)
}

fn round2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}
fn round4(x: f64) -> f64 {
    (x * 10_000.0).round() / 10_000.0
}
fn round6(x: f64) -> f64 {
    (x * 1_000_000.0).round() / 1_000_000.0
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn ts(secs: i64) -> DateTime<Utc> {
        Utc.timestamp_opt(secs, 0).unwrap()
    }

    fn pt(eq: &str, role: &str, t: i64, v: Option<f64>) -> SensorPoint {
        SensorPoint {
            equipment_id: eq.into(),
            role: role.into(),
            timestamp: ts(t),
            value: v,
        }
    }

    #[test]
    fn coverage_and_stats_for_varied_series() {
        let pts = vec![
            pt("AHU-1", "sat", 0, Some(55.0)),
            pt("AHU-1", "sat", 300, Some(56.0)),
            pt("AHU-1", "sat", 600, Some(54.0)),
            pt("AHU-1", "sat", 900, None),
        ];
        let rows = compute_sensor_health(&pts, 5, 1e-9);
        assert_eq!(rows.len(), 1);
        let r = &rows[0];
        assert_eq!(r.n, 4);
        assert_eq!(r.n_finite, 3);
        assert!((r.coverage_pct - 75.0).abs() < 1e-9);
        assert!((r.missingness - 0.25).abs() < 1e-9);
        assert!(!r.flatline_flag);
        assert_eq!(r.min, Some(54.0));
        assert_eq!(r.max, Some(56.0));
        assert!((r.mean.unwrap() - 55.0).abs() < 1e-9);
    }

    #[test]
    fn flatline_when_std_near_zero_and_n_gt_min() {
        let pts: Vec<_> = (0..8)
            .map(|i| pt("SEN-1", "zone_t", i * 300, Some(72.0)))
            .collect();
        let rows = compute_sensor_health(&pts, 5, 1e-9);
        assert!(rows[0].flatline_flag);
        assert_eq!(rows[0].std, Some(0.0));
    }

    #[test]
    fn no_flatline_when_n_le_min() {
        let pts: Vec<_> = (0..4)
            .map(|i| pt("SEN-1", "zone_t", i * 300, Some(72.0)))
            .collect();
        let rows = compute_sensor_health(&pts, 5, 1e-9);
        assert!(!rows[0].flatline_flag);
    }

    #[test]
    fn handle_groups_series() {
        let req = AnalyticsRequest {
            series: Some(json!({
                "points": [
                    {"equipment_id": "AHU-1", "role": "sat", "timestamp": "2024-01-01T00:00:00Z", "value": 55.0},
                    {"equipment_id": "AHU-1", "role": "mat", "timestamp": "2024-01-01T00:00:00Z", "value": 60.0}
                ]
            })),
            ..Default::default()
        };
        let env = handle(&req);
        assert_eq!(env.query_version, QV_SENSOR_HEALTH);
        assert_eq!(env.rows.len(), 2);
        assert_eq!(env.engine, super::super::ENGINE);
    }
}
