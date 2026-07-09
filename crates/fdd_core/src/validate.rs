use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use walkdir::WalkDir;

use crate::error::{CoreError, Result};
use crate::models::{EquipmentHistory, HistoryManifest, PollInterval};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationReport {
    pub building_id: String,
    pub building_root: String,
    pub grid_minutes: u32,
    pub effective_poll_seconds: u32,
    pub equipment_count: usize,
    pub point_count: usize,
    pub estimated_total_rows: u64,
    pub errors: Vec<String>,
    pub warnings: Vec<String>,
    pub equipment: Vec<EquipmentHistory>,
}

pub fn validate_building(data_root: &Path, building_id: &str) -> Result<ValidationReport> {
    let building_root = data_root.join(building_id);
    if !building_root.is_dir() {
        return Err(CoreError::MissingFile(building_root.display().to_string()));
    }

    let manifest_path = building_root.join("manifest.json");
    if !manifest_path.is_file() {
        return Err(CoreError::MissingFile(manifest_path.display().to_string()));
    }

    let manifest_text = std::fs::read_to_string(&manifest_path)?;
    let manifest: HistoryManifest = serde_json::from_str(&manifest_text)?;
    if manifest.grid_minutes == 0 {
        return Err(CoreError::Validation(
            "manifest.json grid_minutes must be > 0".into(),
        ));
    }
    let poll = PollInterval::from_grid_minutes(manifest.grid_minutes);

    let mut errors = Vec::new();
    let mut warnings = Vec::new();
    let mut equipment = Vec::new();
    let mut point_count = 0usize;
    let mut estimated_total_rows = 0u64;

    for entry in discover_equipment_dirs(&building_root) {
        let eq_id = entry
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("unknown")
            .to_string();
        let columns_path = entry.join("columns.csv");
        let history_path = entry.join("history_wide.csv");

        if !columns_path.is_file() {
            errors.push(format!("{eq_id}: missing columns.csv"));
            continue;
        }
        if !history_path.is_file() {
            errors.push(format!("{eq_id}: missing history_wide.csv"));
            continue;
        }

        let cols = read_columns_csv(&columns_path)?;
        point_count += cols;
        let rows = estimate_csv_rows(&history_path)?;
        estimated_total_rows += rows;

        if !history_has_timestamp_header(&history_path)? {
            errors.push(format!(
                "{eq_id}: history_wide.csv missing timestamp_utc column"
            ));
        }

        equipment.push(EquipmentHistory {
            equipment_id: eq_id,
            history_path: history_path.display().to_string(),
            columns_path: columns_path.display().to_string(),
            point_count: cols,
            estimated_rows: Some(rows),
            poll_interval: poll,
        });
    }

    if equipment.is_empty() {
        warnings.push("no equipment folders with history_wide.csv found".into());
    }

    Ok(ValidationReport {
        building_id: building_id.to_string(),
        building_root: building_root.display().to_string(),
        grid_minutes: manifest.grid_minutes,
        effective_poll_seconds: poll.effective_poll_seconds,
        equipment_count: equipment.len(),
        point_count,
        estimated_total_rows,
        errors,
        warnings,
        equipment,
    })
}

fn discover_equipment_dirs(building_root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    if let Ok(rd) = std::fs::read_dir(building_root) {
        for entry in rd.flatten() {
            let path = entry.path();
            if path.is_dir() && path.join("history_wide.csv").is_file() {
                out.push(path);
            }
        }
    }
    // VAV nested layout: VAV/VAV_1/history_wide.csv
    for e in WalkDir::new(building_root)
        .min_depth(2)
        .max_depth(3)
        .into_iter()
        .flatten()
    {
        if e.file_type().is_dir() && e.path().join("history_wide.csv").is_file() {
            let p = e.path().to_path_buf();
            if !out.iter().any(|x| x == &p) {
                out.push(p);
            }
        }
    }
    out.sort();
    out
}

fn read_columns_csv(path: &Path) -> Result<usize> {
    let mut rdr = csv::Reader::from_path(path)?;
    let count = rdr.records().count();
    Ok(count)
}

fn estimate_csv_rows(path: &Path) -> Result<u64> {
    let meta = std::fs::metadata(path)?;
    // Rough estimate: ~80 bytes/row for wide HVAC exports
    Ok((meta.len() / 80).max(1))
}

fn history_has_timestamp_header(path: &Path) -> Result<bool> {
    let mut rdr = csv::ReaderBuilder::new()
        .has_headers(true)
        .from_path(path)?;
    Ok(rdr
        .headers()?
        .iter()
        .any(|h| h == "timestamp_utc" || h == "timestamp"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::TempDir;

    fn write_fixture(dir: &Path) {
        std::fs::write(dir.join("manifest.json"), r#"{"grid_minutes": 5}"#).unwrap();
        let ahu = dir.join("AHU_1");
        std::fs::create_dir_all(&ahu).unwrap();
        std::fs::write(
            ahu.join("columns.csv"),
            "column,point_role,point_name,units\noutside_air_temp_f,oat,OAT,F\n",
        )
        .unwrap();
        let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,outside_air_temp_f").unwrap();
        writeln!(f, "2026-01-01T00:00:00Z,65.0").unwrap();
        writeln!(f, "2026-01-01T00:05:00Z,66.0").unwrap();
    }

    #[test]
    fn validate_building_ok() {
        let tmp = TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_100");
        std::fs::create_dir_all(&building).unwrap();
        write_fixture(&building);
        let report = validate_building(tmp.path(), "BUILDING_100").unwrap();
        assert_eq!(report.equipment_count, 1);
        assert_eq!(report.grid_minutes, 5);
        assert_eq!(report.effective_poll_seconds, 300);
        assert!(report.errors.is_empty());
    }

    #[test]
    fn missing_timestamp_fails() {
        let tmp = TempDir::new().unwrap();
        let building = tmp.path().join("B1");
        std::fs::create_dir_all(&building).unwrap();
        std::fs::write(building.join("manifest.json"), r#"{"grid_minutes": 15}"#).unwrap();
        let eq = building.join("AHU_1");
        std::fs::create_dir_all(&eq).unwrap();
        std::fs::write(eq.join("columns.csv"), "column\nx\n").unwrap();
        std::fs::write(eq.join("history_wide.csv"), "bad_col\n1\n").unwrap();
        let report = validate_building(tmp.path(), "B1").unwrap();
        assert!(!report.errors.is_empty());
    }
}
