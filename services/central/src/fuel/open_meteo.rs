//! Open-Meteo Archive download for fuel HDD/CDD (vibe20 `wattlab.weather.open_meteo`).
//!
//! Fetches hourly dry-bulb °F from `archive-api.open-meteo.com/v1/archive`, aggregates
//! to monthly HDD/CDD (base 65°F), and caches under
//! `$OPENFDD_WORKSPACE/data/fuel/<campus_id>/weather/open_meteo_dd.json`.

use std::collections::{BTreeMap, HashMap};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use anyhow::{anyhow, Context, Result};
use chrono::{Datelike, NaiveDate};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use super::analytics::DD_BASE_F;
use super::campus::Campus;
use super::import::fuel_root;

pub const ARCHIVE_URL: &str = "https://archive-api.open-meteo.com/v1/archive";
pub const SOURCE_NAME: &str = "open-meteo-archive";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MonthlyDegreeDays {
    pub hdd: f64,
    pub cdd: f64,
    pub mean_oat_f: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OpenMeteoDdCache {
    pub source: String,
    pub latitude: f64,
    pub longitude: f64,
    pub start_date: String,
    pub end_date: String,
    pub downloaded_at_utc: String,
    pub base_f: f64,
    /// month `YYYY-MM` → degree days
    pub months: BTreeMap<String, MonthlyDegreeDays>,
}

pub type Opener = Box<dyn Fn(&str) -> Result<Vec<u8>> + Send>;

fn default_opener(url: &str) -> Result<Vec<u8>> {
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(90))
        .build()
        .context("reqwest client")?;
    let resp = client
        .get(url)
        .send()
        .with_context(|| format!("Open-Meteo GET {url}"))?;
    if !resp.status().is_success() {
        return Err(anyhow!(
            "Open-Meteo HTTP {}: {}",
            resp.status(),
            resp.text().unwrap_or_default()
        ));
    }
    Ok(resp.bytes()?.to_vec())
}

pub fn weather_cache_path(campus_id: &str) -> PathBuf {
    fuel_root()
        .join(campus_id)
        .join("weather")
        .join("open_meteo_dd.json")
}

pub fn load_cached_degree_days(campus_id: &str) -> Option<OpenMeteoDdCache> {
    let path = weather_cache_path(campus_id);
    let raw = fs::read_to_string(&path).ok()?;
    serde_json::from_str(&raw).ok()
}

fn atomic_write_json(path: &Path, value: &Value) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let tmp = path.with_extension("json.tmp");
    {
        let mut f = fs::File::create(&tmp)?;
        serde_json::to_writer_pretty(&mut f, value)?;
        f.write_all(b"\n")?;
        f.sync_all()?;
    }
    fs::rename(&tmp, path)?;
    Ok(())
}

pub fn build_archive_url(lat: f64, lon: f64, start: &str, end: &str) -> String {
    format!(
        "{ARCHIVE_URL}?latitude={lat}&longitude={lon}&start_date={start}&end_date={end}\
         &hourly=temperature_2m&temperature_unit=fahrenheit&timezone=UTC"
    )
}

/// Daily-mean OA → monthly HDD/CDD (same convention as vibe19 metering / fuel synthetic).
pub fn monthly_degree_days_from_hourly(
    times: &[String],
    temps_f: &[Option<f64>],
) -> BTreeMap<String, MonthlyDegreeDays> {
    let mut daily: HashMap<NaiveDate, (f64, u32)> = HashMap::new();
    for (ts, temp) in times.iter().zip(temps_f.iter()) {
        let Some(t) = temp.filter(|v| v.is_finite()) else {
            continue;
        };
        let day = NaiveDate::parse_from_str(&ts[..10.min(ts.len())], "%Y-%m-%d").ok();
        let Some(day) = day else { continue };
        let e = daily.entry(day).or_insert((0.0, 0));
        e.0 += t;
        e.1 += 1;
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
    monthly_acc
        .into_iter()
        .map(|(month, (hdd, cdd, mean_sum, n))| {
            (
                month,
                MonthlyDegreeDays {
                    hdd,
                    cdd,
                    mean_oat_f: if n > 0 { mean_sum / n as f64 } else { 0.0 },
                },
            )
        })
        .collect()
}

fn parse_archive_payload(bytes: &[u8]) -> Result<(Vec<String>, Vec<Option<f64>>)> {
    let v: Value = serde_json::from_slice(bytes).context("Open-Meteo JSON")?;
    let hourly = v
        .get("hourly")
        .ok_or_else(|| anyhow!("Open-Meteo response missing hourly"))?;
    let times: Vec<String> = hourly
        .get("time")
        .and_then(|t| t.as_array())
        .ok_or_else(|| anyhow!("Open-Meteo hourly.time missing"))?
        .iter()
        .filter_map(|x| x.as_str().map(|s| s.to_string()))
        .collect();
    let temps: Vec<Option<f64>> = hourly
        .get("temperature_2m")
        .and_then(|t| t.as_array())
        .ok_or_else(|| anyhow!("Open-Meteo hourly.temperature_2m missing"))?
        .iter()
        .map(|x| x.as_f64())
        .collect();
    if times.is_empty() || times.len() != temps.len() {
        return Err(anyhow!(
            "Open-Meteo time/temp length mismatch ({} vs {})",
            times.len(),
            temps.len()
        ));
    }
    Ok((times, temps))
}

/// Bill month span → archive start/end (first day of first month → last day of last month).
pub fn month_span_to_dates(months: &[String]) -> Result<(String, String)> {
    let start = months
        .first()
        .ok_or_else(|| anyhow!("no months"))?;
    let end = months.last().ok_or_else(|| anyhow!("no months"))?;
    let sy: i32 = start[..4].parse()?;
    let sm: u32 = start[5..7].parse()?;
    let ey: i32 = end[..4].parse()?;
    let em: u32 = end[5..7].parse()?;
    let start_date = NaiveDate::from_ymd_opt(sy, sm, 1).ok_or_else(|| anyhow!("bad start"))?;
    let end_month_start = NaiveDate::from_ymd_opt(ey, em, 1).ok_or_else(|| anyhow!("bad end"))?;
    let end_date = if em == 12 {
        NaiveDate::from_ymd_opt(ey + 1, 1, 1)
    } else {
        NaiveDate::from_ymd_opt(ey, em + 1, 1)
    }
    .and_then(|d| d.pred_opt())
    .unwrap_or(end_month_start);
    Ok((
        start_date.format("%Y-%m-%d").to_string(),
        end_date.format("%Y-%m-%d").to_string(),
    ))
}

pub fn fetch_and_cache_degree_days(
    campus: &Campus,
    months: &[String],
    opener: Option<Opener>,
) -> Result<OpenMeteoDdCache> {
    let lat = campus
        .lat
        .ok_or_else(|| anyhow!("campus lat required for Open-Meteo"))?;
    let lon = campus
        .lon
        .ok_or_else(|| anyhow!("campus lon required for Open-Meteo"))?;
    if months.is_empty() {
        return Err(anyhow!("no bill months for Open-Meteo span"));
    }
    if std::env::var("OPENFDD_FUEL_WEATHER_OFFLINE")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
    {
        return Err(anyhow!(
            "OPENFDD_FUEL_WEATHER_OFFLINE set — refusing network Open-Meteo fetch"
        ));
    }
    let (start, end) = month_span_to_dates(months)?;
    let url = build_archive_url(lat, lon, &start, &end);
    let open = opener.unwrap_or_else(|| Box::new(|u| default_opener(u)));
    let bytes = open(&url)?;
    let (times, temps) = parse_archive_payload(&bytes)?;
    let months_dd = monthly_degree_days_from_hourly(&times, &temps);
    let cache = OpenMeteoDdCache {
        source: SOURCE_NAME.into(),
        latitude: lat,
        longitude: lon,
        start_date: start,
        end_date: end,
        downloaded_at_utc: chrono::Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string(),
        base_f: DD_BASE_F,
        months: months_dd,
    };
    let path = weather_cache_path(&campus.campus_id);
    atomic_write_json(&path, &serde_json::to_value(&cache)?)?;
    Ok(cache)
}

/// API handler: fetch Open-Meteo for a campus and persist DD cache.
pub fn fetch_open_meteo_handler(campus_id: &str) -> Value {
    let root = fuel_root().join(campus_id);
    let campus = match super::campus::load_campus(&root) {
        Ok(c) => c,
        Err(e) => {
            return json!({"ok": false, "error": format!("load campus: {e}")});
        }
    };
    let months: Vec<String> = {
        let mut set = std::collections::BTreeSet::new();
        for m in &campus.meters {
            set.extend(m.months());
        }
        set.into_iter().collect()
    };
    match fetch_and_cache_degree_days(&campus, &months, None) {
        Ok(cache) => json!({
            "ok": true,
            "campus_id": campus.campus_id,
            "source": cache.source,
            "path": weather_cache_path(&campus.campus_id).display().to_string(),
            "months": cache.months.len(),
            "start_date": cache.start_date,
            "end_date": cache.end_date,
            "downloaded_at_utc": cache.downloaded_at_utc,
            "lat": cache.latitude,
            "lon": cache.longitude,
            "hint": "Re-run fuel-weather-v1 analytics to plot Open-Meteo HDD/CDD.",
        }),
        Err(e) => json!({"ok": false, "error": e.to_string(), "campus_id": campus_id}),
    }
}

/// Convert cache → map used by fuel_weather (month → hdd,cdd,mean).
pub fn cache_to_dd_map(cache: &OpenMeteoDdCache) -> BTreeMap<String, (f64, f64, f64)> {
    cache
        .months
        .iter()
        .map(|(k, v)| (k.clone(), (v.hdd, v.cdd, v.mean_oat_f)))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::fuel::campus::Campus;

    #[test]
    fn monthly_dd_from_hourly_fixture() {
        let times = vec![
            "2023-01-01T00:00".into(),
            "2023-01-01T01:00".into(),
            "2023-07-01T00:00".into(),
            "2023-07-01T01:00".into(),
        ];
        let temps = vec![Some(20.0), Some(20.0), Some(80.0), Some(80.0)];
        let dd = monthly_degree_days_from_hourly(&times, &temps);
        let jan = dd.get("2023-01").unwrap();
        let jul = dd.get("2023-07").unwrap();
        assert!((jan.hdd - 45.0).abs() < 1e-6); // 65-20
        assert!((jan.cdd - 0.0).abs() < 1e-6);
        assert!((jul.cdd - 15.0).abs() < 1e-6); // 80-65
        assert!((jul.hdd - 0.0).abs() < 1e-6);
    }

    #[test]
    fn fetch_with_injected_opener_writes_cache() {
        let _lock = crate::jobs::WORKSPACE_ENV_TEST_LOCK.lock().unwrap();
        let dir = tempfile::tempdir().unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", dir.path());
        let campus = Campus {
            campus_id: "test_campus".into(),
            label: "Test".into(),
            buildings: vec![],
            meters: vec![],
            notes: String::new(),
            source: dir.path().to_path_buf(),
            lat: Some(42.5),
            lon: Some(-83.1),
            site_ref: None,
        };
        let months = vec!["2023-01".into()];
        let opener: Opener = Box::new(|_url| {
            Ok(br#"{
              "hourly": {
                "time": ["2023-01-01T00:00","2023-01-01T01:00"],
                "temperature_2m": [30.0, 30.0]
              }
            }"#
            .to_vec())
        });
        let cache = fetch_and_cache_degree_days(&campus, &months, Some(opener)).unwrap();
        assert_eq!(cache.source, SOURCE_NAME);
        assert!(weather_cache_path("test_campus").is_file());
        let jan = cache.months.get("2023-01").unwrap();
        assert!((jan.hdd - 35.0).abs() < 1e-6);
        std::env::remove_var("OPENFDD_WORKSPACE");
    }
}
