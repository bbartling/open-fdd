//! Thin IPMVP Option C–style monthly M&V twin (degree-day OLS).
//!
//! Not a Camber port — clean-room monthly baseline vs reporting:
//! fit `energy = intercept + slope * degree_days` on baseline months,
//! predict reporting months, savings = predicted − actual.
//! Callers supply degree-days (HDD or CDD); this module does not invent weather.

use serde::{Deserialize, Serialize};
use serde_json::json;
use std::collections::BTreeSet;

use super::{
    envelope, resolve_query_version, AnalyticsEnvelope, AnalyticsRequest, QV_MV_CHANGE_POINT,
};
use crate::analytics::metering::{monthly_sum, MeterRow};

/// One monthly energy × degree-day observation.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct MvMonthRow {
    pub period: String,
    pub energy: f64,
    pub degree_days: f64,
    #[serde(default)]
    pub meter_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct MvFit {
    pub intercept: f64,
    pub slope: f64,
    pub r2: f64,
    pub n_baseline: u64,
    pub dd_kind: String,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct MvResultRow {
    pub period: String,
    pub energy: f64,
    pub degree_days: f64,
    pub period_kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub predicted: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub savings: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub meter_id: Option<String>,
}

/// OLS `y = intercept + slope * x`. Returns `None` when <2 finite pairs or degenerate x.
pub fn ols_fit(xs: &[f64], ys: &[f64]) -> Option<(f64, f64, f64)> {
    let pairs: Vec<(f64, f64)> = xs
        .iter()
        .zip(ys.iter())
        .filter(|(x, y)| x.is_finite() && y.is_finite())
        .map(|(x, y)| (*x, *y))
        .collect();
    let n = pairs.len();
    if n < 2 {
        return None;
    }
    let mean_x = pairs.iter().map(|(x, _)| *x).sum::<f64>() / n as f64;
    let mean_y = pairs.iter().map(|(_, y)| *y).sum::<f64>() / n as f64;
    let mut ss_xx = 0.0;
    let mut ss_xy = 0.0;
    let mut ss_yy = 0.0;
    for (x, y) in &pairs {
        let dx = x - mean_x;
        let dy = y - mean_y;
        ss_xx += dx * dx;
        ss_xy += dx * dy;
        ss_yy += dy * dy;
    }
    if ss_xx < 1e-12 {
        return None;
    }
    let slope = ss_xy / ss_xx;
    let intercept = mean_y - slope * mean_x;
    let ss_res: f64 = pairs
        .iter()
        .map(|(x, y)| {
            let yhat = slope * x + intercept;
            (y - yhat).powi(2)
        })
        .sum();
    let r2 = if ss_yy > 0.0 {
        1.0 - ss_res / ss_yy
    } else {
        f64::NAN
    };
    Some((slope, intercept, r2))
}

fn round4(x: f64) -> f64 {
    (x * 10_000.0).round() / 10_000.0
}

fn round6(x: f64) -> f64 {
    (x * 1_000_000.0).round() / 1_000_000.0
}

/// Split periods into baseline vs reporting.
/// Prefer explicit lists; else `baseline_end` (inclusive); else first half / second half.
pub fn split_periods(
    periods: &[String],
    baseline_periods: Option<&[String]>,
    reporting_periods: Option<&[String]>,
    baseline_end: Option<&str>,
) -> (BTreeSet<String>, BTreeSet<String>, Vec<String>) {
    let mut warnings = Vec::new();
    if let (Some(b), Some(r)) = (baseline_periods, reporting_periods) {
        return (
            b.iter().cloned().collect(),
            r.iter().cloned().collect(),
            warnings,
        );
    }
    if let Some(end) = baseline_end {
        let mut base = BTreeSet::new();
        let mut rep = BTreeSet::new();
        for p in periods {
            if p.as_str() <= end {
                base.insert(p.clone());
            } else {
                rep.insert(p.clone());
            }
        }
        if base.is_empty() || rep.is_empty() {
            warnings.push(format!(
                "baseline_end={end} left empty baseline or reporting set"
            ));
        }
        return (base, rep, warnings);
    }
    let mut sorted = periods.to_vec();
    sorted.sort();
    if sorted.len() < 4 {
        warnings.push(format!(
            "auto split needs ≥4 months, got {}; put all in baseline",
            sorted.len()
        ));
        return (sorted.into_iter().collect(), BTreeSet::new(), warnings);
    }
    let mid = sorted.len() / 2;
    let base: BTreeSet<String> = sorted[..mid].iter().cloned().collect();
    let rep: BTreeSet<String> = sorted[mid..].iter().cloned().collect();
    warnings.push(format!(
        "auto-split periods: baseline n={} reporting n={} (set baseline_end or lists for IPMVP control)",
        base.len(),
        rep.len()
    ));
    (base, rep, warnings)
}

/// Core twin compute: OLS on baseline → predict reporting → savings.
pub fn change_point_monthly(
    rows: &[MvMonthRow],
    baseline: &BTreeSet<String>,
    reporting: &BTreeSet<String>,
    dd_kind: &str,
) -> (Option<MvFit>, Vec<MvResultRow>, Vec<String>) {
    let mut warnings = Vec::new();
    let mut xs = Vec::new();
    let mut ys = Vec::new();
    for r in rows {
        if !baseline.contains(&r.period) {
            continue;
        }
        if !r.energy.is_finite() || !r.degree_days.is_finite() {
            continue;
        }
        xs.push(r.degree_days);
        ys.push(r.energy);
    }
    if xs.len() < 2 {
        warnings.push(format!(
            "need ≥2 finite baseline months for OLS, got {}",
            xs.len()
        ));
        let out: Vec<MvResultRow> = rows
            .iter()
            .map(|r| {
                let kind = if baseline.contains(&r.period) {
                    "baseline"
                } else if reporting.contains(&r.period) {
                    "reporting"
                } else {
                    "other"
                };
                MvResultRow {
                    period: r.period.clone(),
                    energy: round4(r.energy),
                    degree_days: round4(r.degree_days),
                    period_kind: kind.into(),
                    predicted: None,
                    savings: None,
                    meter_id: r.meter_id.clone(),
                }
            })
            .collect();
        return (None, out, warnings);
    }
    if xs.len() < 6 {
        warnings.push(format!(
            "baseline n={} <6 — fit is provisional (IPMVP often wants ≥12)",
            xs.len()
        ));
    }
    let Some((slope, intercept, r2)) = ols_fit(&xs, &ys) else {
        warnings.push("OLS fit failed (degenerate degree-days)".into());
        return (None, Vec::new(), warnings);
    };
    let fit = MvFit {
        intercept: round4(intercept),
        slope: round6(slope),
        r2: round4(r2),
        n_baseline: xs.len() as u64,
        dd_kind: dd_kind.to_string(),
    };
    let mut out = Vec::new();
    for r in rows {
        let kind = if baseline.contains(&r.period) {
            "baseline"
        } else if reporting.contains(&r.period) {
            "reporting"
        } else {
            "other"
        };
        let (predicted, savings) = if kind == "reporting" && r.degree_days.is_finite() {
            let pred = intercept + slope * r.degree_days;
            let sav = pred - r.energy;
            (Some(round4(pred)), Some(round4(sav)))
        } else if kind == "baseline" && r.degree_days.is_finite() {
            let pred = intercept + slope * r.degree_days;
            (Some(round4(pred)), Some(round4(pred - r.energy)))
        } else {
            (None, None)
        };
        out.push(MvResultRow {
            period: r.period.clone(),
            energy: round4(r.energy),
            degree_days: round4(r.degree_days),
            period_kind: kind.into(),
            predicted,
            savings,
            meter_id: r.meter_id.clone(),
        });
    }
    (Some(fit), out, warnings)
}

fn parse_mv_rows(series: &serde_json::Value) -> Option<Vec<MvMonthRow>> {
    let arr = if let Some(a) = series.as_array() {
        a.clone()
    } else {
        series
            .get("rows")
            .or_else(|| series.get("points"))
            .and_then(|v| v.as_array())?
            .clone()
    };
    let mut out = Vec::new();
    for v in arr {
        // Accept energy | kwh aliases; degree_days | dd | hdd | cdd.
        let period = v
            .get("period")
            .or_else(|| v.get("month"))
            .and_then(|x| x.as_str())?
            .to_string();
        let energy = v
            .get("energy")
            .or_else(|| v.get("kwh"))
            .or_else(|| v.get("usage"))
            .and_then(|x| x.as_f64())?;
        let degree_days = v
            .get("degree_days")
            .or_else(|| v.get("dd"))
            .or_else(|| v.get("hdd"))
            .or_else(|| v.get("cdd"))
            .and_then(|x| x.as_f64())?;
        let meter_id = v
            .get("meter_id")
            .and_then(|x| x.as_str())
            .map(|s| s.to_string());
        if energy.is_finite() && degree_days.is_finite() {
            out.push(MvMonthRow {
                period,
                energy,
                degree_days,
                meter_id,
            });
        }
    }
    Some(out)
}

fn parse_string_list(v: Option<&serde_json::Value>) -> Option<Vec<String>> {
    let arr = v?.as_array()?;
    let mut out = Vec::new();
    for item in arr {
        if let Some(s) = item.as_str() {
            out.push(s.to_string());
        }
    }
    if out.is_empty() {
        None
    } else {
        Some(out)
    }
}

/// Optionally roll raw metering `{period,kwh}` through [`monthly_sum`] then require DD
/// on a parallel `degree_days` map in series.
fn rows_from_metering_wrap(series: &serde_json::Value) -> Option<Vec<MvMonthRow>> {
    let meter_rows: Vec<MeterRow> = {
        let arr = series.get("meter_rows")?.as_array()?;
        let mut out = Vec::new();
        for v in arr {
            if let Ok(r) = serde_json::from_value::<MeterRow>(v.clone()) {
                out.push(r);
            }
        }
        out
    };
    if meter_rows.is_empty() {
        return None;
    }
    let sums = monthly_sum(&meter_rows);
    let dd_map = series.get("degree_days_by_period")?.as_object()?;
    let mut out = Vec::new();
    for s in sums {
        let Some(dd) = dd_map.get(&s.period).and_then(|v| v.as_f64()) else {
            continue;
        };
        out.push(MvMonthRow {
            period: s.period,
            energy: s.kwh,
            degree_days: dd,
            meter_id: s.meter_id,
        });
    }
    Some(out)
}

pub fn handle(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    let (qv, mut warnings) = resolve_query_version(req, QV_MV_CHANGE_POINT);
    let mut env = envelope(&qv, &req.query, warnings.clone());

    let Some(series) = req.series.as_ref() else {
        warnings.push(
            "mv-change-point-v1: provide series.rows[{period,energy,degree_days}] (+ baseline_end or period lists)"
                .into(),
        );
        env.warnings = warnings;
        return env;
    };

    let mut rows = parse_mv_rows(series).unwrap_or_default();
    if rows.is_empty() {
        if let Some(wrapped) = rows_from_metering_wrap(series) {
            rows = wrapped;
            warnings.push(
                "mv-change-point-v1: built rows via metering monthly_sum + degree_days_by_period"
                    .into(),
            );
        }
    }
    if rows.is_empty() {
        warnings.push(
            "mv-change-point-v1: no usable {period,energy,degree_days} rows (or meter_rows wrap)"
                .into(),
        );
        env.warnings = warnings;
        return env;
    }

    let periods: Vec<String> = rows.iter().map(|r| r.period.clone()).collect();
    let baseline_list = parse_string_list(series.get("baseline_periods"));
    let reporting_list = parse_string_list(series.get("reporting_periods"));
    let baseline_end = series
        .get("baseline_end")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let (baseline, reporting, mut split_warns) = split_periods(
        &periods,
        baseline_list.as_deref(),
        reporting_list.as_deref(),
        baseline_end.as_deref(),
    );
    warnings.append(&mut split_warns);

    let dd_kind = series
        .get("dd_kind")
        .and_then(|v| v.as_str())
        .unwrap_or("degree_days")
        .to_string();

    let (fit, result_rows, mut compute_warns) =
        change_point_monthly(&rows, &baseline, &reporting, &dd_kind);
    warnings.append(&mut compute_warns);
    warnings.push(
        "mv-change-point-v1: IPMVP Option C–style monthly OLS twin (not investment-grade Camber)"
            .into(),
    );

    let savings_reporting: f64 = result_rows
        .iter()
        .filter(|r| r.period_kind == "reporting")
        .filter_map(|r| r.savings)
        .sum();
    let reporting_energy: f64 = result_rows
        .iter()
        .filter(|r| r.period_kind == "reporting")
        .map(|r| r.energy)
        .sum();
    let predicted_reporting: f64 = result_rows
        .iter()
        .filter(|r| r.period_kind == "reporting")
        .filter_map(|r| r.predicted)
        .sum();

    env.rows = result_rows
        .iter()
        .map(|r| serde_json::to_value(r).unwrap_or(json!({})))
        .collect();
    env.points = result_rows
        .iter()
        .map(|r| {
            json!({
                "period": r.period,
                "x": r.degree_days,
                "y": r.energy,
                "y_predicted": r.predicted,
                "period_kind": r.period_kind,
                "x_name": dd_kind,
                "y_name": "energy",
            })
        })
        .collect();
    env.coverage = Some(json!({
        "method": "ipmvp_option_c_monthly_dd_ols",
        "dd_kind": dd_kind,
        "n_rows": result_rows.len(),
        "n_baseline": baseline.len(),
        "n_reporting": reporting.len(),
        "fit": fit,
        "savings_reporting_total": round4(savings_reporting),
        "reporting_energy_total": round4(reporting_energy),
        "predicted_reporting_total": round4(predicted_reporting),
    }));
    env.warnings = warnings;
    env
}

#[cfg(test)]
mod tests {
    use super::*;

    fn seed_rows() -> Vec<MvMonthRow> {
        // Synthetic: energy ≈ 500 + 2.0 * DD, reporting months lower by ~100.
        let base = [
            ("2023-01", 500.0 + 2.0 * 800.0, 800.0),
            ("2023-02", 500.0 + 2.0 * 700.0, 700.0),
            ("2023-03", 500.0 + 2.0 * 500.0, 500.0),
            ("2023-04", 500.0 + 2.0 * 300.0, 300.0),
            ("2023-05", 500.0 + 2.0 * 100.0, 100.0),
            ("2023-06", 500.0 + 2.0 * 50.0, 50.0),
            ("2023-07", 500.0 + 2.0 * 20.0, 20.0),
            ("2023-08", 500.0 + 2.0 * 30.0, 30.0),
            ("2023-09", 500.0 + 2.0 * 80.0, 80.0),
            ("2023-10", 500.0 + 2.0 * 250.0, 250.0),
            ("2023-11", 500.0 + 2.0 * 450.0, 450.0),
            ("2023-12", 500.0 + 2.0 * 750.0, 750.0),
        ];
        let rep = [
            ("2024-01", 500.0 + 2.0 * 780.0 - 100.0, 780.0),
            ("2024-02", 500.0 + 2.0 * 690.0 - 100.0, 690.0),
            ("2024-03", 500.0 + 2.0 * 480.0 - 100.0, 480.0),
        ];
        base.iter()
            .chain(rep.iter())
            .map(|(p, e, d)| MvMonthRow {
                period: (*p).into(),
                energy: *e,
                degree_days: *d,
                meter_id: None,
            })
            .collect()
    }

    #[test]
    fn ols_recovers_known_line() {
        let xs = [1.0, 2.0, 3.0, 4.0];
        let ys = [3.0, 5.0, 7.0, 9.0]; // y = 1 + 2x
        let (slope, intercept, r2) = ols_fit(&xs, &ys).unwrap();
        assert!((slope - 2.0).abs() < 1e-9);
        assert!((intercept - 1.0).abs() < 1e-9);
        assert!((r2 - 1.0).abs() < 1e-9);
    }

    #[test]
    fn change_point_reports_positive_savings() {
        let rows = seed_rows();
        let periods: Vec<String> = rows.iter().map(|r| r.period.clone()).collect();
        let (baseline, reporting, _) = split_periods(&periods, None, None, Some("2023-12"));
        assert_eq!(baseline.len(), 12);
        assert_eq!(reporting.len(), 3);
        let (fit, out, warns) = change_point_monthly(&rows, &baseline, &reporting, "hdd");
        assert!(warns.iter().all(|w| !w.contains("failed")));
        let fit = fit.expect("fit");
        assert!((fit.slope - 2.0).abs() < 1e-3);
        assert!((fit.intercept - 500.0).abs() < 1e-2);
        let sav: f64 = out
            .iter()
            .filter(|r| r.period_kind == "reporting")
            .filter_map(|r| r.savings)
            .sum();
        assert!(
            (sav - 300.0).abs() < 1.0,
            "expected ~300 kWh savings, got {sav}"
        );
    }

    #[test]
    fn handle_from_series_seed() {
        let rows = seed_rows();
        let series = json!({
            "rows": rows,
            "baseline_end": "2023-12",
            "dd_kind": "hdd",
        });
        let req = AnalyticsRequest {
            series: Some(series),
            query: super::super::AnalyticsQuery {
                query_version: Some(QV_MV_CHANGE_POINT.into()),
                ..Default::default()
            },
            ..Default::default()
        };
        let env = handle(&req);
        assert_eq!(env.query_version, QV_MV_CHANGE_POINT);
        assert_eq!(env.engine, super::super::ENGINE);
        assert!(!env.rows.is_empty());
        let cov = env.coverage.as_ref().unwrap();
        assert_eq!(cov["method"], "ipmvp_option_c_monthly_dd_ols");
        let sav = cov["savings_reporting_total"].as_f64().unwrap();
        assert!((sav - 300.0).abs() < 1.0);
    }

    #[test]
    fn metering_wrap_builds_rows() {
        let series = json!({
            "meter_rows": [
                {"period": "2023-01", "kwh": 100.0},
                {"period": "2023-01", "kwh": 50.0},
                {"period": "2023-02", "kwh": 200.0},
                {"period": "2024-01", "kwh": 80.0},
                {"period": "2024-02", "kwh": 90.0},
            ],
            "degree_days_by_period": {
                "2023-01": 400.0,
                "2023-02": 350.0,
                "2024-01": 380.0,
                "2024-02": 360.0,
            },
            "baseline_end": "2023-02",
            "dd_kind": "cdd",
        });
        let req = AnalyticsRequest {
            series: Some(series),
            ..Default::default()
        };
        let env = handle(&req);
        assert!(env.warnings.iter().any(|w| w.contains("monthly_sum")));
        assert_eq!(env.rows.len(), 4);
    }
}
