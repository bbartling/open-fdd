//! Fuel analytics query handlers (`POST /api/analytics/fuel`).

use std::collections::{BTreeMap, BTreeSet, HashMap};

use chrono::{Datelike, NaiveDate, Utc};
use serde::Deserialize;
use serde_json::{json, Value};

use super::campus::{annual_summary, load_campus, usage_to_kbtu, Campus, ALLOCATION_AREA_WEIGHTED};
use super::eui::compare_eui;
use super::import::fuel_root;

pub const ENGINE: &str = "rust-fuel";
pub const SCHEMA_VERSION: &str = "analytics-envelope-v1";

pub const QV_SUMMARY: &str = "fuel-summary-v1";
pub const QV_MONTHLY: &str = "fuel-monthly-v1";
pub const QV_STACKED: &str = "fuel-stacked-v1";
pub const QV_INTENSITY: &str = "fuel-intensity-v1";
pub const QV_DEMAND: &str = "fuel-demand-v1";
pub const QV_QUALITY: &str = "fuel-quality-v1";
pub const QV_WEATHER: &str = "fuel-weather-v1";

pub(crate) const DD_BASE_F: f64 = 65.0;

#[derive(Debug, Clone, Default, Deserialize)]
pub struct FuelRequest {
    #[serde(default)]
    pub query_version: Option<String>,
    #[serde(default)]
    pub campus_id: Option<String>,
    #[serde(default)]
    pub allocation: Option<String>,
    #[serde(default)]
    pub building_id: Option<String>,
    /// When true, gap-fill continuous months with null usage (monthly/stacked).
    #[serde(default)]
    pub gap_fill: Option<bool>,
}

fn envelope(query_version: &str, warnings: Vec<String>) -> Value {
    json!({
        "schema_version": SCHEMA_VERSION,
        "query_version": query_version,
        "generated_at": Utc::now().to_rfc3339(),
        "engine": ENGINE,
        "coverage": Value::Null,
        "warnings": warnings,
        "rows": [],
        "points": [],
    })
}

fn resolve_campus(req: &FuelRequest) -> Result<Campus, String> {
    let root = fuel_root();
    let id = match &req.campus_id {
        Some(id) => id.clone(),
        None => {
            // Prefer sole campus, else first alphabetically.
            let list = super::import::list_campuses().map_err(|e| e.to_string())?;
            let campuses = list["campuses"].as_array().cloned().unwrap_or_default();
            if campuses.is_empty() {
                return Err("no fuel campus imported; POST /api/fuel/campus/import first".into());
            }
            campuses[0]["campus_id"]
                .as_str()
                .unwrap_or("unknown")
                .to_string()
        }
    };
    load_campus(&root.join(id)).map_err(|e| e.to_string())
}

/// Dispatch fuel analytics by `query_version`.
pub fn handle_fuel(req: &FuelRequest) -> Value {
    let qv = req
        .query_version
        .as_deref()
        .unwrap_or(QV_SUMMARY)
        .to_string();
    let mut warnings = Vec::new();
    let campus = match resolve_campus(req) {
        Ok(c) => c,
        Err(e) => {
            let mut env = envelope(&qv, vec![e]);
            env["ok"] = json!(false);
            return env;
        }
    };
    let allocation = req
        .allocation
        .as_deref()
        .unwrap_or(ALLOCATION_AREA_WEIGHTED);

    let mut env = match qv.as_str() {
        QV_SUMMARY => fuel_summary(&campus, allocation, &mut warnings),
        QV_MONTHLY => fuel_monthly(&campus, req.gap_fill.unwrap_or(false), &mut warnings),
        QV_STACKED => fuel_stacked(&campus, &mut warnings),
        QV_INTENSITY => fuel_intensity(&campus, req.building_id.as_deref(), &mut warnings),
        QV_DEMAND => fuel_demand(&campus, &mut warnings),
        QV_QUALITY => fuel_quality(&campus, &mut warnings),
        QV_WEATHER => fuel_weather(&campus, &mut warnings),
        other => {
            warnings.push(format!(
                "unknown query_version {other:?}; expected one of \
                 fuel-summary-v1|fuel-monthly-v1|fuel-stacked-v1|fuel-intensity-v1|\
                 fuel-demand-v1|fuel-quality-v1|fuel-weather-v1"
            ));
            envelope(other, warnings.clone())
        }
    };
    if let Some(arr) = env.get_mut("warnings").and_then(|v| v.as_array_mut()) {
        for w in warnings {
            if !arr.iter().any(|x| x.as_str() == Some(w.as_str())) {
                arr.push(json!(w));
            }
        }
    }
    env["ok"] = json!(true);
    env["campus_id"] = json!(campus.campus_id);
    env
}

fn fuel_summary(campus: &Campus, allocation: &str, warnings: &mut Vec<String>) -> Value {
    let mut env = envelope(QV_SUMMARY, vec![]);
    match annual_summary(campus, allocation, None) {
        Ok(summary) => {
            let mut rows = Vec::new();
            if let Some(buildings) = summary.get("buildings").and_then(|v| v.as_array()) {
                for b in buildings {
                    let eui = b
                        .get("site_eui_kbtu_ft2")
                        .and_then(|v| v.as_f64())
                        .unwrap_or(0.0);
                    let ptype = b
                        .get("property_type")
                        .and_then(|v| v.as_str())
                        .unwrap_or("office");
                    let peer = compare_eui(eui, ptype);
                    let mut row = b.clone();
                    if let Some(obj) = row.as_object_mut() {
                        obj.insert("peer".into(), peer);
                    }
                    rows.push(row);
                }
            }
            env["rows"] = json!(rows);
            env["summary"] = summary;
            env["coverage"] = json!({
                "building_count": rows.len(),
                "meter_count": campus.meters.len(),
            });
        }
        Err(e) => {
            warnings.push(e.to_string());
            env["warnings"] = json!(warnings.clone());
        }
    }
    env
}

fn continuous_months(start: &str, end: &str) -> Vec<String> {
    let mut out = Vec::new();
    let Ok(mut y) = start[..4].parse::<i32>() else {
        return out;
    };
    let Ok(mut m) = start[5..7].parse::<u32>() else {
        return out;
    };
    let Ok(ey) = end[..4].parse::<i32>() else {
        return out;
    };
    let Ok(em) = end[5..7].parse::<u32>() else {
        return out;
    };
    while (y, m) <= (ey, em) {
        out.push(format!("{y:04}-{m:02}"));
        m += 1;
        if m > 12 {
            m = 1;
            y += 1;
        }
    }
    out
}

fn fuel_monthly(campus: &Campus, gap_fill: bool, warnings: &mut Vec<String>) -> Value {
    let mut env = envelope(QV_MONTHLY, vec![]);
    let mut rows = Vec::new();
    let mut all_months: BTreeSet<String> = BTreeSet::new();
    for m in &campus.meters {
        for b in &m.bills {
            all_months.insert(b.month.clone());
            rows.push(json!({
                "month": b.month,
                "meter_id": m.meter_id,
                "fuel": m.fuel,
                "usage": b.usage,
                "unit": m.unit,
                "cost_usd": b.cost_usd,
                "demand_kw": b.demand_kw,
                "kbtu": usage_to_kbtu(b.usage, &m.fuel, &m.unit),
            }));
        }
    }
    if gap_fill && !all_months.is_empty() {
        let start = all_months.iter().next().unwrap().clone();
        let end = all_months.iter().next_back().unwrap().clone();
        let months = continuous_months(&start, &end);
        let existing: BTreeSet<(String, String)> = rows
            .iter()
            .filter_map(|r| {
                Some((
                    r.get("month")?.as_str()?.to_string(),
                    r.get("meter_id")?.as_str()?.to_string(),
                ))
            })
            .collect();
        for m in &campus.meters {
            for month in &months {
                if !existing.contains(&(month.clone(), m.meter_id.clone())) {
                    rows.push(json!({
                        "month": month,
                        "meter_id": m.meter_id,
                        "fuel": m.fuel,
                        "usage": Value::Null,
                        "unit": m.unit,
                        "cost_usd": Value::Null,
                        "demand_kw": Value::Null,
                        "kbtu": Value::Null,
                        "gap": true,
                    }));
                }
            }
        }
        warnings.push("gap_fill: inserted null rows for missing meter-months".into());
    }
    rows.sort_by(|a, b| {
        let am = a.get("month").and_then(|v| v.as_str()).unwrap_or("");
        let bm = b.get("month").and_then(|v| v.as_str()).unwrap_or("");
        am.cmp(bm).then_with(|| {
            let ai = a.get("meter_id").and_then(|v| v.as_str()).unwrap_or("");
            let bi = b.get("meter_id").and_then(|v| v.as_str()).unwrap_or("");
            ai.cmp(bi)
        })
    });
    env["rows"] = json!(rows);
    env["coverage"] = json!({ "row_count": rows.len() });
    env
}

type FuelMonthKey = (String, String);
type FuelMonthAgg = (f64, f64, Option<f64>, String);

fn campus_fuel_totals(campus: &Campus) -> Vec<Value> {
    // month → fuel → (usage, kbtu, demand max, unit)
    let mut map: BTreeMap<FuelMonthKey, FuelMonthAgg> = BTreeMap::new();
    for m in &campus.meters {
        for b in &m.bills {
            let kbtu = usage_to_kbtu(b.usage, &m.fuel, &m.unit);
            let key = (b.month.clone(), m.fuel.clone());
            let entry = map.entry(key).or_insert((0.0, 0.0, None, m.unit.clone()));
            entry.0 += b.usage;
            entry.1 += kbtu;
            if let Some(d) = b.demand_kw {
                entry.2 = Some(match entry.2 {
                    Some(prev) => prev.max(d),
                    None => d,
                });
            }
        }
    }
    map.into_iter()
        .map(|((month, fuel), (usage, kbtu, demand_kw, unit))| {
            json!({
                "month": month,
                "fuel": fuel,
                "usage": usage,
                "kbtu": kbtu,
                "unit": unit,
                "demand_kw": demand_kw,
            })
        })
        .collect()
}

fn fuel_stacked(campus: &Campus, _warnings: &mut Vec<String>) -> Value {
    let mut env = envelope(QV_STACKED, vec![]);
    let rows = campus_fuel_totals(campus);
    env["rows"] = json!(rows);
    env["coverage"] = json!({ "row_count": rows.len() });
    env
}

fn fuel_intensity(campus: &Campus, building_id: Option<&str>, warnings: &mut Vec<String>) -> Value {
    let mut env = envelope(QV_INTENSITY, vec![]);
    let area = if let Some(bid) = building_id {
        match campus.building(bid) {
            Ok(b) => b.floor_area_ft2.max(1.0),
            Err(e) => {
                warnings.push(e.to_string());
                campus.total_area_ft2().max(1.0)
            }
        }
    } else {
        campus.total_area_ft2().max(1.0)
    };

    // For building scope we'd need allocation per month — Phase A uses campus totals /
    // total area (or building area when building_id set, still campus fuel totals as
    // intensity denominator note).
    if building_id.is_some() {
        warnings.push(
            "fuel-intensity-v1 with building_id uses building floor area over campus fuel totals \
             (shared-meter monthly allocation follow-up)"
                .into(),
        );
    }

    let totals = campus_fuel_totals(campus);
    let mut rows = Vec::new();
    for t in totals {
        let month = t.get("month").and_then(|v| v.as_str()).unwrap_or("");
        let fuel = t.get("fuel").and_then(|v| v.as_str()).unwrap_or("");
        let kbtu = t.get("kbtu").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let year: i32 = month.get(..4).and_then(|s| s.parse().ok()).unwrap_or(0);
        let mon: u32 = month.get(5..7).and_then(|s| s.parse().ok()).unwrap_or(0);
        rows.push(json!({
            "month": month,
            "year": year,
            "mon": mon,
            "fuel": fuel,
            "kbtu": kbtu,
            "intensity_kbtu_ft2": kbtu / area,
            "area_ft2": area,
            "building_id": building_id,
        }));
    }
    env["rows"] = json!(rows);
    env["coverage"] = json!({ "area_ft2": area, "row_count": rows.len() });
    env
}

fn fuel_demand(campus: &Campus, _warnings: &mut Vec<String>) -> Value {
    let mut env = envelope(QV_DEMAND, vec![]);
    let mut rows = Vec::new();
    for m in &campus.meters {
        if !m.fuel.eq_ignore_ascii_case("electricity") {
            continue;
        }
        for b in &m.bills {
            let year: i32 = b.month.get(..4).and_then(|s| s.parse().ok()).unwrap_or(0);
            let mon: u32 = b.month.get(5..7).and_then(|s| s.parse().ok()).unwrap_or(0);
            rows.push(json!({
                "month": b.month,
                "year": year,
                "mon": mon,
                "meter_id": m.meter_id,
                "demand_kw": b.demand_kw,
            }));
        }
    }
    env["rows"] = json!(rows);
    env["coverage"] = json!({ "row_count": rows.len() });
    env
}

fn fuel_quality(campus: &Campus, _warnings: &mut Vec<String>) -> Value {
    let mut env = envelope(QV_QUALITY, vec![]);
    let mut rows = Vec::new();
    for m in &campus.meters {
        let months = m.months();
        if months.is_empty() {
            rows.push(json!({
                "meter_id": m.meter_id,
                "fuel": m.fuel,
                "n_months": 0,
                "completeness_pct": 0.0,
                "missing_months": [],
            }));
            continue;
        }
        let start = months.iter().next().unwrap().clone();
        let end = months.iter().next_back().unwrap().clone();
        let expected = continuous_months(&start, &end);
        let missing: Vec<_> = expected
            .iter()
            .filter(|mo| !months.contains(*mo))
            .cloned()
            .collect();
        let present = expected.len().saturating_sub(missing.len());
        let pct = if expected.is_empty() {
            0.0
        } else {
            present as f64 / expected.len() as f64 * 100.0
        };
        let with_cost = m.bills.iter().filter(|b| b.cost_usd.is_some()).count();
        let with_demand = m.bills.iter().filter(|b| b.demand_kw.is_some()).count();
        rows.push(json!({
            "meter_id": m.meter_id,
            "fuel": m.fuel,
            "n_months": m.bills.len(),
            "span_start": start,
            "span_end": end,
            "expected_months": expected.len(),
            "missing_months": missing,
            "completeness_pct": (pct * 10.0).round() / 10.0,
            "cost_coverage_pct": if m.bills.is_empty() { 0.0 } else { with_cost as f64 / m.bills.len() as f64 * 100.0 },
            "demand_coverage_pct": if m.bills.is_empty() { 0.0 } else { with_demand as f64 / m.bills.len() as f64 * 100.0 },
        }));
    }
    env["rows"] = json!(rows);
    env["coverage"] = json!({ "meter_count": rows.len() });
    env
}

/// Synthetic hourly OA (vibe20 `_synthetic_hourly`): 35 + 30·sin(2π·(yday−80)/365).
fn synthetic_monthly_degree_days(
    months: &[String],
    _lat: Option<f64>,
) -> BTreeMap<String, (f64, f64, f64)> {
    // month → (hdd, cdd, mean_oat)
    let mut out = BTreeMap::new();
    if months.is_empty() {
        return out;
    }
    let start = &months[0];
    let end = &months[months.len() - 1];
    let Ok(sy) = start[..4].parse::<i32>() else {
        return out;
    };
    let Ok(sm) = start[5..7].parse::<u32>() else {
        return out;
    };
    let Ok(ey) = end[..4].parse::<i32>() else {
        return out;
    };
    let Ok(em) = end[5..7].parse::<u32>() else {
        return out;
    };

    let start_date = NaiveDate::from_ymd_opt(sy, sm, 1)
        .unwrap_or_else(|| NaiveDate::from_ymd_opt(2000, 1, 1).unwrap());
    let end_exclusive = if em == 12 {
        NaiveDate::from_ymd_opt(ey + 1, 1, 1)
    } else {
        NaiveDate::from_ymd_opt(ey, em + 1, 1)
    }
    .unwrap_or(start_date);

    let mut daily: HashMap<NaiveDate, (f64, u32)> = HashMap::new();
    let mut d = start_date;
    while d < end_exclusive {
        let yday = d.ordinal() as f64;
        let temp = 35.0 + 30.0 * (2.0 * std::f64::consts::PI * (yday - 80.0) / 365.0).sin();
        // 24 identical hourly samples → daily mean equals the sine value.
        daily.insert(d, (temp * 24.0, 24));
        d = match d.succ_opt() {
            Some(n) => n,
            None => break,
        };
    }

    let mut monthly_acc: BTreeMap<String, (f64, f64, f64, u32)> = BTreeMap::new();
    for (day, (sum, n)) in daily {
        if n == 0 {
            continue;
        }
        let mean = sum / n as f64;
        let hdd = (DD_BASE_F - mean).max(0.0);
        let cdd = (mean - DD_BASE_F).max(0.0);
        let key = format!("{:04}-{:02}", day.year(), day.month());
        let e = monthly_acc.entry(key).or_insert((0.0, 0.0, 0.0, 0));
        e.0 += hdd;
        e.1 += cdd;
        e.2 += mean;
        e.3 += 1;
    }
    for (month, (hdd, cdd, mean_sum, n)) in monthly_acc {
        out.insert(
            month,
            (hdd, cdd, if n > 0 { mean_sum / n as f64 } else { 0.0 }),
        );
    }
    out
}

fn ols_fit(xs: &[f64], ys: &[f64]) -> Option<(f64, f64, f64)> {
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
    let mean_x = pairs.iter().map(|(x, _)| x).sum::<f64>() / n as f64;
    let mean_y = pairs.iter().map(|(_, y)| y).sum::<f64>() / n as f64;
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

fn fuel_weather(campus: &Campus, warnings: &mut Vec<String>) -> Value {
    let mut env = envelope(QV_WEATHER, vec![]);
    let totals = campus_fuel_totals(campus);
    let months: Vec<String> = totals
        .iter()
        .filter_map(|t| {
            t.get("month")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
        })
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    if months.is_empty() {
        warnings.push("no bill months for weather alignment".into());
        env["warnings"] = json!(warnings.clone());
        return env;
    }

    let (dd, dd_source) = match crate::fuel::open_meteo::load_cached_degree_days(&campus.campus_id)
    {
        Some(cache) => {
            let map = crate::fuel::open_meteo::cache_to_dd_map(&cache);
            let covered = months.iter().filter(|m| map.contains_key(*m)).count();
            if covered == 0 {
                warnings.push(
                    "fuel-weather-v1: Open-Meteo cache present but no months overlap bills; using synthetic sine OA"
                        .into(),
                );
                (synthetic_monthly_degree_days(&months, campus.lat), "synthetic_sine_oa")
            } else {
                if covered < months.len() {
                    warnings.push(format!(
                        "fuel-weather-v1: Open-Meteo covers {covered}/{} bill months (partial)",
                        months.len()
                    ));
                }
                warnings.push(format!(
                    "fuel-weather-v1: Open-Meteo archive HDD/CDD (downloaded {})",
                    cache.downloaded_at_utc
                ));
                (map, "open-meteo-archive")
            }
        }
        None => {
            warnings.push(
                "fuel-weather-v1: synthetic sine OA — click Fetch Open-Meteo on Weather tab for live HDD/CDD (vibe20 parity)"
                    .into(),
            );
            (synthetic_monthly_degree_days(&months, campus.lat), "synthetic_sine_oa")
        }
    };

    let mut gas_x = Vec::new();
    let mut gas_y = Vec::new();
    let mut elec_x = Vec::new();
    let mut elec_y = Vec::new();
    let mut points = Vec::new();
    let mut aligned_rows = Vec::new();

    for t in &totals {
        let month = t.get("month").and_then(|v| v.as_str()).unwrap_or("");
        let fuel = t.get("fuel").and_then(|v| v.as_str()).unwrap_or("");
        let usage = t.get("usage").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let unit = t.get("unit").and_then(|v| v.as_str()).unwrap_or("");
        let Some(&(hdd, cdd, mean_oat)) = dd.get(month) else {
            continue;
        };
        aligned_rows.push(json!({
            "month": month,
            "fuel": fuel,
            "usage": usage,
            "unit": unit,
            "hdd": hdd,
            "cdd": cdd,
            "mean_oat_f": mean_oat,
            "kbtu": t.get("kbtu"),
        }));
        if fuel.eq_ignore_ascii_case("gas") {
            gas_x.push(hdd);
            gas_y.push(usage);
            points.push(json!({
                "month": month,
                "fuel": "gas",
                "x": hdd,
                "y": usage,
                "x_name": "hdd",
                "y_name": "usage",
            }));
        } else if fuel.eq_ignore_ascii_case("electricity") {
            elec_x.push(cdd);
            elec_y.push(usage);
            points.push(json!({
                "month": month,
                "fuel": "electricity",
                "x": cdd,
                "y": usage,
                "x_name": "cdd",
                "y_name": "usage",
            }));
        }
    }

    let mut fits = Vec::new();
    if let Some((slope, intercept, r2)) = ols_fit(&gas_x, &gas_y) {
        if gas_x.len() >= 6 {
            fits.push(json!({
                "fuel": "gas",
                "x": "hdd",
                "y": "usage",
                "unit": "mcf",
                "n_months": gas_x.len(),
                "slope": (slope * 1e6).round() / 1e6,
                "intercept": (intercept * 1e4).round() / 1e4,
                "r2": (r2 * 1e4).round() / 1e4,
                "base_f": DD_BASE_F,
            }));
        } else {
            warnings.push(format!(
                "gas×HDD OLS skipped: need ≥6 months, got {}",
                gas_x.len()
            ));
        }
    }
    if let Some((slope, intercept, r2)) = ols_fit(&elec_x, &elec_y) {
        if elec_x.len() >= 6 {
            fits.push(json!({
                "fuel": "electricity",
                "x": "cdd",
                "y": "usage",
                "unit": "kwh",
                "n_months": elec_x.len(),
                "slope": (slope * 1e6).round() / 1e6,
                "intercept": (intercept * 1e4).round() / 1e4,
                "r2": (r2 * 1e4).round() / 1e4,
                "base_f": DD_BASE_F,
            }));
        } else {
            warnings.push(format!(
                "elec×CDD OLS skipped: need ≥6 months, got {}",
                elec_x.len()
            ));
        }
    }

    env["rows"] = json!(aligned_rows);
    env["points"] = json!(points);
    env["fits"] = json!(fits);
    env["coverage"] = json!({
        "months": months.len(),
        "aligned_rows": aligned_rows.len(),
        "n_fits": fits.len(),
        "degree_days": {
            "base_f": DD_BASE_F,
            "source": dd_source,
            "method": "daily_mean_oat_then_monthly_sum",
            "convention": "vibe19_metering_DD_BASE_F",
        },
        "lat": campus.lat,
        "lon": campus.lon,
    });
    env["warnings"] = json!(warnings.clone());
    env
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::jobs::WORKSPACE_ENV_TEST_LOCK;
    use std::path::PathBuf;

    fn fixture_campus() -> Campus {
        let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/fuel");
        load_campus(&dir).expect("fixture campus")
    }

    #[test]
    fn summary_and_weather_on_fixture() {
        let _g = WORKSPACE_ENV_TEST_LOCK.lock().unwrap();
        let dir = tempfile::tempdir().unwrap();
        let prev = std::env::var("OPENFDD_WORKSPACE").ok();
        std::env::set_var("OPENFDD_WORKSPACE", dir.path());

        let fixture = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/fuel");
        if !fixture.join("campus.json").is_file() {
            if let Some(v) = prev {
                std::env::set_var("OPENFDD_WORKSPACE", v);
            } else {
                std::env::remove_var("OPENFDD_WORKSPACE");
            }
            return;
        }
        // Import via copy
        let dest = fuel_root().join("liberty_practice_bensbench");
        std::fs::create_dir_all(&dest).unwrap();
        for name in [
            "campus.json",
            "Liberty_50_100_Electric_Summary.csv",
            "Liberty_50_Gas_Summary.csv",
            "Liberty_100_Gas_Summary.csv",
        ] {
            std::fs::copy(fixture.join(name), dest.join(name)).unwrap();
        }

        let req = FuelRequest {
            query_version: Some(QV_SUMMARY.into()),
            campus_id: Some("liberty_practice_bensbench".into()),
            allocation: Some(ALLOCATION_AREA_WEIGHTED.into()),
            ..Default::default()
        };
        let out = handle_fuel(&req);
        assert_eq!(out["ok"], true, "summary failed: {out}");
        assert_eq!(out["engine"], ENGINE);
        assert!(out["rows"].as_array().unwrap().len() >= 2);
        assert!(out["rows"][0].get("peer").is_some() || out["rows"][0].get("peer_p50").is_some());

        let wreq = FuelRequest {
            query_version: Some(QV_WEATHER.into()),
            campus_id: Some("liberty_practice_bensbench".into()),
            ..Default::default()
        };
        let w = handle_fuel(&wreq);
        assert_eq!(w["ok"], true, "weather failed: {w}");
        assert!(!w["points"].as_array().unwrap().is_empty());
        assert!(!w["fits"].as_array().unwrap().is_empty());

        if let Some(v) = prev {
            std::env::set_var("OPENFDD_WORKSPACE", v);
        } else {
            std::env::remove_var("OPENFDD_WORKSPACE");
        }
    }

    #[test]
    fn monthly_gap_fill() {
        let campus = fixture_campus();
        let mut warnings = Vec::new();
        let env = fuel_monthly(&campus, true, &mut warnings);
        assert!(!env["rows"].as_array().unwrap().is_empty());
    }
}
