//! Monthly utility bill CSV loader (vibe20 `meters.load_bill_csv` heuristics).

use std::collections::BTreeMap;
use std::path::Path;

use anyhow::{bail, Context, Result};

/// One validated monthly bill row after alias resolution + month aggregation.
#[derive(Debug, Clone, PartialEq)]
pub struct BillRow {
    /// Calendar month key `YYYY-MM`.
    pub month: String,
    /// Usage in native meter units (kWh or Mcf).
    pub usage: f64,
    pub cost_usd: Option<f64>,
    pub demand_kw: Option<f64>,
}

fn norm_header(h: &str) -> String {
    h.trim().to_ascii_lowercase()
}

fn find_col(cols: &[String], needles: &[&str]) -> Option<usize> {
    cols.iter().position(|c| {
        let lc = norm_header(c);
        needles.iter().all(|n| lc.contains(n))
    })
}

fn parse_f64(raw: &str) -> Option<f64> {
    let t = raw.trim();
    if t.is_empty() {
        return None;
    }
    let cleaned = t.replace(',', "").replace('$', "");
    cleaned.parse::<f64>().ok().filter(|v| v.is_finite())
}

fn month_key(raw: &str) -> Option<String> {
    let p = raw.trim();
    if p.len() >= 7 && p.as_bytes().get(4) == Some(&b'-') {
        return Some(p[..7].to_string());
    }
    if p.len() == 6 && p.chars().all(|c| c.is_ascii_digit()) {
        return Some(format!("{}-{}", &p[0..4], &p[4..6]));
    }
    None
}

/// Load a monthly utility bill summary CSV into tidy rows.
///
/// Heuristic columns (case-insensitive substring):
/// - month: `month` / first column
/// - usage: `kwh` or `usage` (Mcf)
/// - cost: `charges` or `cost`
/// - demand: `billed`+`demand` or `demand`
///
/// Duplicate bill months are summed for usage/cost; demand takes the month max.
pub fn load_bill_csv(path: &Path) -> Result<Vec<BillRow>> {
    let mut rdr = csv::ReaderBuilder::new()
        .flexible(true)
        .trim(csv::Trim::All)
        .from_path(path)
        .with_context(|| format!("open bill CSV {}", path.display()))?;

    let headers: Vec<String> = rdr
        .headers()
        .with_context(|| format!("read headers {}", path.display()))?
        .iter()
        .map(|s| s.to_string())
        .collect();
    if headers.is_empty() {
        bail!("bill CSV {} has no header row", path.display());
    }

    let month_i = find_col(&headers, &["month"]).unwrap_or(0);
    let usage_i = find_col(&headers, &["kwh"])
        .or_else(|| find_col(&headers, &["usage"]))
        .or_else(|| if headers.len() > 1 { Some(1) } else { Some(0) })
        .unwrap();
    let cost_i = find_col(&headers, &["charges"]).or_else(|| find_col(&headers, &["cost"]));
    let demand_i =
        find_col(&headers, &["billed", "demand"]).or_else(|| find_col(&headers, &["demand"]));

    #[derive(Default)]
    struct Acc {
        usage: f64,
        cost: f64,
        has_cost: bool,
        demand: Option<f64>,
    }

    let mut map: BTreeMap<String, Acc> = BTreeMap::new();
    for (row_idx, rec) in rdr.records().enumerate() {
        let rec = rec.with_context(|| format!("row {} in {}", row_idx + 2, path.display()))?;
        let month_raw = rec.get(month_i).unwrap_or("").trim();
        if month_raw.is_empty() {
            continue;
        }
        let Some(month) = month_key(month_raw) else {
            continue;
        };
        let Some(usage) = rec.get(usage_i).and_then(parse_f64) else {
            continue;
        };
        let entry = map.entry(month).or_default();
        entry.usage += usage;
        if let Some(ci) = cost_i {
            if let Some(c) = rec.get(ci).and_then(parse_f64) {
                entry.cost += c;
                entry.has_cost = true;
            }
        }
        if let Some(di) = demand_i {
            if let Some(d) = rec.get(di).and_then(parse_f64) {
                entry.demand = Some(match entry.demand {
                    Some(prev) => prev.max(d),
                    None => d,
                });
            }
        }
    }

    Ok(map
        .into_iter()
        .map(|(month, a)| BillRow {
            month,
            usage: a.usage,
            cost_usd: if a.has_cost { Some(a.cost) } else { None },
            demand_kw: a.demand,
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn loads_electric_style_csv() {
        let mut f = NamedTempFile::new().unwrap();
        writeln!(
            f,
            "Bill Month,kWh Total,Billed Demand (kW),Total Current Charges ($)\n\
             2015-01,1000,50,100.5\n\
             2015-01,200,10,20.0\n\
             2015-02,\"1,500\",60,150"
        )
        .unwrap();
        let rows = load_bill_csv(f.path()).unwrap();
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0].month, "2015-01");
        assert!((rows[0].usage - 1200.0).abs() < 1e-9);
        assert!((rows[0].demand_kw.unwrap() - 50.0).abs() < 1e-9); // max of 50,10
        assert!((rows[0].cost_usd.unwrap() - 120.5).abs() < 1e-9);
        assert_eq!(rows[1].month, "2015-02");
        assert!((rows[1].usage - 1500.0).abs() < 1e-9);
    }

    #[test]
    fn loads_gas_style_csv() {
        let mut f = NamedTempFile::new().unwrap();
        writeln!(
            f,
            "Bill Month,Usage (Mcf),Total Energy Charges ($)\n2016-01,1167.3,6673.46"
        )
        .unwrap();
        let rows = load_bill_csv(f.path()).unwrap();
        assert_eq!(rows.len(), 1);
        assert!((rows[0].usage - 1167.3).abs() < 1e-9);
        assert!(rows[0].demand_kw.is_none());
    }

    #[test]
    fn loads_liberty_fixture_electric() {
        let path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("tests/fixtures/fuel/Liberty_50_100_Electric_Summary.csv");
        if !path.is_file() {
            return;
        }
        let rows = load_bill_csv(&path).unwrap();
        assert!(rows.len() > 12);
        assert!(rows.iter().any(|r| r.month == "2015-01" && r.usage > 0.0));
        assert!(rows.iter().any(|r| r.demand_kw.is_some()));
    }
}
