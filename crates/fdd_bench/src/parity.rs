//! Parity harness: compare Vibe19 oracle artifacts (CSV/JSON) to Open-FDD rule results.

use std::collections::{BTreeSet, HashMap};
use std::path::Path;

use anyhow::{Context, Result};
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct ParityCell {
    pub rule_id: String,
    pub equipment_id: String,
    pub metric: String,
    pub oracle: Option<f64>,
    pub openfdd: Option<f64>,
    pub status_oracle: Option<String>,
    pub status_openfdd: Option<String>,
    pub delta: Option<f64>,
    pub within_tolerance: bool,
    pub class: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ParitySummary {
    pub openfdd_git_sha: String,
    pub vibe19_git_sha: String,
    pub oracle_dir: String,
    pub sql_results_dir: String,
    pub tolerance_hours: f64,
    pub compared_cells: usize,
    pub exact_status_matches: usize,
    pub status_mismatches: usize,
    pub numeric_within_tolerance: usize,
    pub numeric_mismatches: usize,
    pub openfdd_only_rules: Vec<String>,
    pub vibe19_only_rules: Vec<String>,
    pub comparable_rules: Vec<String>,
    pub max_abs_delta: f64,
    pub pass: bool,
}

#[derive(Debug, Clone)]
struct DigestRow {
    rule_id: String,
    equipment_id: String,
    status: String,
    fault_hours: f64,
}

/// Overlap classification for Phase 1 honest comparison.
pub fn overlap_class(rule_id: &str) -> &'static str {
    match rule_id {
        // Proven historical BUILDING_100 SQL parity set
        "FC1" | "FC2" | "FC3" | "FC8" | "FC9" | "FC10" | "FC11" | "FC12" | "FC13-SAT-HIGH"
        | "ECON-1" | "ECON-2" | "ECON-4" | "VAV-1" | "OAT-METEO" | "FAN-RUNTIME-HOURS"
        | "ZONE-COMFORT-PCT" | "AVG-ZONE-TEMP" | "FAULT-ELAPSED-HOURS" => "exact_direct_equivalent",
        "PID-HUNT-1" => "openfdd_only",
        _ if rule_id.starts_with("SV-")
            || rule_id.starts_with("CHW-")
            || rule_id.starts_with("TRIM-")
            || rule_id.starts_with("WX-")
            || rule_id.starts_with("VAV-")
            || rule_id.starts_with("FC")
            || rule_id.starts_with("ECON")
            || rule_id == "OA-1"
            || rule_id == "DMP-1"
            || rule_id == "SCHED-1"
            || rule_id == "CMD-1"
            || rule_id == "VLV-1"
            || rule_id == "HP-1"
            || rule_id.starts_with("AHU-") =>
        {
            "equivalent_after_normalization"
        }
        _ => "not_yet_comparable",
    }
}

fn parse_rule_digest_csv(path: &Path) -> Result<Vec<DigestRow>> {
    let mut rdr = csv::Reader::from_path(path)
        .with_context(|| format!("read oracle digest {}", path.display()))?;
    let mut out = Vec::new();
    for row in rdr.deserialize::<HashMap<String, String>>() {
        let row = row?;
        out.push(DigestRow {
            rule_id: normalize_rule_id(row.get("rule_id").map(|s| s.as_str()).unwrap_or("")),
            equipment_id: row.get("equipment_id").cloned().unwrap_or_default(),
            status: row.get("status").cloned().unwrap_or_default(),
            fault_hours: row
                .get("fault_hours")
                .and_then(|s| s.parse().ok())
                .unwrap_or(0.0),
        });
    }
    Ok(out)
}

fn load_openfdd_results(dir: &Path) -> Result<Vec<DigestRow>> {
    let mut out = Vec::new();
    if !dir.is_dir() {
        anyhow::bail!("sql results dir missing: {}", dir.display());
    }
    for entry in std::fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) != Some("json") {
            continue;
        }
        let rule_id = path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("")
            .to_string();
        let text = std::fs::read_to_string(&path)?;
        let v: serde_json::Value = serde_json::from_str(&text)?;
        let rows = v.get("rows").and_then(|r| r.as_array()).cloned().unwrap_or_default();
        for row in rows {
            let status = row
                .get("status")
                .and_then(|s| s.as_str())
                .unwrap_or_else(|| v.get("status").and_then(|s| s.as_str()).unwrap_or(""))
                .to_string();
            // Skip non-applicable for numeric compare unless oracle also has them
            let equipment_id = row
                .get("equipment_id")
                .and_then(|s| s.as_str())
                .unwrap_or("")
                .to_string();
            let fault_hours = row.get("fault_hours").and_then(|x| x.as_f64());
            out.push(DigestRow {
                rule_id: normalize_rule_id(&rule_id),
                equipment_id,
                status,
                fault_hours: fault_hours.unwrap_or(0.0),
            });
        }
    }
    Ok(out)
}

pub fn run_parity(
    oracle_dir: &Path,
    sql_results_dir: &Path,
    output_dir: &Path,
    tolerance_hours: f64,
    openfdd_git_sha: &str,
    vibe19_git_sha: &str,
) -> Result<ParitySummary> {
    std::fs::create_dir_all(output_dir)?;
    let digest_path = oracle_dir.join("rule_digest.csv");
    let oracle_rows = if digest_path.is_file() {
        parse_rule_digest_csv(&digest_path)?
    } else {
        Vec::new()
    };
    let ofdd_rows = load_openfdd_results(sql_results_dir)?;

    let oracle_rules: BTreeSet<String> = oracle_rows.iter().map(|r| r.rule_id.clone()).collect();
    let ofdd_rules: BTreeSet<String> = ofdd_rows.iter().map(|r| r.rule_id.clone()).collect();
    let comparable: Vec<String> = oracle_rules
        .intersection(&ofdd_rules)
        .filter(|r| overlap_class(r) != "not_yet_comparable" && overlap_class(r) != "openfdd_only")
        .cloned()
        .collect();
    let openfdd_only: Vec<String> = ofdd_rules.difference(&oracle_rules).cloned().collect();
    let vibe19_only: Vec<String> = oracle_rules.difference(&ofdd_rules).cloned().collect();

    let oracle_map: HashMap<(String, String), &DigestRow> = oracle_rows
        .iter()
        .map(|r| ((r.rule_id.clone(), r.equipment_id.clone()), r))
        .collect();
    let ofdd_map: HashMap<(String, String), &DigestRow> = ofdd_rows
        .iter()
        .map(|r| ((r.rule_id.clone(), r.equipment_id.clone()), r))
        .collect();

    let mut cells = Vec::new();
    let mut exact_status = 0usize;
    let mut status_mismatch = 0usize;
    let mut num_ok = 0usize;
    let mut num_bad = 0usize;
    let mut max_abs = 0.0f64;

    for rule in &comparable {
        let equips: BTreeSet<String> = oracle_rows
            .iter()
            .filter(|r| &r.rule_id == rule)
            .map(|r| r.equipment_id.clone())
            .collect();
        for equip in equips {
            let key = (rule.clone(), equip.clone());
            let o = oracle_map.get(&key);
            let s = ofdd_map.get(&key);
            let status_o = o.map(|r| r.status.clone());
            let status_s = s.map(|r| r.status.clone());
            let status_match = match (&status_o, &status_s) {
                (Some(a), Some(b)) => normalize_status(a) == normalize_status(b),
                _ => false,
            };
            if status_match {
                exact_status += 1;
            } else if status_o.is_some() && status_s.is_some() {
                status_mismatch += 1;
            }

            let oh = o.map(|r| r.fault_hours);
            let sh = s.and_then(|r| {
                // Do not compare fault hours for skips / N/A
                let st = normalize_status(&r.status);
                if st.starts_with("SKIPPED") || st == "NOT_APPLICABLE_EQUIPMENT_TYPE" || st == "ERROR"
                {
                    None
                } else {
                    Some(r.fault_hours)
                }
            });
            let delta = match (oh, sh) {
                (Some(a), Some(b)) => Some((a - b).abs()),
                _ => None,
            };
            if let Some(d) = delta {
                max_abs = max_abs.max(d);
                if d <= tolerance_hours {
                    num_ok += 1;
                } else {
                    num_bad += 1;
                }
            }
            cells.push(ParityCell {
                rule_id: rule.clone(),
                equipment_id: equip,
                metric: "fault_hours".into(),
                oracle: oh,
                openfdd: sh,
                status_oracle: status_o,
                status_openfdd: status_s,
                delta,
                within_tolerance: delta.map(|d| d <= tolerance_hours).unwrap_or(status_match),
                class: overlap_class(rule).into(),
            });
        }
    }

    let pass = status_mismatch == 0 && num_bad == 0;
    let summary = ParitySummary {
        openfdd_git_sha: openfdd_git_sha.into(),
        vibe19_git_sha: vibe19_git_sha.into(),
        oracle_dir: oracle_dir.display().to_string(),
        sql_results_dir: sql_results_dir.display().to_string(),
        tolerance_hours,
        compared_cells: cells.len(),
        exact_status_matches: exact_status,
        status_mismatches: status_mismatch,
        numeric_within_tolerance: num_ok,
        numeric_mismatches: num_bad,
        openfdd_only_rules: openfdd_only,
        vibe19_only_rules: vibe19_only,
        comparable_rules: comparable,
        max_abs_delta: max_abs,
        pass,
    };

    std::fs::write(
        output_dir.join("parity_summary.json"),
        serde_json::to_string_pretty(&summary)?,
    )?;
    write_details_csv(&output_dir.join("parity_details.csv"), &cells)?;
    write_report_md(&output_dir.join("parity_report.md"), &summary, &cells)?;

    // Copy pointer to results
    let results_link = output_dir.join("openfdd_results");
    let _ = std::fs::remove_dir_all(&results_link);
    // Best-effort directory copy of JSON results
    copy_dir_json(sql_results_dir, &results_link)?;

    Ok(summary)
}

fn normalize_rule_id(rule_id: &str) -> String {
    match rule_id {
        "FC13" => "FC13-SAT-HIGH".into(),
        "AHU-SIMUL" => "AHU-SIMUL-HEAT-COOL".into(),
        "VAV-REHEAT" => "VAV-REHEAT-STUCK".into(),
        other => other.to_string(),
    }
}

fn normalize_status(s: &str) -> String {
    let u = s.trim().to_ascii_uppercase();
    match u.as_str() {
        "OK" | "PASS" => "PASS".into(),
        "FAIL" | "FAULT" | "FAILED" => "FAULT".into(),
        other => other.to_string(),
    }
}

fn write_details_csv(path: &Path, cells: &[ParityCell]) -> Result<()> {
    let mut wtr = csv::Writer::from_path(path)?;
    wtr.write_record([
        "rule_id",
        "equipment_id",
        "metric",
        "oracle",
        "openfdd",
        "status_oracle",
        "status_openfdd",
        "delta",
        "within_tolerance",
        "class",
    ])?;
    for c in cells {
        wtr.write_record([
            c.rule_id.as_str(),
            c.equipment_id.as_str(),
            c.metric.as_str(),
            &c.oracle.map(|v| v.to_string()).unwrap_or_default(),
            &c.openfdd.map(|v| v.to_string()).unwrap_or_default(),
            c.status_oracle.as_deref().unwrap_or(""),
            c.status_openfdd.as_deref().unwrap_or(""),
            &c.delta.map(|v| v.to_string()).unwrap_or_default(),
            if c.within_tolerance { "true" } else { "false" },
            c.class.as_str(),
        ])?;
    }
    wtr.flush()?;
    Ok(())
}

fn write_report_md(path: &Path, summary: &ParitySummary, cells: &[ParityCell]) -> Result<()> {
    let mut md = String::new();
    md.push_str("# Open-FDD ↔ Vibe19 parity report\n\n");
    md.push_str(&format!("- Open-FDD SHA: `{}`\n", summary.openfdd_git_sha));
    md.push_str(&format!("- Vibe19 SHA: `{}`\n", summary.vibe19_git_sha));
    md.push_str(&format!("- tolerance_hours: {}\n", summary.tolerance_hours));
    md.push_str(&format!("- pass: **{}**\n", summary.pass));
    md.push_str(&format!("- compared_cells: {}\n", summary.compared_cells));
    md.push_str(&format!(
        "- status matches/mismatches: {} / {}\n",
        summary.exact_status_matches, summary.status_mismatches
    ));
    md.push_str(&format!(
        "- numeric within/mismatch: {} / {}\n",
        summary.numeric_within_tolerance, summary.numeric_mismatches
    ));
    md.push_str(&format!("- max_abs_delta: {:.4}\n\n", summary.max_abs_delta));
    md.push_str("## Comparable rules\n\n");
    for r in &summary.comparable_rules {
        md.push_str(&format!("- `{}` ({})\n", r, overlap_class(r)));
    }
    md.push_str("\n## Worst deltas\n\n");
    let mut worst: Vec<_> = cells
        .iter()
        .filter(|c| c.delta.is_some())
        .collect();
    worst.sort_by(|a, b| {
        b.delta
            .unwrap_or(0.0)
            .partial_cmp(&a.delta.unwrap_or(0.0))
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    for c in worst.iter().take(20) {
        md.push_str(&format!(
            "- {} / {} Δ={:.4} (oracle={:?} openfdd={:?}) statuses {:?}/{:?}\n",
            c.rule_id,
            c.equipment_id,
            c.delta.unwrap_or(0.0),
            c.oracle,
            c.openfdd,
            c.status_oracle,
            c.status_openfdd
        ));
    }
    std::fs::write(path, md)?;
    Ok(())
}

fn copy_dir_json(src: &Path, dst: &Path) -> Result<()> {
    std::fs::create_dir_all(dst)?;
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        let p = entry.path();
        if p.extension().and_then(|e| e.to_str()) == Some("json") {
            let name = p.file_name().unwrap();
            std::fs::copy(&p, dst.join(name))?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::TempDir;

    #[test]
    fn parity_detects_status_and_numeric_deltas() {
        let tmp = TempDir::new().unwrap();
        let oracle = tmp.path().join("oracle");
        let results = tmp.path().join("results");
        let out = tmp.path().join("out");
        std::fs::create_dir_all(&oracle).unwrap();
        std::fs::create_dir_all(&results).unwrap();
        let mut f = std::fs::File::create(oracle.join("rule_digest.csv")).unwrap();
        writeln!(
            f,
            "equipment_id,equipment_type,fault_hours,fault_pct,fault_sample_count,gate_applied,gate_kind,gate_source,rule_id,sample_count,status"
        )
        .unwrap();
        writeln!(
            f,
            "AHU_1,AHU,1.0,0,0,False,always,disabled,FC8,10,FAULT"
        )
        .unwrap();
        writeln!(
            f,
            "AHU_1,AHU,0.0,0,0,False,always,disabled,FC3,10,PASS"
        )
        .unwrap();
        std::fs::write(
            results.join("FC8.json"),
            r#"{"status":"FAULT","rows":[{"equipment_id":"AHU_1","status":"FAULT","fault_hours":1.2}]}"#,
        )
        .unwrap();
        std::fs::write(
            results.join("FC3.json"),
            r#"{"status":"PASS","rows":[{"equipment_id":"AHU_1","status":"PASS","fault_hours":0.0}]}"#,
        )
        .unwrap();
        let summary = run_parity(&oracle, &results, &out, 0.5, "testsha", "vibe19").unwrap();
        assert!(out.join("parity_summary.json").is_file());
        assert!(out.join("parity_details.csv").is_file());
        assert!(out.join("parity_report.md").is_file());
        assert_eq!(summary.status_mismatches, 0);
        assert!(summary.numeric_within_tolerance >= 1);
        assert!(summary.pass);
    }
}
