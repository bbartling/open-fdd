//! Metering aggregations — monthly kWh sum (no finance / EnergyPlus).

use serde::{Deserialize, Serialize};
use serde_json::json;
use std::collections::BTreeMap;

use super::{envelope, resolve_query_version, AnalyticsEnvelope, AnalyticsRequest, QV_METERING};

/// One metering energy row: period label (e.g. `2024-01`) + kWh.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct MeterRow {
    /// Calendar period key, typically `YYYY-MM` or any stable monthly label.
    pub period: String,
    pub kwh: f64,
    #[serde(default)]
    pub meter_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct MonthlySum {
    pub period: String,
    pub kwh: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub meter_id: Option<String>,
    pub n_rows: u64,
}

/// Sum kWh by (period, optional meter_id).
pub fn monthly_sum(rows: &[MeterRow]) -> Vec<MonthlySum> {
    let mut map: BTreeMap<(String, Option<String>), (f64, u64)> = BTreeMap::new();
    for r in rows {
        if !r.kwh.is_finite() {
            continue;
        }
        let entry = map
            .entry((r.period.clone(), r.meter_id.clone()))
            .or_insert((0.0, 0));
        entry.0 += r.kwh;
        entry.1 += 1;
    }
    map.into_iter()
        .map(|((period, meter_id), (kwh, n_rows))| MonthlySum {
            period,
            kwh: round4(kwh),
            meter_id,
            n_rows,
        })
        .collect()
}

pub fn handle(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    let (qv, mut warnings) = resolve_query_version(req, QV_METERING);
    let mut env = envelope(&qv, &req.query, warnings.clone());

    let rows = parse_rows(req);
    match rows {
        Some(meter_rows) if !meter_rows.is_empty() => {
            let sums = monthly_sum(&meter_rows);
            env.rows = sums
                .iter()
                .map(|r| serde_json::to_value(r).unwrap_or(json!({})))
                .collect();
            env.coverage = Some(json!({
                "period_count": env.rows.len(),
                "input_row_count": meter_rows.len(),
                "total_kwh": round4(sums.iter().map(|s| s.kwh).sum::<f64>()),
            }));
            warnings.push(
                "metering: monthly kWh sum only (no finance / EnergyPlus calibration)".into(),
            );
            env.warnings = warnings;
        }
        _ => {
            warnings.push(
                "no inline {period,kwh} rows provided; historian/job metering load is next".into(),
            );
            env.warnings = warnings;
        }
    }
    env
}

fn parse_rows(req: &AnalyticsRequest) -> Option<Vec<MeterRow>> {
    let series = req.series.as_ref()?;
    let arr = if let Some(a) = series.as_array() {
        a.clone()
    } else if let Some(a) = series
        .get("rows")
        .or_else(|| series.get("points"))
        .and_then(|v| v.as_array())
    {
        a.clone()
    } else {
        return None;
    };
    let mut out = Vec::new();
    for v in arr {
        if let Ok(p) = serde_json::from_value::<MeterRow>(v) {
            out.push(p);
        }
    }
    Some(out)
}

fn round4(x: f64) -> f64 {
    (x * 10_000.0).round() / 10_000.0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn monthly_sum_aggregates_periods() {
        let rows = vec![
            MeterRow {
                period: "2024-01".into(),
                kwh: 100.0,
                meter_id: None,
            },
            MeterRow {
                period: "2024-01".into(),
                kwh: 50.5,
                meter_id: None,
            },
            MeterRow {
                period: "2024-02".into(),
                kwh: 200.0,
                meter_id: None,
            },
        ];
        let sums = monthly_sum(&rows);
        assert_eq!(sums.len(), 2);
        assert_eq!(sums[0].period, "2024-01");
        assert!((sums[0].kwh - 150.5).abs() < 1e-9);
        assert_eq!(sums[0].n_rows, 2);
        assert_eq!(sums[1].period, "2024-02");
        assert!((sums[1].kwh - 200.0).abs() < 1e-9);
    }

    #[test]
    fn handle_from_series() {
        let req = AnalyticsRequest {
            series: Some(json!({
                "rows": [
                    {"period": "2024-03", "kwh": 10.0},
                    {"period": "2024-03", "kwh": 5.0}
                ]
            })),
            ..Default::default()
        };
        let env = handle(&req);
        assert_eq!(env.query_version, QV_METERING);
        assert_eq!(env.rows.len(), 1);
        assert_eq!(env.rows[0]["kwh"], 15.0);
        assert_eq!(env.engine, super::super::ENGINE);
    }
}
