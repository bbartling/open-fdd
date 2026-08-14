//! Merge hourly history_wide.csv chunks (timestamp last-write-wins).

use anyhow::{bail, Context, Result};
use std::collections::BTreeMap;
use std::path::Path;

#[derive(Debug, Clone, Default)]
pub struct MergeReport {
    pub rows_in: u64,
    pub rows_added: u64,
    pub rows_duped: u64,
    pub rows_out: u64,
    pub ts_min: Option<String>,
    pub ts_max: Option<String>,
}

/// Append `incoming` into `existing` (or create), dedup by timestamp column.
pub fn merge_history_wide_csv(existing: &Path, incoming: &Path, out: &Path) -> Result<MergeReport> {
    let incoming_text = std::fs::read_to_string(incoming).context("read incoming csv")?;
    merge_history_wide_text(
        existing,
        &incoming_text,
        out,
        existing
            .is_file()
            .then(|| std::fs::read_to_string(existing).ok())
            .flatten(),
    )
}

pub fn merge_history_wide_text(
    existing_path: &Path,
    incoming_text: &str,
    out: &Path,
    existing_text: Option<String>,
) -> Result<MergeReport> {
    let inc = parse_wide(incoming_text)?;
    if inc.headers.is_empty() {
        bail!("incoming CSV has no header");
    }
    let mut headers = inc.headers.clone();
    let mut by_ts: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut report = MergeReport {
        rows_in: inc.rows.len() as u64,
        ..Default::default()
    };

    if let Some(ex_text) = existing_text.filter(|s| !s.trim().is_empty()) {
        let ex = parse_wide(&ex_text)?;
        if ex.headers != inc.headers {
            // Allow incoming to be a subset (same order prefix) — fail on extra cols.
            let extra: Vec<_> = inc
                .headers
                .iter()
                .filter(|h| !ex.headers.iter().any(|e| e == *h))
                .cloned()
                .collect();
            if !extra.is_empty() {
                bail!("schema drift: extra columns {extra:?}");
            }
            let missing: Vec<_> = ex
                .headers
                .iter()
                .filter(|h| {
                    *h != "timestamp"
                        && *h != "timestamp_utc"
                        && !inc.headers.iter().any(|e| e == *h)
                })
                .cloned()
                .collect();
            if !missing.is_empty() {
                bail!("schema drift: missing columns {missing:?}");
            }
            headers = ex.headers.clone();
        }
        for row in ex.rows {
            if let Some(ts) = row.first() {
                by_ts.insert(ts.clone(), row);
            }
        }
    }

    for row in inc.rows {
        let Some(ts) = row.first() else { continue };
        if by_ts
            .insert(ts.clone(), align_row(&headers, &inc.headers, &row))
            .is_some()
        {
            report.rows_duped += 1;
        } else {
            report.rows_added += 1;
        }
    }

    let mut body = headers.join(",");
    body.push('\n');
    for (ts, row) in &by_ts {
        if report.ts_min.is_none() {
            report.ts_min = Some(ts.clone());
        }
        report.ts_max = Some(ts.clone());
        body.push_str(&row.join(","));
        body.push('\n');
    }
    report.rows_out = by_ts.len() as u64;
    if let Some(parent) = out.parent().or_else(|| existing_path.parent()) {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(out, body).context("write merged csv")?;
    Ok(report)
}

struct WideCsv {
    headers: Vec<String>,
    rows: Vec<Vec<String>>,
}

fn parse_wide(text: &str) -> Result<WideCsv> {
    let mut lines = text.lines().filter(|l| !l.trim().is_empty());
    let header = lines.next().unwrap_or("");
    let headers: Vec<String> = header.split(',').map(|s| s.trim().to_string()).collect();
    let mut rows = Vec::new();
    for line in lines {
        let cells: Vec<String> = line.split(',').map(|s| s.trim().to_string()).collect();
        if cells.iter().all(|c| c.is_empty()) {
            continue;
        }
        rows.push(cells);
    }
    Ok(WideCsv { headers, rows })
}

fn align_row(out_headers: &[String], in_headers: &[String], row: &[String]) -> Vec<String> {
    out_headers
        .iter()
        .map(|h| {
            in_headers
                .iter()
                .position(|x| x == h)
                .and_then(|i| row.get(i).cloned())
                .unwrap_or_default()
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn merge_dedup_and_append() {
        let tmp = TempDir::new().unwrap();
        let a = tmp.path().join("a.csv");
        let b = tmp.path().join("b.csv");
        let out = tmp.path().join("out.csv");
        std::fs::write(
            &a,
            "timestamp_utc,sat\n2026-01-01T00:00:00Z,70\n2026-01-01T00:15:00Z,71\n",
        )
        .unwrap();
        std::fs::write(
            &b,
            "timestamp_utc,sat\n2026-01-01T00:15:00Z,72\n2026-01-01T00:30:00Z,73\n",
        )
        .unwrap();
        let r = merge_history_wide_csv(&a, &b, &out).unwrap();
        assert_eq!(r.rows_out, 3);
        assert_eq!(r.rows_added, 1);
        assert_eq!(r.rows_duped, 1);
        let text = std::fs::read_to_string(&out).unwrap();
        assert!(text.contains("2026-01-01T00:30:00Z,73"));
        assert!(text.contains("2026-01-01T00:15:00Z,72"));
    }

    #[test]
    fn extra_column_fails() {
        let tmp = TempDir::new().unwrap();
        let a = tmp.path().join("a.csv");
        let b = tmp.path().join("b.csv");
        std::fs::write(&a, "timestamp_utc,sat\n2026-01-01T00:00:00Z,70\n").unwrap();
        std::fs::write(&b, "timestamp_utc,sat,ghost\n2026-01-01T01:00:00Z,70,1\n").unwrap();
        assert!(merge_history_wide_csv(&a, &b, &tmp.path().join("o.csv")).is_err());
    }
}
