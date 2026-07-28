//! RCx AHU reset evidence + VAV zone comfort ranking (minimal compute).

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::collections::BTreeMap;

use super::{
    envelope, finalize_historian, historian, resolve_query_version, AnalyticsEnvelope,
    AnalyticsRequest, QV_RCX_AHU, QV_RCX_VAV,
};

/// Generic series point used for AHU reset coverage stubs.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RcxSeriesPoint {
    pub equipment_id: String,
    pub role: String,
    pub timestamp: DateTime<Utc>,
    #[serde(default)]
    pub value: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AhuResetEvidence {
    pub equipment_id: String,
    pub has_sat_sp: bool,
    pub has_duct_static_sp: bool,
    pub sat_sp_coverage_pct: f64,
    pub duct_static_sp_coverage_pct: f64,
    pub reset_evidence_stub: bool,
}

/// VAV zone comfort sample: zone temp vs setpoint (optional occupied flag).
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ZoneComfortPoint {
    pub equipment_id: String,
    pub timestamp: DateTime<Utc>,
    pub zone_temp: f64,
    pub setpoint: f64,
    #[serde(default)]
    pub occupied: Option<bool>,
    /// Half-band around setpoint for comfort (°F). Default 2.0 if omitted at compute time.
    #[serde(default)]
    pub band_f: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ZoneComfortRank {
    pub equipment_id: String,
    pub n_samples: u64,
    pub n_outside: u64,
    pub outside_pct: f64,
    pub mean_abs_error_f: f64,
}

const RESET_ROLES_SAT: &[&str] = &["sat_sp", "sat_setpoint", "supply_air_temp_sp"];
const RESET_ROLES_DUCT: &[&str] = &["duct_static_sp", "duct_sp", "static_sp"];

fn role_is_sat_sp(role: &str) -> bool {
    let r = role.to_ascii_lowercase();
    RESET_ROLES_SAT.iter().any(|k| r == *k)
}

fn role_is_duct_sp(role: &str) -> bool {
    let r = role.to_ascii_lowercase();
    RESET_ROLES_DUCT.iter().any(|k| r == *k)
}

/// Build AHU reset evidence stub fields from series (coverage only is OK).
pub fn compute_ahu_reset_evidence(points: &[RcxSeriesPoint]) -> Vec<AhuResetEvidence> {
    let mut by_eq: BTreeMap<String, Vec<&RcxSeriesPoint>> = BTreeMap::new();
    for p in points {
        by_eq.entry(p.equipment_id.clone()).or_default().push(p);
    }

    let mut out = Vec::with_capacity(by_eq.len());
    for (equipment_id, pts) in by_eq {
        let sat: Vec<_> = pts
            .iter()
            .copied()
            .filter(|p| role_is_sat_sp(&p.role))
            .collect();
        let duct: Vec<_> = pts
            .iter()
            .copied()
            .filter(|p| role_is_duct_sp(&p.role))
            .collect();

        let sat_cov = coverage_pct(&sat);
        let duct_cov = coverage_pct(&duct);
        let has_sat = !sat.is_empty();
        let has_duct = !duct.is_empty();

        out.push(AhuResetEvidence {
            equipment_id,
            has_sat_sp: has_sat,
            has_duct_static_sp: has_duct,
            sat_sp_coverage_pct: round2(sat_cov),
            duct_static_sp_coverage_pct: round2(duct_cov),
            reset_evidence_stub: has_sat || has_duct,
        });
    }
    out
}

fn coverage_pct(pts: &[&RcxSeriesPoint]) -> f64 {
    if pts.is_empty() {
        return 0.0;
    }
    let finite = pts
        .iter()
        .filter(|p| p.value.map(|v| v.is_finite()).unwrap_or(false))
        .count();
    100.0 * finite as f64 / pts.len() as f64
}

/// Rank zones by % of samples outside comfort band around setpoint.
///
/// When `occupied` is present on any point for an equipment, only occupied
/// samples contribute; otherwise all samples are used.
pub fn compute_vav_comfort_ranking(
    points: &[ZoneComfortPoint],
    default_band_f: f64,
) -> Vec<ZoneComfortRank> {
    let mut by_eq: BTreeMap<String, Vec<&ZoneComfortPoint>> = BTreeMap::new();
    for p in points {
        by_eq.entry(p.equipment_id.clone()).or_default().push(p);
    }

    let mut ranks = Vec::with_capacity(by_eq.len());
    for (equipment_id, pts) in by_eq {
        let use_occ = pts.iter().any(|p| p.occupied.is_some());
        let selected: Vec<_> = if use_occ {
            pts.into_iter()
                .filter(|p| p.occupied.unwrap_or(false))
                .collect()
        } else {
            pts
        };

        if selected.is_empty() {
            ranks.push(ZoneComfortRank {
                equipment_id,
                n_samples: 0,
                n_outside: 0,
                outside_pct: 0.0,
                mean_abs_error_f: 0.0,
            });
            continue;
        }

        let mut n_outside = 0_u64;
        let mut abs_err_sum = 0.0_f64;
        for p in &selected {
            let band = p.band_f.unwrap_or(default_band_f).abs();
            let err = (p.zone_temp - p.setpoint).abs();
            abs_err_sum += err;
            if err > band {
                n_outside += 1;
            }
        }
        let n = selected.len() as u64;
        ranks.push(ZoneComfortRank {
            equipment_id,
            n_samples: n,
            n_outside,
            outside_pct: round2(100.0 * n_outside as f64 / n as f64),
            mean_abs_error_f: round4(abs_err_sum / n as f64),
        });
    }

    ranks.sort_by(|a, b| {
        b.outside_pct
            .partial_cmp(&a.outside_pct)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.equipment_id.cmp(&b.equipment_id))
    });
    ranks
}

pub fn handle_ahu(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    let (qv, mut warnings) = resolve_query_version(req, QV_RCX_AHU);
    let mut env = envelope(&qv, &req.query, warnings.clone());

    let points = parse_rcx_series(req);
    match points {
        Some(pts) if !pts.is_empty() => {
            let mut filtered = pts;
            if let Some(ids) = &req.query.equipment_ids {
                if !ids.is_empty() {
                    filtered.retain(|p| ids.contains(&p.equipment_id));
                }
            }
            let rows = compute_ahu_reset_evidence(&filtered);
            let rows: Vec<_> = rows.into_iter().filter(|r| r.reset_evidence_stub).collect();
            env.rows = rows
                .iter()
                .map(|r| serde_json::to_value(r).unwrap_or(json!({})))
                .collect();
            env.equipment = env.rows.clone();
            env.coverage = Some(json!({
                "equipment_count": env.equipment.len(),
                "point_count": filtered.len(),
            }));
            warnings.push(
                "rcx/ahu: reset evidence coverage stub only (full reset diagnostics next)".into(),
            );
            env.warnings = warnings;
        }
        _ => {
            warnings.push("no inline series for rcx/ahu; historian/job load is next".into());
            env.warnings = warnings;
        }
    }
    env
}

pub fn handle_vav(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    let (qv, mut warnings) = resolve_query_version(req, QV_RCX_VAV);
    let mut env = envelope(&qv, &req.query, warnings.clone());

    let points = parse_zone_points(req);
    match points {
        Some(pts) if !pts.is_empty() => {
            let mut filtered = pts;
            if let Some(ids) = &req.query.equipment_ids {
                if !ids.is_empty() {
                    filtered.retain(|p| ids.contains(&p.equipment_id));
                }
            }
            let ranks = compute_vav_comfort_ranking(&filtered, 2.0);
            env.rows = ranks
                .iter()
                .map(|r| serde_json::to_value(r).unwrap_or(json!({})))
                .collect();
            env.equipment = env.rows.clone();
            env.coverage = Some(json!({
                "equipment_count": env.equipment.len(),
                "point_count": filtered.len(),
            }));
            warnings
                .push("rcx/vav: zone comfort ranking from zone_temp vs setpoint (minimal)".into());
            env.warnings = warnings;
        }
        _ => {
            warnings.push(
                "no inline zone_temp/setpoint series for rcx/vav; historian/job load is next"
                    .into(),
            );
            env.warnings = warnings;
        }
    }
    env
}

/// Async AHU handler: prefer historian descriptive counts via DataFusion when
/// no inline series is provided; otherwise inline reset-evidence coverage stub.
pub async fn handle_ahu_async(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    if req.series.is_none() {
        match historian::descriptive_counts_from_history(
            QV_RCX_AHU,
            req.query.equipment_ids.as_deref(),
            "rcx/ahu: reset-evidence coverage requires inline series",
        )
        .await
        {
            Ok(Some(env)) => return finalize_historian(req, env, QV_RCX_AHU),
            Ok(None) => {}
            Err(e) => {
                tracing::warn!(error = %e, "historian rcx/ahu path failed; using inline/empty fallback");
            }
        }
    }
    handle_ahu(req)
}

/// Async VAV handler: prefer historian descriptive counts via DataFusion when
/// no inline series is provided; otherwise inline zone-comfort ranking.
pub async fn handle_vav_async(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    if req.series.is_none() {
        match historian::descriptive_counts_from_history(
            QV_RCX_VAV,
            req.query.equipment_ids.as_deref(),
            "rcx/vav: zone-comfort ranking requires inline zone_temp/setpoint series",
        )
        .await
        {
            Ok(Some(env)) => return finalize_historian(req, env, QV_RCX_VAV),
            Ok(None) => {}
            Err(e) => {
                tracing::warn!(error = %e, "historian rcx/vav path failed; using inline/empty fallback");
            }
        }
    }
    handle_vav(req)
}

fn parse_rcx_series(req: &AnalyticsRequest) -> Option<Vec<RcxSeriesPoint>> {
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
        if let Ok(p) = serde_json::from_value::<RcxSeriesPoint>(v) {
            out.push(p);
        }
    }
    Some(out)
}

fn parse_zone_points(req: &AnalyticsRequest) -> Option<Vec<ZoneComfortPoint>> {
    let series = req.series.as_ref()?;
    let arr = if let Some(a) = series.as_array() {
        a.clone()
    } else if let Some(a) = series
        .get("zones")
        .or_else(|| series.get("points"))
        .and_then(|v| v.as_array())
    {
        a.clone()
    } else {
        return None;
    };
    let mut out = Vec::new();
    for v in arr {
        if let Ok(p) = serde_json::from_value::<ZoneComfortPoint>(v) {
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

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn ts(secs: i64) -> DateTime<Utc> {
        Utc.timestamp_opt(secs, 0).unwrap()
    }

    #[test]
    fn ahu_sat_sp_coverage() {
        let pts = vec![
            RcxSeriesPoint {
                equipment_id: "AHU-1".into(),
                role: "sat_sp".into(),
                timestamp: ts(0),
                value: Some(55.0),
            },
            RcxSeriesPoint {
                equipment_id: "AHU-1".into(),
                role: "sat_sp".into(),
                timestamp: ts(300),
                value: None,
            },
            RcxSeriesPoint {
                equipment_id: "AHU-1".into(),
                role: "mat".into(),
                timestamp: ts(0),
                value: Some(60.0),
            },
        ];
        let rows = compute_ahu_reset_evidence(&pts);
        let ahu = rows.iter().find(|r| r.equipment_id == "AHU-1").unwrap();
        assert!(ahu.has_sat_sp);
        assert!(!ahu.has_duct_static_sp);
        assert!((ahu.sat_sp_coverage_pct - 50.0).abs() < 1e-9);
        assert!(ahu.reset_evidence_stub);
    }

    #[test]
    fn vav_comfort_ranking_orders_worst_first() {
        let pts = vec![
            ZoneComfortPoint {
                equipment_id: "VAV-OK".into(),
                timestamp: ts(0),
                zone_temp: 72.0,
                setpoint: 72.0,
                occupied: Some(true),
                band_f: Some(2.0),
            },
            ZoneComfortPoint {
                equipment_id: "VAV-BAD".into(),
                timestamp: ts(0),
                zone_temp: 80.0,
                setpoint: 72.0,
                occupied: Some(true),
                band_f: Some(2.0),
            },
            ZoneComfortPoint {
                equipment_id: "VAV-BAD".into(),
                timestamp: ts(300),
                zone_temp: 79.0,
                setpoint: 72.0,
                occupied: Some(true),
                band_f: Some(2.0),
            },
        ];
        let ranks = compute_vav_comfort_ranking(&pts, 2.0);
        assert_eq!(ranks[0].equipment_id, "VAV-BAD");
        assert_eq!(ranks[0].outside_pct, 100.0);
        assert_eq!(ranks[1].equipment_id, "VAV-OK");
        assert_eq!(ranks[1].outside_pct, 0.0);
    }

    #[test]
    fn handle_ahu_and_vav() {
        let ahu_req = AnalyticsRequest {
            series: Some(json!({
                "points": [
                    {"equipment_id": "AHU-1", "role": "duct_static_sp", "timestamp": "2024-01-01T00:00:00Z", "value": 1.2}
                ]
            })),
            ..Default::default()
        };
        let env = handle_ahu(&ahu_req);
        assert_eq!(env.query_version, QV_RCX_AHU);
        assert_eq!(env.rows.len(), 1);
        assert_eq!(env.rows[0]["has_duct_static_sp"], true);

        let vav_req = AnalyticsRequest {
            series: Some(json!({
                "zones": [
                    {"equipment_id": "VAV-1", "timestamp": "2024-01-01T00:00:00Z", "zone_temp": 75.0, "setpoint": 72.0}
                ]
            })),
            ..Default::default()
        };
        let env = handle_vav(&vav_req);
        assert_eq!(env.query_version, QV_RCX_VAV);
        assert_eq!(env.rows.len(), 1);
    }
}
