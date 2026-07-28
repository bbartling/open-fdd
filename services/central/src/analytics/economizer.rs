//! AHU free-cooling economizer diagnostics (Guideline 36–aligned mixing).

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::json;

use super::{envelope, resolve_query_version, AnalyticsEnvelope, AnalyticsRequest, QV_ECONOMIZER};

pub const DEFAULT_DT_MIN_F: f64 = 10.0;

/// One mixed-air diagnostic sample.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct EconomizerPointIn {
    pub equipment_id: String,
    #[serde(default)]
    pub equipment_type: Option<String>,
    pub timestamp: DateTime<Utc>,
    pub oat_f: f64,
    pub rat_f: f64,
    pub mat_f: f64,
    #[serde(default)]
    pub sat_f: Option<f64>,
    pub fan_on: bool,
    /// OA damper feedback, percent 0–100 (optional).
    #[serde(default)]
    pub oa_damper_pct: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EconomizerPointOut {
    pub timestamp: DateTime<Utc>,
    pub equipment_id: String,
    pub equipment_type: String,
    pub oat_f: f64,
    pub rat_f: f64,
    pub mat_f: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sat_f: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub damper_fb_pct: Option<f64>,
    pub fan_on: bool,
    pub delta_or_f: f64,
    pub delta_mr_f: f64,
    pub identifiable: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub oa_frac_temp_pct: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mat_pred_f: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mat_resid_f: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EconomizerMetrics {
    pub equipment_id: String,
    pub equipment_type: String,
    pub n_fan_on_samples: u64,
    pub n_identifiable: u64,
    pub has_damper: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub median_mat_resid_f: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mat_resid_mae_f: Option<f64>,
    pub dt_min_f: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EconomizerSkipped {
    pub equipment_id: String,
    pub reason: String,
}

#[derive(Debug, Clone)]
pub struct EconomizerResult {
    pub metrics: Vec<EconomizerMetrics>,
    pub points: Vec<EconomizerPointOut>,
    pub skipped: Vec<EconomizerSkipped>,
}

/// Compute economizer diagnostics from inline points.
///
/// - Fan-on gate: only `fan_on == true` rows contribute points.
/// - Equipment with no fan-on rows → skipped (`no_fan_on_rows`).
/// - Identifiable when `|OAT−RAT| >= dt_min_f`.
/// - OA fraction (%) = `100 * (MAT−RAT) / (OAT−RAT)` when identifiable.
/// - MAT residual when damper present: `MAT − (RAT + damper_frac * (OAT−RAT))`.
pub fn compute_economizer_diagnostics(
    points: &[EconomizerPointIn],
    dt_min_f: f64,
    max_points_per_eq: usize,
) -> EconomizerResult {
    use std::collections::BTreeMap;

    let mut by_eq: BTreeMap<String, Vec<&EconomizerPointIn>> = BTreeMap::new();
    for p in points {
        by_eq.entry(p.equipment_id.clone()).or_default().push(p);
    }

    let mut metrics = Vec::new();
    let mut out_points = Vec::new();
    let mut skipped = Vec::new();
    let dt_min = dt_min_f.max(0.0);

    for (eq_id, pts) in by_eq {
        let fan_on_pts: Vec<_> = pts.iter().copied().filter(|p| p.fan_on).collect();
        if fan_on_pts.is_empty() {
            skipped.push(EconomizerSkipped {
                equipment_id: eq_id,
                reason: "no_fan_on_rows".into(),
            });
            continue;
        }

        let et = fan_on_pts
            .first()
            .and_then(|p| p.equipment_type.clone())
            .unwrap_or_else(|| "AHU".into());
        let has_damper = fan_on_pts.iter().any(|p| p.oa_damper_pct.is_some());

        let mut eq_points = Vec::with_capacity(fan_on_pts.len());
        let mut resid_vals: Vec<f64> = Vec::new();
        let mut n_ident = 0_u64;

        for p in &fan_on_pts {
            let delta_or = p.oat_f - p.rat_f;
            let delta_mr = p.mat_f - p.rat_f;
            let identifiable = delta_or.abs() >= dt_min;
            if identifiable {
                n_ident += 1;
            }

            let oa_frac = if identifiable && delta_or.abs() > 1e-12 {
                Some((100.0 * delta_mr / delta_or).clamp(-20.0, 120.0))
            } else {
                None
            };

            let (mat_pred, mat_resid) = match p.oa_damper_pct {
                Some(damp) => {
                    let pred = p.rat_f + (damp / 100.0) * delta_or;
                    let resid = p.mat_f - pred;
                    if identifiable {
                        resid_vals.push(resid);
                    }
                    (Some(pred), Some(resid))
                }
                None => (None, None),
            };

            eq_points.push(EconomizerPointOut {
                timestamp: p.timestamp,
                equipment_id: eq_id.clone(),
                equipment_type: et.clone(),
                oat_f: p.oat_f,
                rat_f: p.rat_f,
                mat_f: p.mat_f,
                sat_f: p.sat_f,
                damper_fb_pct: p.oa_damper_pct,
                fan_on: true,
                delta_or_f: delta_or,
                delta_mr_f: delta_mr,
                identifiable,
                oa_frac_temp_pct: oa_frac,
                mat_pred_f: mat_pred,
                mat_resid_f: mat_resid,
            });
        }

        // Downsample if needed (stride).
        if eq_points.len() > max_points_per_eq && max_points_per_eq > 0 {
            let step = (eq_points.len() / max_points_per_eq).max(1);
            eq_points = eq_points
                .into_iter()
                .enumerate()
                .filter(|(i, _)| i % step == 0)
                .map(|(_, p)| p)
                .collect();
        }

        let (median_resid, mae_resid) = if resid_vals.is_empty() {
            (None, None)
        } else {
            resid_vals.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
            let mid = resid_vals.len() / 2;
            let median = if resid_vals.len().is_multiple_of(2) {
                (resid_vals[mid - 1] + resid_vals[mid]) / 2.0
            } else {
                resid_vals[mid]
            };
            let mae = resid_vals.iter().map(|v| v.abs()).sum::<f64>() / resid_vals.len() as f64;
            (Some(round2(median)), Some(round2(mae)))
        };

        metrics.push(EconomizerMetrics {
            equipment_id: eq_id,
            equipment_type: et,
            n_fan_on_samples: fan_on_pts.len() as u64,
            n_identifiable: n_ident,
            has_damper,
            median_mat_resid_f: median_resid,
            mat_resid_mae_f: mae_resid,
            dt_min_f: dt_min,
        });
        out_points.extend(eq_points);
    }

    EconomizerResult {
        metrics,
        points: out_points,
        skipped,
    }
}

pub fn handle(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    let (qv, mut warnings) = resolve_query_version(req, QV_ECONOMIZER);
    let dt_min = req.dt_min_f.unwrap_or(DEFAULT_DT_MIN_F);
    let max_pts = req.query.max_points.unwrap_or(8000);
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
            let result = compute_economizer_diagnostics(&filtered, dt_min, max_pts);
            env.equipment = result
                .metrics
                .iter()
                .map(|m| serde_json::to_value(m).unwrap_or(json!({})))
                .collect();
            env.points = result
                .points
                .iter()
                .map(|p| serde_json::to_value(p).unwrap_or(json!({})))
                .collect();
            env.skipped = result
                .skipped
                .iter()
                .map(|s| serde_json::to_value(s).unwrap_or(json!({})))
                .collect();
            env.coverage = Some(json!({
                "equipment_count": env.equipment.len(),
                "point_count": env.points.len(),
                "skipped_count": env.skipped.len(),
                "dt_min_f": dt_min,
            }));
        }
        _ => {
            warnings.push(
                "no inline series/points provided; historian/job economizer load is next".into(),
            );
            env.warnings = warnings;
        }
    }
    env
}

fn parse_points(req: &AnalyticsRequest) -> Option<Vec<EconomizerPointIn>> {
    let series = req.series.as_ref()?;
    // Accept `{ "points": [...] }` or a bare array.
    let arr = if let Some(a) = series.as_array() {
        a.clone()
    } else if let Some(a) = series.get("points").and_then(|v| v.as_array()) {
        a.clone()
    } else {
        return None;
    };
    let mut out = Vec::new();
    for v in arr {
        if let Ok(p) = serde_json::from_value::<EconomizerPointIn>(v) {
            out.push(p);
        }
    }
    Some(out)
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
    fn fifty_percent_mixing_oa_fraction() {
        // OAT=40, RAT=70, MAT=55 → (55-70)/(40-70) = 0.5 → 50%
        let pts = vec![EconomizerPointIn {
            equipment_id: "AHU-1".into(),
            equipment_type: Some("AHU".into()),
            timestamp: ts(0),
            oat_f: 40.0,
            rat_f: 70.0,
            mat_f: 55.0,
            sat_f: None,
            fan_on: true,
            oa_damper_pct: Some(50.0),
        }];
        let result = compute_economizer_diagnostics(&pts, 10.0, 8000);
        assert_eq!(result.skipped.len(), 0);
        assert_eq!(result.points.len(), 1);
        let p = &result.points[0];
        assert!(p.identifiable);
        let frac = p.oa_frac_temp_pct.unwrap();
        assert!((frac - 50.0).abs() < 1e-6);
        // Perfect damper match → residual ~0
        assert!((p.mat_resid_f.unwrap()).abs() < 1e-9);
        assert_eq!(result.metrics[0].n_identifiable, 1);
        assert!(result.metrics[0].has_damper);
    }

    #[test]
    fn fan_off_skips_equipment() {
        let pts = vec![EconomizerPointIn {
            equipment_id: "AHU-2".into(),
            equipment_type: Some("AHU".into()),
            timestamp: ts(0),
            oat_f: 40.0,
            rat_f: 70.0,
            mat_f: 55.0,
            sat_f: None,
            fan_on: false,
            oa_damper_pct: Some(50.0),
        }];
        let result = compute_economizer_diagnostics(&pts, 10.0, 8000);
        assert!(result.points.is_empty());
        assert_eq!(result.skipped.len(), 1);
        assert_eq!(result.skipped[0].reason, "no_fan_on_rows");
    }

    #[test]
    fn small_delta_t_not_identifiable() {
        let pts = vec![EconomizerPointIn {
            equipment_id: "AHU-1".into(),
            equipment_type: Some("AHU".into()),
            timestamp: ts(0),
            oat_f: 68.0,
            rat_f: 70.0,
            mat_f: 69.0,
            sat_f: None,
            fan_on: true,
            oa_damper_pct: None,
        }];
        let result = compute_economizer_diagnostics(&pts, 10.0, 8000);
        assert!(!result.points[0].identifiable);
        assert!(result.points[0].oa_frac_temp_pct.is_none());
        assert_eq!(result.metrics[0].n_identifiable, 0);
    }

    #[test]
    fn handle_from_series_json() {
        let req = AnalyticsRequest {
            series: Some(json!({
                "points": [{
                    "equipment_id": "AHU-1",
                    "timestamp": "2024-01-01T00:00:00Z",
                    "oat_f": 40.0,
                    "rat_f": 70.0,
                    "mat_f": 55.0,
                    "fan_on": true,
                    "oa_damper_pct": 50.0
                }]
            })),
            ..Default::default()
        };
        let env = handle(&req);
        assert_eq!(env.query_version, QV_ECONOMIZER);
        assert_eq!(env.points.len(), 1);
        assert!(env.to_json().get("plotly").is_none());
    }
}
