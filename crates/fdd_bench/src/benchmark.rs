use std::path::Path;

use anyhow::Result;
use fdd_core::validate_building;
use fdd_csv::scan_history_csv;
use fdd_rules::{load_registry, run_all_rules};
use fdd_store::ingest_building;
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct BenchmarkReport {
    pub building_id: String,
    pub data_available: bool,
    pub validate_ms: u128,
    pub equipment_count: usize,
    pub csv_scan_ms: u128,
    pub ingest_ms: u128,
    pub ingest_rows: u64,
    pub rules_ms: u128,
    pub rules_run: usize,
    pub rules_succeeded: usize,
    pub rules_failed: usize,
    pub notes: Vec<String>,
}

pub async fn run_benchmark(
    data_root: &Path,
    building_id: &str,
    parquet_out: &Path,
    rules_dir: &Path,
    rule_results_out: &Path,
) -> Result<BenchmarkReport> {
    let mut notes = Vec::new();
    let t0 = std::time::Instant::now();
    let validation = match validate_building(data_root, building_id) {
        Ok(v) => v,
        Err(e) => {
            notes.push(format!("validation blocked: {e}"));
            return Ok(BenchmarkReport {
                building_id: building_id.to_string(),
                data_available: false,
                validate_ms: t0.elapsed().as_millis(),
                equipment_count: 0,
                csv_scan_ms: 0,
                ingest_ms: 0,
                ingest_rows: 0,
                rules_ms: 0,
                rules_run: 0,
                rules_succeeded: 0,
                rules_failed: 0,
                notes,
            });
        }
    };
    let validate_ms = t0.elapsed().as_millis();

    let t1 = std::time::Instant::now();
    if let Some(eq) = validation.equipment.first() {
        let _ = scan_history_csv(Path::new(&eq.history_path), 500)?;
    }
    let csv_scan_ms = t1.elapsed().as_millis();

    let t2 = std::time::Instant::now();
    let ingest = ingest_building(data_root, building_id, parquet_out)?;
    let ingest_ms = t2.elapsed().as_millis();

    let t3 = std::time::Instant::now();
    let registry = load_registry(rules_dir)?;
    let rules = run_all_rules(parquet_out, &registry, rule_results_out).await?;
    let rules_ms = t3.elapsed().as_millis();

    Ok(BenchmarkReport {
        building_id: building_id.to_string(),
        data_available: true,
        validate_ms,
        equipment_count: validation.equipment_count,
        csv_scan_ms,
        ingest_ms,
        ingest_rows: ingest.total_rows,
        rules_ms,
        rules_run: rules.rules_run,
        rules_succeeded: rules.rules_succeeded,
        rules_failed: rules.rules_failed,
        notes,
    })
}
