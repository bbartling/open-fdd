//! Legacy historian migration discovery and dry-run planning.
//!
//! H6 must never invent building/equipment identity while converting old
//! historian artifacts into the canonical monthly Hive layout. This module is
//! deliberately conservative: a source is eligible only when both identities
//! are present as trusted legacy path segments (`building=<id>/equipment=<id>`)
//! and pass the same partition-value validation used by the canonical writer.

use std::fs;
use std::path::Path;

use anyhow::{Context, Result};
use serde::Serialize;

use crate::safe_partition_value;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LegacyHistorianFormat {
    Parquet,
    Jsonl,
    Feather,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct LegacyHistorianCandidate {
    pub path: String,
    pub format: LegacyHistorianFormat,
    pub building_id: Option<String>,
    pub equipment_id: Option<String>,
    pub eligible: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct MigrationInventory {
    pub root: String,
    pub candidates: Vec<LegacyHistorianCandidate>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct MigrationDryRunReport {
    pub root: String,
    pub recognized_files: usize,
    pub eligible_files: usize,
    pub parquet_files: usize,
    pub jsonl_files: usize,
    pub feather_files: usize,
    pub candidates: Vec<LegacyHistorianCandidate>,
}

impl MigrationInventory {
    pub fn dry_run_report(&self) -> MigrationDryRunReport {
        let mut parquet_files = 0usize;
        let mut jsonl_files = 0usize;
        let mut feather_files = 0usize;
        let mut eligible_files = 0usize;
        for candidate in &self.candidates {
            match candidate.format {
                LegacyHistorianFormat::Parquet => parquet_files += 1,
                LegacyHistorianFormat::Jsonl => jsonl_files += 1,
                LegacyHistorianFormat::Feather => feather_files += 1,
            }
            if candidate.eligible {
                eligible_files += 1;
            }
        }
        MigrationDryRunReport {
            root: self.root.clone(),
            recognized_files: self.candidates.len(),
            eligible_files,
            parquet_files,
            jsonl_files,
            feather_files,
            candidates: self.candidates.clone(),
        }
    }
}

/// Discover legacy historian artifacts recursively without reading their data.
///
/// Recognized source formats are Parquet, JSONL/NDJSON, and Feather/Arrow IPC.
/// Eligibility is intentionally stricter than recognition: both trusted legacy
/// identity path segments must be present and safe, and legacy Parquet must use
/// the historical `history.parquet` filename. JSONL/Feather sources are merely
/// classified here; their content conversion is a later H6 step.
pub fn discover_legacy_historian(root: &Path) -> Result<MigrationInventory> {
    let mut candidates = Vec::new();
    if root.exists() {
        walk(root, &mut candidates)?;
    }
    candidates.sort_by(|a, b| a.path.cmp(&b.path));
    Ok(MigrationInventory {
        root: root.display().to_string(),
        candidates,
    })
}

fn walk(dir: &Path, out: &mut Vec<LegacyHistorianCandidate>) -> Result<()> {
    for entry in fs::read_dir(dir).with_context(|| format!("read {}", dir.display()))? {
        let entry = entry?;
        let path = entry.path();
        let file_type = entry.file_type()?;
        if file_type.is_symlink() {
            continue;
        }
        if file_type.is_dir() {
            walk(&path, out)?;
            continue;
        }
        if let Some(candidate) = classify_file(&path) {
            out.push(candidate);
        }
    }
    Ok(())
}

fn classify_file(path: &Path) -> Option<LegacyHistorianCandidate> {
    let format = format_from_path(path)?;
    let (building_id, equipment_id, identity_reason) = legacy_identity(path);
    let parquet_name_ok = format != LegacyHistorianFormat::Parquet
        || path.file_name().and_then(|v| v.to_str()) == Some("history.parquet");

    let reason = if let Some(reason) = identity_reason {
        Some(reason)
    } else if !parquet_name_ok {
        Some("legacy Parquet candidate must be named history.parquet".to_string())
    } else {
        None
    };

    Some(LegacyHistorianCandidate {
        path: path.display().to_string(),
        format,
        building_id,
        equipment_id,
        eligible: reason.is_none(),
        reason,
    })
}

fn format_from_path(path: &Path) -> Option<LegacyHistorianFormat> {
    let extension = path.extension()?.to_str()?.to_ascii_lowercase();
    match extension.as_str() {
        "parquet" => Some(LegacyHistorianFormat::Parquet),
        "jsonl" | "ndjson" => Some(LegacyHistorianFormat::Jsonl),
        "feather" | "arrow" | "ipc" => Some(LegacyHistorianFormat::Feather),
        _ => None,
    }
}

fn legacy_identity(path: &Path) -> (Option<String>, Option<String>, Option<String>) {
    let mut building: Option<String> = None;
    let mut equipment: Option<String> = None;
    for component in path.ancestors().flat_map(Path::file_name) {
        let Some(segment) = component.to_str() else {
            continue;
        };
        if let Some(value) = segment.strip_prefix("building=") {
            match safe_partition_value(value, "building_id") {
                Ok(value) => {
                    if building
                        .as_deref()
                        .is_some_and(|existing| existing != value)
                    {
                        return (
                            None,
                            None,
                            Some("conflicting legacy building path identity".to_string()),
                        );
                    }
                    building = Some(value);
                }
                Err(_) => {
                    return (
                        None,
                        None,
                        Some("unsafe legacy building path identity".to_string()),
                    )
                }
            }
        }
        if let Some(value) = segment.strip_prefix("equipment=") {
            match safe_partition_value(value, "equipment_id") {
                Ok(value) => {
                    if equipment
                        .as_deref()
                        .is_some_and(|existing| existing != value)
                    {
                        return (
                            None,
                            None,
                            Some("conflicting legacy equipment path identity".to_string()),
                        );
                    }
                    equipment = Some(value);
                }
                Err(_) => {
                    return (
                        None,
                        None,
                        Some("unsafe legacy equipment path identity".to_string()),
                    )
                }
            }
        }
    }

    if building.is_none() || equipment.is_none() {
        return (
            building,
            equipment,
            Some("missing trusted building/equipment legacy path identity".to_string()),
        );
    }
    (building, equipment, None)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn touch(path: &Path) {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, b"").unwrap();
    }

    #[test]
    fn discovers_trusted_legacy_parquet_identity() {
        let tmp = TempDir::new().unwrap();
        let history = tmp
            .path()
            .join("building=BLDG_1/equipment=AHU_1/history.parquet");
        touch(&history);

        let inventory = discover_legacy_historian(tmp.path()).unwrap();
        assert_eq!(inventory.candidates.len(), 1);
        let candidate = &inventory.candidates[0];
        assert_eq!(candidate.format, LegacyHistorianFormat::Parquet);
        assert_eq!(candidate.building_id.as_deref(), Some("BLDG_1"));
        assert_eq!(candidate.equipment_id.as_deref(), Some("AHU_1"));
        assert!(candidate.eligible);
    }

    #[test]
    fn jsonl_and_feather_are_classified_only_with_path_identity() {
        let tmp = TempDir::new().unwrap();
        touch(
            &tmp.path()
                .join("building=BLDG_1/equipment=AHU_1/history.jsonl"),
        );
        touch(&tmp.path().join("orphan/history.feather"));

        let report = discover_legacy_historian(tmp.path())
            .unwrap()
            .dry_run_report();
        assert_eq!(report.recognized_files, 2);
        assert_eq!(report.jsonl_files, 1);
        assert_eq!(report.feather_files, 1);
        assert_eq!(report.eligible_files, 1);
        assert!(report
            .candidates
            .iter()
            .any(|candidate| !candidate.eligible && candidate.equipment_id.is_none()));
    }

    #[test]
    fn unsafe_or_conflicting_identity_never_becomes_eligible() {
        let tmp = TempDir::new().unwrap();
        touch(
            &tmp.path()
                .join("building=BLDG_1/building=BLDG_2/equipment=AHU_1/history.parquet"),
        );
        touch(
            &tmp.path()
                .join("building=BLDG=BAD/equipment=AHU_2/history.parquet"),
        );

        let inventory = discover_legacy_historian(tmp.path()).unwrap();
        assert_eq!(inventory.candidates.len(), 2);
        assert!(inventory
            .candidates
            .iter()
            .all(|candidate| !candidate.eligible));
    }

    #[test]
    fn non_history_parquet_is_not_eligible_for_legacy_migration() {
        let tmp = TempDir::new().unwrap();
        touch(
            &tmp.path()
                .join("building=BLDG_1/equipment=AHU_1/other.parquet"),
        );
        let inventory = discover_legacy_historian(tmp.path()).unwrap();
        assert_eq!(inventory.candidates.len(), 1);
        assert!(!inventory.candidates[0].eligible);
        assert!(inventory.candidates[0]
            .reason
            .as_deref()
            .unwrap()
            .contains("history.parquet"));
    }
}
