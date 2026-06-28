//! CSV parsing: delimiter/encoding detection, type inference, quarantine.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

pub const MAX_UPLOAD_BYTES: usize = 250 * 1024 * 1024;
pub const MAX_ROWS: usize = 10_000_000;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ColumnKind {
    Timestamp,
    Float,
    Integer,
    Boolean,
    String,
    Null,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ColumnProfile {
    pub original_name: String,
    pub sanitized_name: String,
    pub kind: ColumnKind,
    pub null_count: u64,
    pub sample_values: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QuarantinedRow {
    pub row_number: u64,
    pub column: Option<String>,
    pub raw_value: String,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParseProfile {
    pub delimiter: char,
    pub encoding: String,
    pub has_bom: bool,
    pub headers: Vec<String>,
    pub sanitized_headers: Vec<String>,
    pub columns: Vec<ColumnProfile>,
    pub row_count: u64,
    pub quarantined: Vec<QuarantinedRow>,
    pub sample_rows: Vec<Vec<String>>,
}

pub fn sanitize_filename(name: &str) -> Result<String, String> {
    if name.contains("..") || name.contains('\0') {
        return Err("invalid filename".into());
    }
    let base = name.rsplit(['/', '\\']).next().unwrap_or(name).trim();
    if base.is_empty() {
        return Err("invalid filename".into());
    }
    let safe: String = base
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '.' || c == '-' || c == '_' || c == ' ' {
                c
            } else {
                '_'
            }
        })
        .collect();
    if safe.is_empty() {
        return Err("invalid filename".into());
    }
    Ok(safe)
}

pub fn sanitize_header(name: &str) -> String {
    let mut out = String::new();
    let mut prev_us = false;
    for c in name.trim().chars() {
        if c.is_ascii_alphanumeric() {
            out.push(c.to_ascii_lowercase());
            prev_us = false;
        } else if !prev_us {
            out.push('_');
            prev_us = true;
        }
    }
    let t = out.trim_matches('_');
    if t.is_empty() {
        "col".into()
    } else {
        t.to_string()
    }
}

pub fn decode_bytes(raw: &[u8]) -> (String, String, bool) {
    if raw.starts_with(&[0xEF, 0xBB, 0xBF]) {
        let s = String::from_utf8_lossy(&raw[3..]).into_owned();
        return (s, "utf-8-bom".into(), true);
    }
    if let Ok(s) = std::str::from_utf8(raw) {
        return (s.to_string(), "utf-8".into(), false);
    }
    let (cow, _, _) = encoding_rs::WINDOWS_1252.decode(raw);
    (cow.into_owned(), "windows-1252".into(), false)
}

pub fn detect_delimiter(sample: &str) -> char {
    let line = sample.lines().next().unwrap_or(sample);
    let candidates = [',', '\t', ';', '|'];
    let mut best = ',';
    let mut best_count = 0usize;
    for d in candidates {
        let count = line.matches(d).count();
        if count > best_count {
            best_count = count;
            best = d;
        }
    }
    best
}

fn is_null_token(s: &str) -> bool {
    matches!(
        s.trim().to_ascii_lowercase().as_str(),
        "" | "na" | "n/a" | "null" | "none" | "--" | "nan"
    )
}

fn infer_kind(values: &[String]) -> ColumnKind {
    let mut non_null = 0u64;
    let mut float_ok = 0u64;
    let mut int_ok = 0u64;
    let mut bool_ok = 0u64;
    for v in values {
        if is_null_token(v) {
            continue;
        }
        non_null += 1;
        let t = v.trim();
        if t.eq_ignore_ascii_case("true") || t.eq_ignore_ascii_case("false") || t == "0" || t == "1"
        {
            bool_ok += 1;
        }
        if t.parse::<i64>().is_ok() {
            int_ok += 1;
        }
        if t.replace(',', "").parse::<f64>().is_ok() {
            float_ok += 1;
        }
    }
    if non_null == 0 {
        return ColumnKind::Null;
    }
    if bool_ok == non_null {
        return ColumnKind::Boolean;
    }
    if int_ok == non_null {
        return ColumnKind::Integer;
    }
    if float_ok >= non_null.saturating_sub(non_null / 10) {
        return ColumnKind::Float;
    }
    ColumnKind::String
}

pub fn parse_csv_text(text: &str, delimiter: Option<char>) -> Result<ParseProfile, String> {
    let delimiter = delimiter.unwrap_or_else(|| detect_delimiter(text));
    let mut rdr = csv::ReaderBuilder::new()
        .delimiter(delimiter as u8)
        .flexible(true)
        .trim(csv::Trim::All)
        .from_reader(text.as_bytes());

    let headers: Vec<String> = rdr
        .headers()
        .map_err(|e| e.to_string())?
        .iter()
        .map(|h| h.trim().trim_start_matches('\u{feff}').to_string())
        .collect();
    if headers.is_empty() {
        return Err("no headers".into());
    }

    let mut sanitized_map: HashMap<String, u32> = HashMap::new();
    let sanitized_headers: Vec<String> = headers
        .iter()
        .map(|h| {
            let base = sanitize_header(h);
            let n = sanitized_map.entry(base.clone()).or_insert(0);
            *n += 1;
            if *n == 1 {
                base
            } else {
                format!("{base}_{n}")
            }
        })
        .collect();

    let mut col_samples: Vec<Vec<String>> = vec![Vec::new(); headers.len()];
    let mut sample_rows: Vec<Vec<String>> = Vec::new();
    let mut quarantined: Vec<QuarantinedRow> = Vec::new();
    let mut row_count = 0u64;

    for result in rdr.records() {
        row_count += 1;
        if row_count > MAX_ROWS as u64 {
            return Err(format!("row count exceeds limit ({MAX_ROWS})"));
        }
        match result {
            Ok(rec) => {
                let mut row = Vec::with_capacity(headers.len());
                for (i, field) in rec.iter().enumerate() {
                    row.push(field.to_string());
                    if col_samples[i].len() < 20 {
                        col_samples[i].push(field.to_string());
                    }
                }
                while row.len() < headers.len() {
                    row.push(String::new());
                }
                if sample_rows.len() < 25 {
                    sample_rows.push(row);
                }
            }
            Err(e) => {
                quarantined.push(QuarantinedRow {
                    row_number: row_count,
                    column: None,
                    raw_value: String::new(),
                    reason: e.to_string(),
                });
            }
        }
    }

    let columns: Vec<ColumnProfile> = headers
        .iter()
        .zip(sanitized_headers.iter())
        .enumerate()
        .map(|(i, (orig, san))| {
            let kind = infer_kind(&col_samples[i]);
            let null_count = col_samples[i].iter().filter(|v| is_null_token(v)).count() as u64;
            ColumnProfile {
                original_name: orig.clone(),
                sanitized_name: san.clone(),
                kind,
                null_count,
                sample_values: col_samples[i].iter().take(5).cloned().collect(),
            }
        })
        .collect();

    Ok(ParseProfile {
        delimiter,
        encoding: String::new(),
        has_bom: false,
        headers,
        sanitized_headers,
        columns,
        row_count,
        quarantined,
        sample_rows,
    })
}

pub fn parse_csv_bytes(
    raw: &[u8],
    delimiter: Option<char>,
) -> Result<(ParseProfile, String), String> {
    if raw.len() > MAX_UPLOAD_BYTES {
        return Err(format!("file exceeds {} byte limit", MAX_UPLOAD_BYTES));
    }
    let (text, encoding, has_bom) = decode_bytes(raw);
    let mut profile = parse_csv_text(&text, delimiter)?;
    profile.encoding = encoding;
    profile.has_bom = has_bom;
    Ok((profile, text))
}

pub fn neutralize_csv_cell(s: &str) -> String {
    let t = s.trim();
    if t.starts_with(['=', '+', '-', '@', '\t', '\r']) {
        format!("'{t}")
    } else {
        s.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detects_tab_delimiter() {
        assert_eq!(detect_delimiter("a\tb\tc\n1\t2\t3"), '\t');
    }

    #[test]
    fn utf8_bom_stripped() {
        let raw = b"\xEF\xBB\xBFtime,kW\n2013-01-01,1.0";
        let (profile, _) = parse_csv_bytes(raw, None).unwrap();
        assert_eq!(profile.headers[0], "time");
    }

    #[test]
    fn duplicate_headers_sanitized() {
        let csv = "Date,Date,kW\n1/1/2013,2/1/2013,1\n";
        let p = parse_csv_text(csv, Some(',')).unwrap();
        assert_eq!(p.sanitized_headers, vec!["date", "date_2", "kw"]);
    }

    #[test]
    fn rejects_path_traversal_filename() {
        assert!(sanitize_filename("../etc/passwd").is_err());
    }
}
