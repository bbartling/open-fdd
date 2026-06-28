//! Timestamp detection, parsing, timezone normalization, DST analysis.

use chrono::{DateTime, NaiveDateTime, TimeZone, Utc};
use chrono_tz::Tz;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ParseStatus {
    Ok,
    Ambiguous,
    Gap,
    Failed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParsedTimestamp {
    pub ts_utc: Option<DateTime<Utc>>,
    pub ts_local: Option<NaiveDateTime>,
    pub raw: String,
    pub status: ParseStatus,
    pub fold: Option<String>,
}

const CANDIDATE_NAMES: &[&str] = &[
    "date",
    "time",
    "time_local",
    "timestamp",
    "datetime",
    "date_time",
    "ts",
    "timestamp",
];

pub fn is_timestamp_candidate(name: &str) -> bool {
    let lower = name.trim().to_lowercase();
    CANDIDATE_NAMES
        .iter()
        .any(|c| lower == *c || lower.contains("date") || lower.contains("time"))
}

pub fn detect_timestamp_columns(
    headers: &[String],
    sample_rows: &[Vec<String>],
) -> Vec<(usize, f64)> {
    let mut scores = Vec::new();
    for (i, h) in headers.iter().enumerate() {
        let name_boost = if is_timestamp_candidate(h) { 0.3 } else { 0.0 };
        let samples: Vec<String> = sample_rows
            .iter()
            .filter_map(|r| r.get(i).cloned())
            .collect();
        let mut ok = 0u64;
        let mut tried = 0u64;
        for s in samples.iter().take(50) {
            if s.trim().is_empty() {
                continue;
            }
            tried += 1;
            if parse_timestamp_loose(s).is_some() {
                ok += 1;
            }
        }
        let rate = if tried == 0 {
            0.0
        } else {
            ok as f64 / tried as f64
        };
        scores.push((i, rate + name_boost));
    }
    scores.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    scores
}

pub fn parse_timestamp_loose(s: &str) -> Option<NaiveDateTime> {
    let t = s.trim();
    if t.is_empty() {
        return None;
    }
    if let Ok(n) = t.parse::<i64>() {
        if n > 1_000_000_000_000 {
            return DateTime::from_timestamp_millis(n).map(|d| d.naive_utc());
        }
        return DateTime::from_timestamp(n, 0).map(|d| d.naive_utc());
    }
    if let Ok(n) = t.parse::<f64>() {
        if n > 40_000.0 && n < 60_000.0 {
            // possible Excel serial — require explicit confirm elsewhere
            return None;
        }
    }
    let formats = [
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%y %H:%M",
        "%m/%d/%Y %H:%M:%S",
    ];
    for fmt in formats {
        if let Ok(nd) = NaiveDateTime::parse_from_str(t, fmt) {
            return Some(nd);
        }
    }
    if let Ok(dt) = DateTime::parse_from_rfc3339(t) {
        return Some(dt.naive_utc());
    }
    None
}

pub fn localize_timestamp(naive: NaiveDateTime, tz: Tz, ambiguous_policy: &str) -> ParsedTimestamp {
    let raw = naive.format("%Y-%m-%d %H:%M:%S").to_string();
    match tz.from_local_datetime(&naive) {
        chrono::LocalResult::Single(dt) => ParsedTimestamp {
            ts_utc: Some(dt.with_timezone(&Utc)),
            ts_local: Some(naive),
            raw,
            status: ParseStatus::Ok,
            fold: None,
        },
        chrono::LocalResult::Ambiguous(earlier, later) => {
            let chosen = if ambiguous_policy == "second" {
                later
            } else {
                earlier
            };
            ParsedTimestamp {
                ts_utc: Some(chosen.with_timezone(&Utc)),
                ts_local: Some(naive),
                raw,
                status: ParseStatus::Ambiguous,
                fold: Some(format!(
                    "ambiguous:earlier={},later={}",
                    earlier.with_timezone(&Utc).to_rfc3339(),
                    later.with_timezone(&Utc).to_rfc3339()
                )),
            }
        }
        chrono::LocalResult::None => ParsedTimestamp {
            ts_utc: None,
            ts_local: Some(naive),
            raw,
            status: ParseStatus::Gap,
            fold: Some("spring_forward_gap".into()),
        },
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TimestampAnalysis {
    pub duplicate_local_count: u64,
    pub ambiguous_count: u64,
    pub gap_count: u64,
    pub failed_count: u64,
    pub inferred_interval_seconds: Option<i64>,
    pub duplicate_examples: Vec<String>,
    pub gap_examples: Vec<String>,
}

pub fn analyze_timestamps(rows: &[(String, ParsedTimestamp)]) -> TimestampAnalysis {
    let mut local_counts: BTreeMap<String, u64> = BTreeMap::new();
    let mut analysis = TimestampAnalysis::default();
    let mut deltas: Vec<i64> = Vec::new();
    let mut prev_utc: Option<DateTime<Utc>> = None;

    for (raw, pt) in rows {
        match pt.status {
            ParseStatus::Failed => analysis.failed_count += 1,
            ParseStatus::Gap => {
                analysis.gap_count += 1;
                if analysis.gap_examples.len() < 5 {
                    analysis.gap_examples.push(raw.clone());
                }
            }
            ParseStatus::Ambiguous => analysis.ambiguous_count += 1,
            ParseStatus::Ok => {}
        }
        if let Some(local) = pt.ts_local {
            let key = local.format("%Y-%m-%d %H:%M:%S").to_string();
            *local_counts.entry(key).or_insert(0) += 1;
        }
        if let Some(utc) = pt.ts_utc {
            if let Some(p) = prev_utc {
                let d = (utc - p).num_seconds();
                if d > 0 {
                    deltas.push(d);
                }
            }
            prev_utc = Some(utc);
        }
    }

    for (k, c) in &local_counts {
        if *c > 1 {
            analysis.duplicate_local_count += c - 1;
            if analysis.duplicate_examples.len() < 5 {
                analysis.duplicate_examples.push(format!("{k} x{c}"));
            }
        }
    }

    if !deltas.is_empty() {
        let mut freq: HashMap<i64, u64> = HashMap::new();
        for d in deltas {
            *freq.entry(d).or_insert(0) += 1;
        }
        analysis.inferred_interval_seconds =
            freq.into_iter().max_by_key(|(_, n)| *n).map(|(s, _)| s);
    }

    analysis
}

pub fn default_tz() -> Tz {
    "America/Chicago".parse().unwrap()
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::NaiveDate;

    #[test]
    fn parses_iso_local() {
        assert!(parse_timestamp_loose("2013-01-01T00:00").is_some());
    }

    #[test]
    fn parses_us_slash() {
        assert!(parse_timestamp_loose("6/19/2013 0:15").is_some());
    }

    #[test]
    fn chicago_fall_ambiguous() {
        let tz: Tz = "America/Chicago".parse().unwrap();
        // First Sunday Nov 2013 — duplicate 1:00-1:59
        let naive = NaiveDate::from_ymd_opt(2013, 11, 3)
            .unwrap()
            .and_hms_opt(1, 30, 0)
            .unwrap();
        let pt = localize_timestamp(naive, tz, "first");
        assert_eq!(pt.status, ParseStatus::Ambiguous);
    }

    #[test]
    fn chicago_spring_gap() {
        let tz: Tz = "America/Chicago".parse().unwrap();
        let naive = NaiveDate::from_ymd_opt(2013, 3, 10)
            .unwrap()
            .and_hms_opt(2, 30, 0)
            .unwrap();
        let pt = localize_timestamp(naive, tz, "first");
        assert_eq!(pt.status, ParseStatus::Gap);
    }
}
