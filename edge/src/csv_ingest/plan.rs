//! Append, join, fill execution plans.

use crate::csv_ingest::parse::parse_csv_text;
use crate::csv_ingest::timestamp::{
    analyze_timestamps, default_tz, is_timestamp_candidate, localize_timestamp,
    parse_timestamp_loose, ParseStatus, ParsedTimestamp, TimestampAnalysis,
};
use chrono::{DateTime, Timelike, Utc};
use chrono_tz::Tz;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum OperationMode {
    #[default]
    Single,
    Append,
    Join,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum JoinAlignment {
    Exact,
    FloorHour,
    AsOfPrevious,
    ResampleWeather15m,
    ResampleKwHourly,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum FillPolicy {
    #[default]
    None,
    Forward,
    Backward,
    Linear,
    Constant,
    AcknowledgeOnly,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileMapping {
    pub filename: String,
    pub timestamp_column: String,
    pub timezone: String,
    pub value_columns: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ImportPlan {
    #[serde(default)]
    pub mode: OperationMode,
    #[serde(default)]
    pub files: Vec<FileMapping>,
    pub join_alignment: Option<JoinAlignment>,
    #[serde(default)]
    pub fill_policy: FillPolicy,
    pub fill_constant: Option<f64>,
    #[serde(default = "default_ambiguous")]
    pub ambiguous_policy: String,
    #[serde(default)]
    pub output_dataset_name: String,
    pub left_dataset: Option<String>,
    pub right_dataset: Option<String>,
}

fn default_ambiguous() -> String {
    "first".into()
}

#[derive(Debug, Clone)]
pub struct OutputRow {
    pub ts_utc: Option<DateTime<Utc>>,
    pub ts_local: String,
    pub timezone: String,
    pub source_timestamp_raw: String,
    pub source_timestamp_parse_status: String,
    pub source_timestamp_fold: Option<String>,
    pub source_file: String,
    pub source_row_number: u64,
    pub values: BTreeMap<String, String>,
    pub fill_created: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlanPreview {
    pub row_count: u64,
    pub column_names: Vec<String>,
    pub sample_rows: Vec<Value>,
    pub timestamp_analysis: TimestampAnalysis,
    pub warnings: Vec<String>,
    pub time_range: Option<(String, String)>,
}

pub fn parse_file_to_rows(
    csv_text: &str,
    mapping: &FileMapping,
    delimiter: char,
    ambiguous_policy: &str,
) -> Result<Vec<OutputRow>, String> {
    let profile = parse_csv_text(csv_text, Some(delimiter))?;
    let ts_idx = profile
        .headers
        .iter()
        .position(|h| h == &mapping.timestamp_column)
        .ok_or_else(|| format!("timestamp column {} not found", mapping.timestamp_column))?;
    let tz: Tz = mapping.timezone.parse().unwrap_or_else(|_| default_tz());
    let value_indices: Vec<(String, usize)> = mapping
        .value_columns
        .iter()
        .filter_map(|vc| {
            profile
                .headers
                .iter()
                .position(|h| h == vc)
                .map(|i| (vc.clone(), i))
        })
        .collect();

    let mut rdr = csv::ReaderBuilder::new()
        .delimiter(delimiter as u8)
        .flexible(true)
        .trim(csv::Trim::All)
        .from_reader(csv_text.as_bytes());
    let mut rows = Vec::new();
    for (idx, rec) in rdr.records().enumerate() {
        let row_num = (idx + 1) as u64;
        let rec = rec.map_err(|e| e.to_string())?;
        let raw_ts = rec.get(ts_idx).unwrap_or("").to_string();
        let mut values = BTreeMap::new();
        for (name, idx) in &value_indices {
            values.insert(
                crate::csv_ingest::parse::sanitize_header(name),
                rec.get(*idx).unwrap_or("").to_string(),
            );
        }
        let pt = if let Some(naive) = parse_timestamp_loose(&raw_ts) {
            localize_timestamp(naive, tz, ambiguous_policy)
        } else {
            ParsedTimestamp {
                ts_utc: None,
                ts_local: None,
                raw: raw_ts.clone(),
                status: ParseStatus::Failed,
                fold: None,
            }
        };
        rows.push(OutputRow {
            ts_utc: pt.ts_utc,
            ts_local: pt
                .ts_local
                .map(|l| l.format("%Y-%m-%d %H:%M:%S").to_string())
                .unwrap_or_default(),
            timezone: mapping.timezone.clone(),
            source_timestamp_raw: raw_ts,
            source_timestamp_parse_status: format!("{:?}", pt.status).to_lowercase(),
            source_timestamp_fold: pt.fold,
            source_file: mapping.filename.clone(),
            source_row_number: row_num,
            values,
            fill_created: false,
        });
    }
    Ok(rows)
}

pub fn append_rows(mut batches: Vec<Vec<OutputRow>>) -> Vec<OutputRow> {
    let mut out = Vec::new();
    for b in batches.drain(..) {
        out.extend(b);
    }
    out.sort_by(|a, b| {
        a.ts_utc
            .unwrap_or(DateTime::<Utc>::MIN_UTC)
            .cmp(&b.ts_utc.unwrap_or(DateTime::<Utc>::MIN_UTC))
    });
    out
}

fn floor_hour(dt: DateTime<Utc>) -> DateTime<Utc> {
    dt.date_naive()
        .and_hms_opt(dt.hour(), 0, 0)
        .unwrap()
        .and_utc()
}

pub fn join_rows(
    left: Vec<OutputRow>,
    right: Vec<OutputRow>,
    alignment: JoinAlignment,
    fill: FillPolicy,
) -> Result<Vec<OutputRow>, String> {
    match alignment {
        JoinAlignment::Exact => join_exact(left, right),
        JoinAlignment::FloorHour | JoinAlignment::AsOfPrevious => {
            join_asof(left, right, alignment == JoinAlignment::FloorHour, fill)
        }
        JoinAlignment::ResampleWeather15m => join_weather_to_15m(left, right, fill),
        JoinAlignment::ResampleKwHourly => {
            let left_hourly = resample_kw_hourly(left);
            join_asof(left_hourly, right, true, fill)
        }
    }
}

fn join_exact(left: Vec<OutputRow>, right: Vec<OutputRow>) -> Result<Vec<OutputRow>, String> {
    let mut right_map: BTreeMap<String, OutputRow> = BTreeMap::new();
    for r in right {
        if let Some(u) = r.ts_utc {
            right_map.insert(u.to_rfc3339(), r);
        }
    }
    let mut out = Vec::new();
    for mut l in left {
        if let Some(u) = l.ts_utc {
            if let Some(r) = right_map.get(&u.to_rfc3339()) {
                for (k, v) in &r.values {
                    l.values.insert(k.clone(), v.clone());
                }
            }
        }
        out.push(l);
    }
    Ok(out)
}

fn join_asof(
    left: Vec<OutputRow>,
    mut right: Vec<OutputRow>,
    floor: bool,
    fill: FillPolicy,
) -> Result<Vec<OutputRow>, String> {
    right.sort_by_key(|r| r.ts_utc.unwrap_or(DateTime::<Utc>::MIN_UTC));
    let mut out = Vec::new();
    for mut l in left {
        let key = match l.ts_utc {
            Some(u) if floor => floor_hour(u),
            Some(u) => u,
            None => {
                out.push(l);
                continue;
            }
        };
        let mut best: Option<&OutputRow> = None;
        for r in &right {
            if let Some(ru) = r.ts_utc {
                let rk = if floor { floor_hour(ru) } else { ru };
                if rk <= key {
                    best = Some(r);
                } else {
                    break;
                }
            }
        }
        if let Some(r) = best {
            for (k, v) in &r.values {
                l.values.insert(k.clone(), v.clone());
            }
        }
        out.push(l);
    }
    apply_fill_policy(&mut out, fill);
    Ok(out)
}

fn resample_kw_hourly(rows: Vec<OutputRow>) -> Vec<OutputRow> {
    let mut buckets: BTreeMap<DateTime<Utc>, (OutputRow, Vec<BTreeMap<String, f64>>)> =
        BTreeMap::new();
    for row in rows {
        let Some(ts) = row.ts_utc else { continue };
        let hour = floor_hour(ts);
        let entry = buckets.entry(hour).or_insert_with(|| {
            let mut base = row.clone();
            base.ts_utc = Some(hour);
            base.ts_local = hour.format("%Y-%m-%d %H:%M:%S").to_string();
            base.source_timestamp_fold = Some("resample_kw_hourly".into());
            base.values.clear();
            base.fill_created = false;
            (base, Vec::new())
        });
        let mut nums = BTreeMap::new();
        for (k, v) in &row.values {
            if let Ok(n) = v.trim().parse::<f64>() {
                nums.insert(k.clone(), n);
            }
        }
        if !nums.is_empty() {
            entry.1.push(nums);
        }
    }
    buckets
        .into_iter()
        .map(|(_, (mut base, samples))| {
            if !samples.is_empty() {
                let mut sums: BTreeMap<String, f64> = BTreeMap::new();
                for sample in &samples {
                    for (k, v) in sample {
                        *sums.entry(k.clone()).or_insert(0.0) += v;
                    }
                }
                for (k, sum) in sums {
                    let avg = sum / samples.len() as f64;
                    base.values.insert(k, format!("{avg:.4}"));
                }
            }
            base
        })
        .collect()
}

fn apply_fill_policy(rows: &mut [OutputRow], fill: FillPolicy) {
    match fill {
        FillPolicy::Forward => forward_fill_numeric(rows),
        FillPolicy::Backward => backward_fill_numeric(rows),
        FillPolicy::Linear => linear_fill_numeric(rows),
        _ => {}
    }
}

fn backward_fill_numeric(rows: &mut [OutputRow]) {
    let mut next: BTreeMap<String, String> = BTreeMap::new();
    for row in rows.iter_mut().rev() {
        for (k, v) in row.values.clone() {
            if v.trim().is_empty() {
                if let Some(nxt) = next.get(&k) {
                    row.values.insert(k, nxt.clone());
                    row.fill_created = true;
                }
            } else {
                next.insert(k, v);
            }
        }
    }
}

fn linear_fill_numeric(rows: &mut [OutputRow]) {
    if rows.is_empty() {
        return;
    }
    let col_keys: Vec<String> = rows
        .iter()
        .flat_map(|r| r.values.keys().cloned())
        .collect::<std::collections::BTreeSet<_>>()
        .into_iter()
        .collect();
    for col in col_keys {
        let mut i = 0usize;
        while i < rows.len() {
            if rows[i]
                .values
                .get(&col)
                .map(|s| !s.trim().is_empty())
                .unwrap_or(false)
            {
                i += 1;
                continue;
            }
            let gap_start = i;
            while i < rows.len()
                && rows[i]
                    .values
                    .get(&col)
                    .map(|s| s.trim().is_empty())
                    .unwrap_or(true)
            {
                i += 1;
            }
            let gap_end = i;
            let prev_idx = gap_start.checked_sub(1);
            let next_idx = if gap_end < rows.len() {
                Some(gap_end)
            } else {
                None
            };
            let (Some(p), Some(n)) = (prev_idx, next_idx) else {
                continue;
            };
            let v0 = rows[p].values.get(&col).and_then(|s| s.parse::<f64>().ok());
            let v1 = rows[n].values.get(&col).and_then(|s| s.parse::<f64>().ok());
            if let (Some(a), Some(b)) = (v0, v1) {
                let steps = (gap_end - gap_start + 1) as f64;
                for (j, idx) in (gap_start..gap_end).enumerate() {
                    let t = (j as f64 + 1.0) / steps;
                    let v = a + (b - a) * t;
                    rows[idx].values.insert(col.clone(), format!("{v:.4}"));
                    rows[idx].fill_created = true;
                }
            }
        }
    }
}

fn join_weather_to_15m(
    kw: Vec<OutputRow>,
    weather: Vec<OutputRow>,
    fill: FillPolicy,
) -> Result<Vec<OutputRow>, String> {
    join_asof(kw, weather, true, fill)
}

fn forward_fill_numeric(rows: &mut [OutputRow]) {
    let mut last: BTreeMap<String, String> = BTreeMap::new();
    for row in rows.iter_mut() {
        for (k, v) in row.values.clone() {
            if v.trim().is_empty() {
                if let Some(prev) = last.get(&k) {
                    row.values.insert(k, prev.clone());
                    row.fill_created = true;
                }
            } else {
                last.insert(k, v);
            }
        }
    }
}

pub fn preview_rows(rows: &[OutputRow], limit: usize) -> PlanPreview {
    let mut col_set = BTreeMap::new();
    col_set.insert("ts_utc".into(), ());
    col_set.insert("ts_local".into(), ());
    col_set.insert("timezone".into(), ());
    col_set.insert("source_timestamp_raw".into(), ());
    col_set.insert("source_timestamp_parse_status".into(), ());
    col_set.insert("source_file".into(), ());
    col_set.insert("source_row_number".into(), ());
    for r in rows.iter().take(1000) {
        for k in r.values.keys() {
            col_set.insert(k.clone(), ());
        }
    }
    let column_names: Vec<String> = col_set.keys().cloned().collect();

    let ts_pairs: Vec<(String, ParsedTimestamp)> = rows
        .iter()
        .map(|r| {
            (
                r.source_timestamp_raw.clone(),
                ParsedTimestamp {
                    ts_utc: r.ts_utc,
                    ts_local: r.ts_local.parse().ok(),
                    raw: r.source_timestamp_raw.clone(),
                    status: match r.source_timestamp_parse_status.as_str() {
                        "ambiguous" => ParseStatus::Ambiguous,
                        "gap" => ParseStatus::Gap,
                        "failed" => ParseStatus::Failed,
                        _ => ParseStatus::Ok,
                    },
                    fold: r.source_timestamp_fold.clone(),
                },
            )
        })
        .collect();
    let timestamp_analysis = analyze_timestamps(&ts_pairs);

    let mut warnings = Vec::new();
    if timestamp_analysis.duplicate_local_count > 0 {
        warnings.push(format!(
            "Detected {} duplicate local timestamps (fall DST)",
            timestamp_analysis.duplicate_local_count
        ));
    }
    if timestamp_analysis.gap_count > 0 {
        warnings.push(format!(
            "Detected {} spring-forward gap timestamps",
            timestamp_analysis.gap_count
        ));
    }

    let sample_rows: Vec<Value> = rows
        .iter()
        .take(limit)
        .map(|r| {
            let mut obj = serde_json::Map::new();
            obj.insert("ts_utc".into(), json!(r.ts_utc.map(|u| u.to_rfc3339())));
            obj.insert("ts_local".into(), json!(r.ts_local));
            obj.insert("source_file".into(), json!(r.source_file));
            obj.insert("fill_created".into(), json!(r.fill_created));
            for (k, v) in &r.values {
                obj.insert(k.clone(), json!(v));
            }
            Value::Object(obj)
        })
        .collect();

    let time_range = if rows.is_empty() {
        None
    } else {
        let min = rows
            .iter()
            .filter_map(|r| r.ts_utc)
            .min()
            .map(|u| u.to_rfc3339());
        let max = rows
            .iter()
            .filter_map(|r| r.ts_utc)
            .max()
            .map(|u| u.to_rfc3339());
        match (min, max) {
            (Some(a), Some(b)) => Some((a, b)),
            _ => None,
        }
    };

    PlanPreview {
        row_count: rows.len() as u64,
        column_names,
        sample_rows,
        timestamp_analysis,
        warnings,
        time_range,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    #[test]
    fn linear_fill_between_known_points() {
        let mut rows = vec![
            OutputRow {
                ts_utc: Some(Utc.with_ymd_and_hms(2013, 6, 19, 0, 0, 0).unwrap()),
                ts_local: String::new(),
                timezone: "UTC".into(),
                source_timestamp_raw: String::new(),
                source_timestamp_parse_status: "ok".into(),
                source_timestamp_fold: None,
                source_file: "t.csv".into(),
                source_row_number: 1,
                values: BTreeMap::from([("kw".into(), "10".into())]),
                fill_created: false,
            },
            OutputRow {
                ts_utc: Some(Utc.with_ymd_and_hms(2013, 6, 19, 1, 0, 0).unwrap()),
                ts_local: String::new(),
                timezone: "UTC".into(),
                source_timestamp_raw: String::new(),
                source_timestamp_parse_status: "ok".into(),
                source_timestamp_fold: None,
                source_file: "t.csv".into(),
                source_row_number: 2,
                values: BTreeMap::from([("kw".into(), String::new())]),
                fill_created: false,
            },
            OutputRow {
                ts_utc: Some(Utc.with_ymd_and_hms(2013, 6, 19, 2, 0, 0).unwrap()),
                ts_local: String::new(),
                timezone: "UTC".into(),
                source_timestamp_raw: String::new(),
                source_timestamp_parse_status: "ok".into(),
                source_timestamp_fold: None,
                source_file: "t.csv".into(),
                source_row_number: 3,
                values: BTreeMap::from([("kw".into(), "20".into())]),
                fill_created: false,
            },
        ];
        apply_fill_policy(&mut rows, FillPolicy::Linear);
        let mid = rows[1].values.get("kw").unwrap();
        let v: f64 = mid.parse().unwrap();
        assert!(v > 10.0 && v < 20.0);
    }
}

pub fn plan_from_json(body: &Value) -> Result<ImportPlan, String> {
    serde_json::from_value(body.clone()).map_err(|e| e.to_string())
}

pub fn auto_detect_mapping(filename: &str, headers: &[String]) -> FileMapping {
    let ts_candidates = headers
        .iter()
        .find(|h| is_timestamp_candidate(h))
        .cloned()
        .unwrap_or_else(|| headers.first().cloned().unwrap_or_else(|| "Date".into()));
    let value_columns: Vec<String> = headers
        .iter()
        .filter(|h| *h != &ts_candidates)
        .take(20)
        .cloned()
        .collect();
    FileMapping {
        filename: filename.to_string(),
        timestamp_column: ts_candidates,
        timezone: "America/Chicago".into(),
        value_columns,
    }
}
