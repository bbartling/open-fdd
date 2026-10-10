//! Merge hourly history_wide.csv chunks (timestamp last-write-wins).
//!
//! Soft-OPEN 370 T1d / M70-04: stream existing history line-by-line into an
//! atomic temp file. Only the incoming request rows are retained in a BTreeMap
//! — working-set peak tracks the append chunk, not retained history length.

use anyhow::{bail, Context, Result};
use std::collections::BTreeMap;
use std::fs::File;
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Default)]
pub struct MergeReport {
    pub rows_in: u64,
    pub rows_added: u64,
    pub rows_duped: u64,
    pub rows_out: u64,
    pub ts_min: Option<String>,
    pub ts_max: Option<String>,
    /// Peak number of incoming rows held during merge (request-bounded).
    pub incoming_resident_rows: u64,
}

/// Append `incoming` into `existing` (or create), dedup by timestamp column.
pub fn merge_history_wide_csv(existing: &Path, incoming: &Path, out: &Path) -> Result<MergeReport> {
    let incoming_text = std::fs::read_to_string(incoming).context("read incoming csv")?;
    merge_history_wide_text(existing, &incoming_text, out, None)
}

/// Merge `incoming_text` into the CSV at `existing_path`, writing atomically to `out`.
///
/// `existing_text` is ignored when `existing_path` is a readable file — kept only
/// for API compatibility with callers that previously pre-loaded history.
pub fn merge_history_wide_text(
    existing_path: &Path,
    incoming_text: &str,
    out: &Path,
    _existing_text: Option<String>,
) -> Result<MergeReport> {
    let inc = parse_wide(incoming_text)?;
    if inc.headers.is_empty() {
        bail!("incoming CSV has no header");
    }
    let mut report = MergeReport {
        rows_in: inc.rows.len() as u64,
        incoming_resident_rows: inc.rows.len() as u64,
        ..Default::default()
    };

    let mut incoming_by_ts: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for row in inc.rows {
        let Some(ts) = row.first().cloned() else {
            continue;
        };
        if ts.is_empty() {
            continue;
        }
        incoming_by_ts.insert(ts, row);
    }

    let parent = out
        .parent()
        .or_else(|| existing_path.parent())
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."));
    std::fs::create_dir_all(&parent)?;
    let tmp = parent.join(format!(
        ".{}.append-{}.tmp",
        out.file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("history_wide.csv"),
        std::process::id()
    ));

    let result = if existing_path.is_file() {
        merge_stream_existing(
            existing_path,
            &inc.headers,
            &mut incoming_by_ts,
            &tmp,
            &mut report,
        )
    } else {
        write_incoming_only(&inc.headers, &incoming_by_ts, &tmp, &mut report)
    };

    if let Err(e) = result {
        let _ = std::fs::remove_file(&tmp);
        return Err(e);
    }

    std::fs::rename(&tmp, out)
        .with_context(|| format!("atomic rename {} -> {}", tmp.display(), out.display()))?;
    Ok(report)
}

fn merge_stream_existing(
    existing_path: &Path,
    incoming_headers: &[String],
    incoming_by_ts: &mut BTreeMap<String, Vec<String>>,
    tmp: &Path,
    report: &mut MergeReport,
) -> Result<()> {
    let file = File::open(existing_path)
        .with_context(|| format!("open existing {}", existing_path.display()))?;
    let mut reader = BufReader::new(file);
    let mut header_line = String::new();
    reader
        .read_line(&mut header_line)
        .context("read existing header")?;
    let existing_headers: Vec<String> = header_line
        .trim_end_matches(['\r', '\n'])
        .split(',')
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty() || !header_line.trim().is_empty())
        .collect();
    if existing_headers.is_empty() {
        bail!("existing CSV has no header");
    }
    reconcile_headers(&existing_headers, incoming_headers)?;
    let headers = existing_headers;

    let out_file = File::create(tmp).context("create append temp")?;
    let mut writer = BufWriter::new(out_file);
    writeln!(writer, "{}", headers.join(",")).context("write header")?;

    let mut prev_ts: Option<String> = None;
    let mut line = String::new();
    let mut incoming_iter = std::mem::take(incoming_by_ts).into_iter().peekable();

    loop {
        line.clear();
        let n = reader.read_line(&mut line).context("read existing row")?;
        if n == 0 {
            break;
        }
        let trimmed = line.trim_end_matches(['\r', '\n']);
        if trimmed.is_empty() {
            continue;
        }
        let cells: Vec<String> = trimmed.split(',').map(|s| s.trim().to_string()).collect();
        let Some(ts) = cells.first().cloned() else {
            continue;
        };
        if ts.is_empty() {
            continue;
        }
        if let Some(prev) = &prev_ts {
            if ts.as_str() < prev.as_str() {
                bail!(
                    "existing history_wide.csv is not timestamp-sorted (saw {ts} after {prev}); re-seed package or repair CSV before append"
                );
            }
        }
        prev_ts = Some(ts.clone());

        // Emit any incoming rows that sort before this existing timestamp.
        while let Some((in_ts, _)) = incoming_iter.peek() {
            if in_ts.as_str() < ts.as_str() {
                let (in_ts, in_row) = incoming_iter.next().expect("peeked");
                write_aligned_row(&mut writer, &headers, incoming_headers, &in_row, report)?;
                report.rows_added += 1;
                track_span(report, &in_ts);
            } else {
                break;
            }
        }

        if let Some((in_ts, _)) = incoming_iter.peek() {
            if in_ts == &ts {
                let (in_ts, in_row) = incoming_iter.next().expect("peeked");
                write_aligned_row(&mut writer, &headers, incoming_headers, &in_row, report)?;
                report.rows_duped += 1;
                track_span(report, &in_ts);
                continue;
            }
        }

        // Keep existing row.
        writeln!(writer, "{}", cells.join(",")).context("write existing row")?;
        report.rows_out += 1;
        track_span(report, &ts);
    }

    // Tail of incoming after last existing timestamp.
    for (in_ts, in_row) in incoming_iter {
        write_aligned_row(&mut writer, &headers, incoming_headers, &in_row, report)?;
        report.rows_added += 1;
        track_span(report, &in_ts);
    }

    writer.flush().context("flush append temp")?;
    Ok(())
}

fn write_incoming_only(
    headers: &[String],
    incoming_by_ts: &BTreeMap<String, Vec<String>>,
    tmp: &Path,
    report: &mut MergeReport,
) -> Result<()> {
    let out_file = File::create(tmp).context("create append temp")?;
    let mut writer = BufWriter::new(out_file);
    writeln!(writer, "{}", headers.join(",")).context("write header")?;
    for (ts, row) in incoming_by_ts {
        write_aligned_row(&mut writer, headers, headers, row, report)?;
        report.rows_added += 1;
        track_span(report, ts);
    }
    writer.flush().context("flush append temp")?;
    Ok(())
}

fn write_aligned_row(
    writer: &mut BufWriter<File>,
    out_headers: &[String],
    in_headers: &[String],
    row: &[String],
    report: &mut MergeReport,
) -> Result<()> {
    let aligned = align_row(out_headers, in_headers, row);
    writeln!(writer, "{}", aligned.join(",")).context("write merged row")?;
    report.rows_out += 1;
    Ok(())
}

fn track_span(report: &mut MergeReport, ts: &str) {
    if report.ts_min.is_none() {
        report.ts_min = Some(ts.to_string());
    }
    report.ts_max = Some(ts.to_string());
}

fn reconcile_headers(existing: &[String], incoming: &[String]) -> Result<()> {
    if existing == incoming {
        return Ok(());
    }
    let extra: Vec<_> = incoming
        .iter()
        .filter(|h| !existing.iter().any(|e| e == *h))
        .cloned()
        .collect();
    if !extra.is_empty() {
        bail!("schema drift: extra columns {extra:?}");
    }
    let missing: Vec<_> = existing
        .iter()
        .filter(|h| *h != "timestamp" && *h != "timestamp_utc" && !incoming.iter().any(|e| e == *h))
        .cloned()
        .collect();
    if !missing.is_empty() {
        bail!("schema drift: missing columns {missing:?}");
    }
    Ok(())
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
        assert_eq!(r.incoming_resident_rows, 2);
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

    #[test]
    fn growing_history_keeps_incoming_resident_bound() {
        let tmp = TempDir::new().unwrap();
        let hist = tmp.path().join("history_wide.csv");
        // Lexicographically sortable synthetic timestamps (not wall-clock seconds).
        let mut body = String::from("timestamp_utc,sat\n");
        for i in 0..5_000 {
            body.push_str(&format!("2026-01-01T00:00:{i:04}Z,{i}\n"));
        }
        std::fs::write(&hist, body).unwrap();
        let chunk = "timestamp_utc,sat\n2026-01-01T00:00:5000Z,5000\n2026-01-01T00:00:2500Z,9999\n";
        let r = merge_history_wide_text(&hist, chunk, &hist, None).unwrap();
        assert_eq!(r.rows_out, 5_001);
        assert_eq!(r.rows_added, 1);
        assert_eq!(r.rows_duped, 1);
        assert_eq!(
            r.incoming_resident_rows, 2,
            "resident set must be incoming-only, not full history"
        );
        let text = std::fs::read_to_string(&hist).unwrap();
        assert!(text.contains("2026-01-01T00:00:2500Z,9999"));
        assert!(text.contains("2026-01-01T00:00:5000Z,5000"));
    }

    #[test]
    fn unsorted_existing_fails_closed() {
        let tmp = TempDir::new().unwrap();
        let hist = tmp.path().join("history_wide.csv");
        std::fs::write(
            &hist,
            "timestamp_utc,sat\n2026-01-01T01:00:00Z,1\n2026-01-01T00:00:00Z,0\n",
        )
        .unwrap();
        let err = merge_history_wide_text(
            &hist,
            "timestamp_utc,sat\n2026-01-01T02:00:00Z,2\n",
            &hist,
            None,
        )
        .unwrap_err()
        .to_string();
        assert!(err.contains("not timestamp-sorted"), "{err}");
    }
}
