use std::collections::{HashMap, HashSet};
use std::path::Path;

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MetricRow {
    pub rule_id: Option<String>,
    pub equipment_id: Option<String>,
    pub metric: String,
    pub value: f64,
}

#[derive(Debug, Clone, Deserialize)]
struct OracleRecord {
    rule_id: String,
    equipment_id: String,
    #[serde(default)]
    applicable: bool,
    #[serde(default)]
    missing_roles: Vec<String>,
    #[serde(default)]
    _notes: Option<String>,
    #[serde(default)]
    metrics: HashMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Deserialize)]
struct OracleFile {
    #[serde(default)]
    building_id: Option<String>,
    #[serde(default)]
    records: Vec<OracleRecord>,
    #[serde(default)]
    metrics: Vec<MetricRow>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CompareMismatch {
    pub rule_id: String,
    pub equipment_id: String,
    pub metric: String,
    pub python_value: f64,
    pub sql_value: f64,
    pub delta: f64,
    pub pct_delta: Option<f64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct SkippedRecord {
    pub rule_id: String,
    pub equipment_id: String,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct RuleSummary {
    pub rule_id: String,
    pub pass_count: usize,
    pub fail_count: usize,
    pub skipped_equipment: usize,
    pub max_abs_delta: f64,
    pub max_pct_delta: Option<f64>,
    pub worst_equipment: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct EquipmentSummary {
    pub equipment_id: String,
    pub fail_count: usize,
    pub max_abs_delta: f64,
    pub failed_rules: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CompareReport {
    pub building_id: Option<String>,
    pub rules_compared: usize,
    pub equipment_compared: usize,
    pub pass_count: usize,
    pub fail_count: usize,
    pub skipped_missing_roles: usize,
    pub python_only: usize,
    pub sql_only: usize,
    pub max_abs_delta: f64,
    pub max_pct_delta: Option<f64>,
    pub tolerance: f64,
    pub mismatches: Vec<CompareMismatch>,
    pub skipped: Vec<SkippedRecord>,
    pub rule_summaries: Vec<RuleSummary>,
    pub equipment_summaries: Vec<EquipmentSummary>,
    pub material_failure: bool,
}

pub fn compare_results(
    python_path: &Path,
    sql_path: &Path,
    tolerance: f64,
) -> Result<CompareReport> {
    let oracle = load_oracle(python_path)?;
    let py_metrics = flatten_oracle(&oracle);
    let sql_metrics = load_sql_metrics(sql_path)?;

    let py_keys: HashSet<String> = py_metrics.keys().cloned().collect();
    let sql_keys: HashSet<String> = sql_metrics.keys().cloned().collect();

    let mut rules: HashSet<String> = HashSet::new();
    let mut equipment: HashSet<String> = HashSet::new();
    for key in py_keys.iter().chain(sql_keys.iter()) {
        let parts: Vec<&str> = key.split('|').collect();
        if parts.len() >= 3 {
            rules.insert(parts[0].to_string());
            equipment.insert(parts[1].to_string());
        }
    }

    let mut skipped = Vec::new();
    for rec in &oracle.records {
        if !rec.applicable && !rec.missing_roles.is_empty() {
            skipped.push(SkippedRecord {
                rule_id: rec.rule_id.clone(),
                equipment_id: rec.equipment_id.clone(),
                reason: format!("missing roles: {}", rec.missing_roles.join(", ")),
            });
        }
    }

    let mut pass_count = 0usize;
    let mut fail_count = 0usize;
    let mut mismatches = Vec::new();
    let mut max_abs_delta = 0.0f64;
    let mut max_pct_delta: Option<f64> = None;
    let mut rule_pass: HashMap<String, usize> = HashMap::new();
    let mut rule_fail: HashMap<String, usize> = HashMap::new();
    let mut rule_max_delta: HashMap<String, f64> = HashMap::new();
    let mut rule_max_pct: HashMap<String, f64> = HashMap::new();
    let mut rule_worst_eq: HashMap<String, (String, f64)> = HashMap::new();
    let mut eq_fail: HashMap<String, usize> = HashMap::new();
    let mut eq_max_delta: HashMap<String, f64> = HashMap::new();
    let mut eq_failed_rules: HashMap<String, HashSet<String>> = HashMap::new();

    for key in py_keys.intersection(&sql_keys) {
        let py_val = py_metrics[key];
        let sql_val = sql_metrics[key];
        let delta = (py_val - sql_val).abs();
        let pct = if py_val.abs() > 1e-9 {
            Some(100.0 * delta / py_val.abs())
        } else if sql_val.abs() > 1e-9 {
            Some(100.0 * delta / sql_val.abs())
        } else {
            Some(0.0)
        };
        let parts: Vec<&str> = key.split('|').collect();
        let rule_id = parts[0].to_string();
        let equipment_id = parts[1].to_string();
        if delta <= tolerance {
            pass_count += 1;
            *rule_pass.entry(rule_id.clone()).or_default() += 1;
        } else {
            fail_count += 1;
            *rule_fail.entry(rule_id.clone()).or_default() += 1;
            *eq_fail.entry(equipment_id.clone()).or_default() += 1;
            eq_failed_rules
                .entry(equipment_id.clone())
                .or_default()
                .insert(rule_id.clone());
            mismatches.push(CompareMismatch {
                rule_id: rule_id.clone(),
                equipment_id: equipment_id.clone(),
                metric: parts[2].to_string(),
                python_value: py_val,
                sql_value: sql_val,
                delta,
                pct_delta: pct,
            });
            let prev = rule_max_delta.get(&rule_id).copied().unwrap_or(0.0);
            if delta > prev {
                rule_max_delta.insert(rule_id.clone(), delta);
                rule_worst_eq.insert(rule_id.clone(), (equipment_id.clone(), delta));
            }
            if let Some(p) = pct {
                let prev_p = rule_max_pct.get(&rule_id).copied().unwrap_or(0.0);
                if p > prev_p {
                    rule_max_pct.insert(rule_id.clone(), p);
                }
            }
            let eq_prev = eq_max_delta.get(&equipment_id).copied().unwrap_or(0.0);
            if delta > eq_prev {
                eq_max_delta.insert(equipment_id.clone(), delta);
            }
        }
        max_abs_delta = max_abs_delta.max(delta);
        if let Some(p) = pct {
            max_pct_delta = Some(max_pct_delta.map_or(p, |m| m.max(p)));
        }
    }

    let python_only = py_keys.difference(&sql_keys).count();
    let sql_only = sql_keys.difference(&py_keys).count();

    let py_rules: HashSet<String> = oracle
        .records
        .iter()
        .filter(|r| r.applicable)
        .map(|r| r.rule_id.clone())
        .collect();

    // Fail when Python has applicable outputs but SQL result file is absent
    let sql_dir = if sql_path.is_dir() {
        sql_path.to_path_buf()
    } else {
        sql_path.parent().unwrap_or(sql_path).to_path_buf()
    };
    for rid in &py_rules {
        let has_skip = oracle
            .records
            .iter()
            .any(|r| r.rule_id == *rid && !r.applicable && !r.missing_roles.is_empty());
        if has_skip {
            continue;
        }
        let sql_file = sql_dir.join(format!("{rid}.json"));
        if !sql_file.is_file() {
            skipped.push(SkippedRecord {
                rule_id: rid.clone(),
                equipment_id: "*".into(),
                reason: "SQL result file missing".into(),
            });
            continue;
        }
        if let Ok(text) = std::fs::read_to_string(&sql_file) {
            if let Ok(v) = serde_json::from_str::<serde_json::Value>(&text) {
                if v.get("error").is_some() {
                    skipped.push(SkippedRecord {
                        rule_id: rid.clone(),
                        equipment_id: "*".into(),
                        reason: v["error"].as_str().unwrap_or("sql error").into(),
                    });
                }
            }
        }
    }

    let material_failure = fail_count > 0 || python_only > 0 || sql_only > 0;

    let mut skipped_by_rule: HashMap<String, usize> = HashMap::new();
    for s in &skipped {
        *skipped_by_rule.entry(s.rule_id.clone()).or_default() += 1;
    }

    let rule_summaries = all_rules_from_maps(
        &rule_pass,
        &rule_fail,
        &skipped_by_rule,
        &rule_max_delta,
        &rule_max_pct,
        &rule_worst_eq,
    );

    let mut equipment_summaries: Vec<EquipmentSummary> = eq_fail
        .into_iter()
        .map(|(equipment_id, fail_count)| {
            let mut failed_rules: Vec<String> = eq_failed_rules
                .get(&equipment_id)
                .cloned()
                .unwrap_or_default()
                .into_iter()
                .collect();
            failed_rules.sort();
            EquipmentSummary {
                equipment_id: equipment_id.clone(),
                fail_count,
                max_abs_delta: eq_max_delta.get(&equipment_id).copied().unwrap_or(0.0),
                failed_rules,
            }
        })
        .collect();
    equipment_summaries.sort_by(|a, b| {
        b.max_abs_delta
            .partial_cmp(&a.max_abs_delta)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    Ok(CompareReport {
        building_id: oracle.building_id,
        rules_compared: rules.len(),
        equipment_compared: equipment.len(),
        pass_count,
        fail_count,
        skipped_missing_roles: skipped.len(),
        python_only,
        sql_only,
        max_abs_delta,
        max_pct_delta,
        tolerance,
        mismatches,
        skipped,
        rule_summaries,
        equipment_summaries,
        material_failure,
    })
}

fn all_rules_from_maps(
    rule_pass: &HashMap<String, usize>,
    rule_fail: &HashMap<String, usize>,
    skipped_by_rule: &HashMap<String, usize>,
    rule_max_delta: &HashMap<String, f64>,
    rule_max_pct: &HashMap<String, f64>,
    rule_worst_eq: &HashMap<String, (String, f64)>,
) -> Vec<RuleSummary> {
    let mut all: HashSet<String> = rule_pass.keys().cloned().collect();
    all.extend(rule_fail.keys().cloned());
    all.extend(skipped_by_rule.keys().cloned());
    let mut out: Vec<RuleSummary> = all
        .into_iter()
        .map(|rule_id| RuleSummary {
            pass_count: rule_pass.get(&rule_id).copied().unwrap_or(0),
            fail_count: rule_fail.get(&rule_id).copied().unwrap_or(0),
            skipped_equipment: skipped_by_rule.get(&rule_id).copied().unwrap_or(0),
            max_abs_delta: rule_max_delta.get(&rule_id).copied().unwrap_or(0.0),
            max_pct_delta: rule_max_pct.get(&rule_id).copied(),
            worst_equipment: rule_worst_eq.get(&rule_id).map(|(eq, _)| eq.clone()),
            rule_id,
        })
        .collect();
    out.sort_by(|a, b| {
        b.max_abs_delta
            .partial_cmp(&a.max_abs_delta)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    out
}

pub fn write_compare_markdown(report: &CompareReport, path: &Path) -> Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let mut md = String::new();
    md.push_str("# Rust + DataFusion parity benchmark\n\n");
    md.push_str(&format!(
        "Generated: {}\n\n",
        chrono::Utc::now().format("%Y-%m-%d %H:%M UTC")
    ));
    if let Some(b) = &report.building_id {
        md.push_str(&format!("- building: `{b}`\n"));
    }
    md.push_str(&format!("- tolerance: `{}`\n", report.tolerance));
    md.push_str(&format!("- rules compared: {}\n", report.rules_compared));
    md.push_str(&format!(
        "- equipment compared: {}\n",
        report.equipment_compared
    ));
    md.push_str(&format!("- pass: {}\n", report.pass_count));
    md.push_str(&format!("- fail: {}\n", report.fail_count));
    md.push_str(&format!(
        "- skipped (missing roles): {}\n",
        report.skipped_missing_roles
    ));
    md.push_str(&format!("- python-only keys: {}\n", report.python_only));
    md.push_str(&format!("- sql-only keys: {}\n", report.sql_only));
    md.push_str(&format!("- max abs delta: {:.4}\n", report.max_abs_delta));
    if let Some(p) = report.max_pct_delta {
        md.push_str(&format!("- max pct delta: {:.2}%\n", p));
    }
    md.push_str(&format!(
        "- material failure: {}\n\n",
        report.material_failure
    ));

    md.push_str("## Summary by rule\n\n");
    md.push_str("| rule | pass | fail | skipped | max Δ | max % | worst equipment |\n");
    md.push_str("| --- | ---: | ---: | ---: | ---: | ---: | --- |\n");
    for rs in &report.rule_summaries {
        md.push_str(&format!(
            "| {} | {} | {} | {} | {:.3} | {} | {} |\n",
            rs.rule_id,
            rs.pass_count,
            rs.fail_count,
            rs.skipped_equipment,
            rs.max_abs_delta,
            rs.max_pct_delta
                .map(|p| format!("{:.1}%", p))
                .unwrap_or_else(|| "-".into()),
            rs.worst_equipment.as_deref().unwrap_or("-")
        ));
    }

    if !report.equipment_summaries.is_empty() {
        md.push_str("\n## Summary by equipment (failures only)\n\n");
        md.push_str("| equipment | failed rules | fail metrics | max Δ |\n");
        md.push_str("| --- | --- | ---: | ---: |\n");
        for es in report.equipment_summaries.iter().take(30) {
            md.push_str(&format!(
                "| {} | {} | {} | {:.3} |\n",
                es.equipment_id,
                es.failed_rules.join(", "),
                es.fail_count,
                es.max_abs_delta
            ));
        }
    }

    let mut by_abs = report.mismatches.clone();
    by_abs.sort_by(|a, b| {
        b.delta
            .partial_cmp(&a.delta)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    if !by_abs.is_empty() {
        md.push_str("\n## Top 20 mismatches (absolute delta)\n\n");
        md.push_str("| rule | equipment | metric | python | sql | delta | pct |\n");
        md.push_str("| --- | --- | --- | ---: | ---: | ---: | ---: |\n");
        for m in by_abs.iter().take(20) {
            md.push_str(&format!(
                "| {} | {} | {} | {:.3} | {:.3} | {:.3} | {} |\n",
                m.rule_id,
                m.equipment_id,
                m.metric,
                m.python_value,
                m.sql_value,
                m.delta,
                m.pct_delta
                    .map(|p| format!("{:.1}%", p))
                    .unwrap_or_else(|| "-".into())
            ));
        }
    }

    let mut by_pct = report.mismatches.clone();
    by_pct.sort_by(|a, b| {
        let pa = a.pct_delta.unwrap_or(0.0);
        let pb = b.pct_delta.unwrap_or(0.0);
        pb.partial_cmp(&pa).unwrap_or(std::cmp::Ordering::Equal)
    });
    if !by_pct.is_empty() {
        md.push_str("\n## Top 20 mismatches (percent delta)\n\n");
        md.push_str("| rule | equipment | metric | python | sql | delta | pct |\n");
        md.push_str("| --- | --- | --- | ---: | ---: | ---: | ---: |\n");
        for m in by_pct.iter().take(20) {
            md.push_str(&format!(
                "| {} | {} | {} | {:.3} | {:.3} | {:.3} | {} |\n",
                m.rule_id,
                m.equipment_id,
                m.metric,
                m.python_value,
                m.sql_value,
                m.delta,
                m.pct_delta
                    .map(|p| format!("{:.1}%", p))
                    .unwrap_or_else(|| "-".into())
            ));
        }
    }

    let near_pct = 5.0f64;
    let near_abs = report.tolerance;
    let mut proven = Vec::new();
    let mut near = Vec::new();
    let mut material = Vec::new();
    let mut skipped_rules = Vec::new();
    let mut proxy = Vec::new();
    for rs in &report.rule_summaries {
        if rs.skipped_equipment > 0 && rs.fail_count == 0 && rs.pass_count == 0 {
            skipped_rules.push(rs.rule_id.clone());
        } else if rs.fail_count == 0 && rs.pass_count > 0 {
            proven.push(rs.rule_id.clone());
        } else if rs.fail_count > 0
            && rs.max_abs_delta <= near_abs
            && rs.max_pct_delta.map(|p| p <= near_pct).unwrap_or(true)
        {
            near.push(rs.rule_id.clone());
        } else if rs.fail_count > 0 {
            material.push(rs.rule_id.clone());
        }
        if rs.rule_id.contains("OAT-METEO") && rs.fail_count > 0 {
            proxy.push(rs.rule_id.clone());
        }
    }

    md.push_str("\n## Proven parity\n\n");
    if proven.is_empty() {
        md.push_str("_None yet at current tolerance._\n");
    } else {
        for r in proven {
            md.push_str(&format!("- `{r}`\n"));
        }
    }

    md.push_str("\n## Near parity\n\n");
    if near.is_empty() {
        md.push_str("_None._\n");
    } else {
        for r in near {
            md.push_str(&format!("- `{r}`\n"));
        }
    }

    md.push_str("\n## Material mismatch\n\n");
    if material.is_empty() {
        md.push_str("_None._\n");
    } else {
        for r in material {
            md.push_str(&format!("- `{r}`\n"));
        }
    }

    md.push_str("\n## Skipped due to missing roles\n\n");
    if report.skipped.is_empty() {
        md.push_str("_None._\n");
    } else {
        for s in report.skipped.iter().take(50) {
            md.push_str(&format!(
                "- `{}` / `{}`: {}\n",
                s.rule_id, s.equipment_id, s.reason
            ));
        }
    }

    md.push_str("\n## Proxy / partial implementation\n\n");
    md.push_str(
        "- Review registry `parity_status` and blockers for rules not yet oracle-aligned.\n",
    );
    if !proxy.is_empty() {
        for r in proxy {
            md.push_str(&format!("- `{r}` (weather/threshold proxy path)\n"));
        }
    }

    if !report.mismatches.is_empty() {
        md.push_str("\n## All mismatches\n\n");
        md.push_str("| rule | equipment | metric | python | sql | delta | pct |\n");
        md.push_str("| --- | --- | --- | ---: | ---: | ---: | ---: |\n");
        for m in report.mismatches.iter().take(100) {
            md.push_str(&format!(
                "| {} | {} | {} | {:.3} | {:.3} | {:.3} | {} |\n",
                m.rule_id,
                m.equipment_id,
                m.metric,
                m.python_value,
                m.sql_value,
                m.delta,
                m.pct_delta
                    .map(|p| format!("{:.1}%", p))
                    .unwrap_or_else(|| "-".into())
            ));
        }
        if report.mismatches.len() > 100 {
            md.push_str(&format!("\n… and {} more\n", report.mismatches.len() - 100));
        }
    }

    std::fs::write(path, md)?;
    Ok(())
}

fn load_oracle(path: &Path) -> Result<OracleFile> {
    let text = std::fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    Ok(serde_json::from_str(&text)?)
}

fn flatten_oracle(oracle: &OracleFile) -> HashMap<String, f64> {
    let mut out = HashMap::new();
    if !oracle.metrics.is_empty() {
        for row in &oracle.metrics {
            if let (Some(rid), Some(eq)) = (&row.rule_id, &row.equipment_id) {
                out.insert(metric_key(rid, eq, &row.metric), row.value);
            }
        }
        return out;
    }
    for rec in &oracle.records {
        if !rec.applicable {
            continue;
        }
        for (metric, val) in &rec.metrics {
            if let Some(v) = val.as_f64() {
                out.insert(metric_key(&rec.rule_id, &rec.equipment_id, metric), v);
            }
        }
    }
    out
}

fn load_sql_metrics(sql_path: &Path) -> Result<HashMap<String, f64>> {
    let mut out = HashMap::new();
    if sql_path.is_dir() {
        for entry in std::fs::read_dir(sql_path)? {
            let entry = entry?;
            let path = entry.path();
            if path.extension().and_then(|s| s.to_str()) != Some("json") {
                continue;
            }
            let rule_id = path
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("unknown")
                .to_string();
            merge_sql_file(&mut out, &rule_id, &path)?;
        }
        return Ok(out);
    }
    let rule_id = sql_path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown")
        .to_string();
    merge_sql_file(&mut out, &rule_id, sql_path)?;
    Ok(out)
}

fn merge_sql_file(out: &mut HashMap<String, f64>, rule_id: &str, path: &Path) -> Result<()> {
    let text = std::fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    let parsed: serde_json::Value = serde_json::from_str(&text)?;
    let rows = if parsed.is_array() {
        parsed.as_array().context("array rows")?
    } else {
        parsed
            .get("rows")
            .and_then(|v| v.as_array())
            .context("sql result missing rows array")?
    };
    for row in rows {
        let eq = row
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");
        let obj = row.as_object().context("row not object")?;
        for (col, val) in obj {
            if col == "equipment_id" {
                continue;
            }
            if let Some(v) = val.as_f64() {
                out.insert(metric_key(rule_id, eq, col), v);
            }
        }
    }
    Ok(())
}

fn metric_key(rule_id: &str, equipment_id: &str, metric: &str) -> String {
    format!("{rule_id}|{equipment_id}|{metric}")
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn compare_within_tolerance() {
        let tmp = TempDir::new().unwrap();
        let oracle_path = tmp.path().join("oracle.json");
        let sql_dir = tmp.path().join("sql");
        std::fs::create_dir_all(&sql_dir).unwrap();

        let oracle = r#"{
            "building_id": "B1",
            "records": [{
                "rule_id": "FAN-RUNTIME-HOURS",
                "equipment_id": "AHU_1",
                "applicable": true,
                "metrics": {"fan_runtime_hours": 10.0}
            }],
            "metrics": [{"rule_id": "FAN-RUNTIME-HOURS", "equipment_id": "AHU_1", "metric": "fan_runtime_hours", "value": 10.0}]
        }"#;
        std::fs::write(&oracle_path, oracle).unwrap();
        std::fs::write(
            sql_dir.join("FAN-RUNTIME-HOURS.json"),
            r#"{"rows":[{"equipment_id":"AHU_1","fan_runtime_hours":10.01}]}"#,
        )
        .unwrap();

        let report = compare_results(&oracle_path, &sql_dir, 0.1).unwrap();
        assert!(!report.material_failure);
        assert_eq!(report.pass_count, 1);
    }

    #[test]
    fn compare_detects_mismatch() {
        let tmp = TempDir::new().unwrap();
        let oracle_path = tmp.path().join("oracle.json");
        let sql_dir = tmp.path().join("sql");
        std::fs::create_dir_all(&sql_dir).unwrap();
        std::fs::write(
            &oracle_path,
            r#"{"metrics":[{"rule_id":"VAV-1","equipment_id":"VAV_1","metric":"fault_hours","value":5.0}]}"#,
        )
        .unwrap();
        std::fs::write(
            sql_dir.join("VAV-1.json"),
            r#"{"rows":[{"equipment_id":"VAV_1","fault_hours":10.0}]}"#,
        )
        .unwrap();
        let report = compare_results(&oracle_path, &sql_dir, 0.5).unwrap();
        assert!(report.material_failure);
        assert_eq!(report.fail_count, 1);
    }
}
