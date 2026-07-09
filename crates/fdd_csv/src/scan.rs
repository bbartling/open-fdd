use std::path::Path;

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct TimestampHealth {
    pub column: String,
    pub sample_count: usize,
    pub duplicate_timestamps: usize,
    pub non_monotonic_steps: usize,
    pub malformed_rows: usize,
    pub median_delta_seconds: Option<f64>,
    pub min_timestamp: Option<String>,
    pub max_timestamp: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CsvScanReport {
    pub path: String,
    pub header_columns: Vec<String>,
    pub estimated_rows: u64,
    pub file_bytes: u64,
    pub timestamp: Option<TimestampHealth>,
}

pub fn scan_history_csv(path: &Path, sample_rows: usize) -> Result<CsvScanReport> {
    let meta = std::fs::metadata(path).context("metadata")?;
    let mut rdr = csv::ReaderBuilder::new()
        .has_headers(true)
        .from_path(path)
        .context("open csv")?;
    let headers: Vec<String> = rdr.headers()?.iter().map(|s| s.to_string()).collect();
    let ts_col = headers
        .iter()
        .position(|h| h == "timestamp_utc" || h == "timestamp")
        .map(|i| (i, headers[i].clone()));

    let mut timestamps: Vec<DateTime<Utc>> = Vec::new();
    let mut malformed = 0usize;
    for (i, rec) in rdr.records().enumerate() {
        if i >= sample_rows {
            break;
        }
        let rec = match rec {
            Ok(r) => r,
            Err(_) => {
                malformed += 1;
                continue;
            }
        };
        if let Some((idx, _)) = ts_col {
            let raw = rec.get(idx).unwrap_or("");
            match raw.parse::<DateTime<Utc>>() {
                Ok(ts) => timestamps.push(ts),
                Err(_) => malformed += 1,
            }
        }
    }

    let timestamp = ts_col.map(|(_, col)| analyze_timestamps(col, &timestamps, malformed));

    Ok(CsvScanReport {
        path: path.display().to_string(),
        header_columns: headers,
        estimated_rows: (meta.len() / 80).max(1),
        file_bytes: meta.len(),
        timestamp,
    })
}

fn analyze_timestamps(
    column: String,
    timestamps: &[DateTime<Utc>],
    malformed_rows: usize,
) -> TimestampHealth {
    let mut dups = 0usize;
    let mut non_mono = 0usize;
    let mut deltas = Vec::new();
    for w in timestamps.windows(2) {
        if w[0] == w[1] {
            dups += 1;
        }
        if w[1] < w[0] {
            non_mono += 1;
        }
        let dt = (w[1] - w[0]).num_seconds() as f64;
        if dt > 0.0 {
            deltas.push(dt);
        }
    }
    deltas.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let median_delta = if deltas.is_empty() {
        None
    } else {
        Some(deltas[deltas.len() / 2])
    };

    TimestampHealth {
        column,
        sample_count: timestamps.len(),
        duplicate_timestamps: dups,
        non_monotonic_steps: non_mono,
        malformed_rows,
        median_delta_seconds: median_delta,
        min_timestamp: timestamps.first().map(|t| t.to_rfc3339()),
        max_timestamp: timestamps.last().map(|t| t.to_rfc3339()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn scan_detects_timestamp_column() {
        let mut f = NamedTempFile::new().unwrap();
        writeln!(f, "timestamp_utc,oat_f").unwrap();
        writeln!(f, "2026-01-01T00:00:00Z,65").unwrap();
        writeln!(f, "2026-01-01T00:05:00Z,66").unwrap();
        let report = scan_history_csv(f.path(), 10).unwrap();
        assert!(report.timestamp.is_some());
        let ts = report.timestamp.unwrap();
        assert_eq!(ts.median_delta_seconds, Some(300.0));
    }
}
