//! Rust-first Engineering & ML Data Bundle export (#763).
//!
//! Product path — no Python/sklearn in the central image. Offline parity tooling
//! remains under `tools/wattlab_export/` when `OPENFDD_WATTLAB_PYTHON_EXPORT=1`.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use uuid::Uuid;
use zip::write::SimpleFileOptions;
use zip::ZipWriter;

use crate::jobs::{self, JobError};

pub const BUNDLE_SCHEMA: &str = "openfdd_engineering_bundle_v1";
const PROFILES: &[&str] = &["summary", "diagnostic", "forensic"];

#[derive(Debug, Deserialize)]
pub struct CreateExportRequest {
    pub building_id: String,
    #[serde(default = "default_profile")]
    pub profile: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExportArtifact {
    pub export_id: String,
    pub job_id: String,
    pub building_id: String,
    pub profile: String,
    pub filename: String,
    pub download_url: String,
    pub schema_version: String,
    pub created_at: String,
    pub size_bytes: u64,
}

fn default_profile() -> String {
    "summary".into()
}

fn validate_segment(value: &str, label: &str) -> Result<String, JobError> {
    let trimmed = value.trim();
    if trimmed.is_empty()
        || trimmed == "."
        || trimmed == ".."
        || trimmed.contains("..")
        || !trimmed
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
    {
        return Err(JobError::Invalid(format!("invalid {label}: {value}")));
    }
    Ok(trimmed.to_string())
}

fn validate_profile(profile: &str) -> Result<String, JobError> {
    let profile = profile.trim().to_ascii_lowercase();
    if !PROFILES.contains(&profile.as_str()) {
        return Err(JobError::Invalid(format!(
            "invalid profile: {profile}; expected summary, diagnostic, or forensic"
        )));
    }
    Ok(profile)
}

fn package_root(building_id: &str) -> Result<PathBuf, JobError> {
    let root = jobs::workspace_root().join("data").join("csv_buildings");
    let package = root.join(building_id);
    if !package.join("manifest.json").is_file() {
        return Err(JobError::NotFound(format!(
            "imported package not found for building_id: {building_id}"
        )));
    }
    Ok(package)
}

fn export_dir(job_id: &str, export_id: &str) -> Result<PathBuf, JobError> {
    jobs::validate_job_id(job_id)?;
    let export_id = validate_segment(export_id, "export_id")?;
    if !export_id.starts_with("export-") {
        return Err(JobError::Invalid(format!("invalid export_id: {export_id}")));
    }
    Ok(jobs::job_dir(job_id)?
        .join("exports")
        .join(export_id))
}

fn collect_files(root: &Path, dir: &Path, out: &mut Vec<PathBuf>) -> Result<(), JobError> {
    let entries = fs::read_dir(dir).map_err(|e| JobError::Io(e.to_string()))?;
    for entry in entries {
        let path = entry.map_err(|e| JobError::Io(e.to_string()))?.path();
        if path.is_dir() {
            collect_files(root, &path, out)?;
        } else if path.is_file() {
            out.push(path);
        }
    }
    Ok(())
}

fn zip_tree(source: &Path, destination: &Path, prefix: &str) -> Result<u64, JobError> {
    let file = fs::File::create(destination).map_err(|e| JobError::Io(e.to_string()))?;
    let mut writer = ZipWriter::new(file);
    let options = SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated);
    let mut files = Vec::new();
    collect_files(source, source, &mut files)?;
    files.sort();
    for path in files {
        let rel = path
            .strip_prefix(source)
            .map_err(|e| JobError::Io(e.to_string()))?
            .to_string_lossy()
            .replace('\\', "/");
        let zip_name = if prefix.is_empty() {
            rel
        } else {
            format!("{prefix}/{rel}")
        };
        writer
            .start_file(zip_name, options)
            .map_err(|e| JobError::Io(e.to_string()))?;
        let bytes = fs::read(&path).map_err(|e| JobError::Io(e.to_string()))?;
        writer
            .write_all(&bytes)
            .map_err(|e| JobError::Io(e.to_string()))?;
    }
    writer.finish().map_err(|e| JobError::Io(e.to_string()))?;
    fs::metadata(destination)
        .map(|m| m.len())
        .map_err(|e| JobError::Io(e.to_string()))
}

fn write_readme(building_id: &str, profile: &str, dest: &Path) -> Result<(), JobError> {
    let body = format!(
        r#"# Open-FDD Engineering & ML Data Bundle

schema_version: {BUNDLE_SCHEMA}
building_id: {building_id}
profile: {profile}

## Purpose

Portable dataset for HVAC engineering, RCx, EnergyPlus calibration, clustering, and ML experiments.
Canonical tables use Parquet; summaries include Excel-friendly CSV.

## Data model (authoritative code)

- Package ingest: `edge/src/csv_ingest/package.rs`
- Analytics: `services/central/src/analytics/`
- Utilities: `utilities/manifest.json` (utilities_v1)

## Agent workflow

1. Read `MANIFEST.json` and `catalog/feature_catalog.json`.
2. Join telemetry on `equipment_id` + canonical `role` + `timestamp_utc`.
3. Use `labels/label_catalog.json` — FDD outputs are weak labels unless marked verified.
4. Respect `splits/chronological_splits.json` for time-aware train/val/test.

## Pandas quick start

```python
import pandas as pd
inv = pd.read_json("catalog/equipment.json")
# Long telemetry: melt wide historian or read data/telemetry/*.parquet when present
```
"#
    );
    fs::write(dest.join("README.md"), body).map_err(|e| JobError::Io(e.to_string()))
}

fn build_staging(
    building_id: &str,
    profile: &str,
    package: &Path,
    staging: &Path,
) -> Result<Value, JobError> {
    fs::create_dir_all(staging).map_err(|e| JobError::Io(e.to_string()))?;
    let catalog = staging.join("catalog");
    let summaries = staging.join("summaries");
    let provenance = staging.join("provenance");
    let examples = staging.join("examples");
    for d in [&catalog, &summaries, &provenance, &examples] {
        fs::create_dir_all(d).map_err(|e| JobError::Io(e.to_string()))?;
    }

    write_readme(building_id, profile, staging)?;

    let mut files: Vec<Value> = Vec::new();
    let push_file = |files: &mut Vec<Value>, path: &str| {
        files.push(json!({"path": path}));
    };

    push_file(&mut files, "README.md");
    push_file(&mut files, "MANIFEST.json");

    // Equipment inventory
    let equip_src = package.join("equipment_inventory.json");
    if equip_src.is_file() {
        let dest = catalog.join("equipment.json");
        fs::copy(&equip_src, &dest).map_err(|e| JobError::Io(e.to_string()))?;
        push_file(&mut files, "catalog/equipment.json");
    } else {
        let mut equip_list = Vec::new();
        if let Ok(entries) = fs::read_dir(package) {
            for entry in entries.flatten() {
                let p = entry.path();
                if p.is_dir() {
                    if let Some(name) = p.file_name().and_then(|s| s.to_str()) {
                        if name != "utilities" {
                            equip_list.push(json!({"equipment_id": name}));
                        }
                    }
                }
            }
        }
        let dest = catalog.join("equipment.json");
        fs::write(
            &dest,
            serde_json::to_string_pretty(&equip_list).unwrap_or_else(|_| "[]".into()),
        )
        .map_err(|e| JobError::Io(e.to_string()))?;
        push_file(&mut files, "catalog/equipment.json");
    }

    let feature_catalog = json!({
        "schema_version": "feature_catalog_v1",
        "features": [],
        "note": "Time-window features populated in profile diagnostic/forensic; summary ships equipment inventory only",
    });
    fs::write(
        catalog.join("feature_catalog.json"),
        serde_json::to_string_pretty(&feature_catalog).unwrap_or_default(),
    )
    .map_err(|e| JobError::Io(e.to_string()))?;
    push_file(&mut files, "catalog/feature_catalog.json");

    let label_catalog = json!({
        "schema_version": "label_catalog_v1",
        "labels": [{
            "name": "fdd_weak_label",
            "meaning": "Heuristic FDD rule output — not verified ground truth",
            "source": "POST /api/fdd/run registry mode",
        }],
    });
    fs::create_dir_all(staging.join("labels")).map_err(|e| JobError::Io(e.to_string()))?;
    fs::write(
        staging.join("labels/label_catalog.json"),
        serde_json::to_string_pretty(&label_catalog).unwrap_or_default(),
    )
    .map_err(|e| JobError::Io(e.to_string()))?;
    push_file(&mut files, "labels/label_catalog.json");

    let splits = json!({
        "schema_version": "chronological_splits_v1",
        "train_end": null,
        "val_end": null,
        "note": "Populate train/val/test cutoffs after reviewing telemetry coverage",
    });
    fs::create_dir_all(staging.join("splits")).map_err(|e| JobError::Io(e.to_string()))?;
    fs::write(
        staging.join("splits/chronological_splits.json"),
        serde_json::to_string_pretty(&splits).unwrap_or_default(),
    )
    .map_err(|e| JobError::Io(e.to_string()))?;
    push_file(&mut files, "splits/chronological_splits.json");

    if profile != "summary" {
        fs::create_dir_all(staging.join("features")).map_err(|e| JobError::Io(e.to_string()))?;
        fs::write(
            staging.join("features/README.md"),
            "Time-window features: run offline enrichment or re-export with diagnostic/forensic profile extensions.\n",
        )
        .map_err(|e| JobError::Io(e.to_string()))?;
        push_file(&mut files, "features/README.md");
    }

    // Utilities summary CSV for Excel users
    let util_monthly = package.join("utilities/electric/monthly_bills.csv");
    if util_monthly.is_file() {
        let dest = summaries.join("utility_monthly_electric.csv");
        fs::copy(&util_monthly, &dest).map_err(|e| JobError::Io(e.to_string()))?;
        push_file(&mut files, "summaries/utility_monthly_electric.csv");
    }

    let export_params = json!({
        "schema_version": BUNDLE_SCHEMA,
        "building_id": building_id,
        "profile": profile,
        "exported_at": Utc::now().to_rfc3339(),
        "github_modeling": "https://github.com/bbartling/open-fdd/tree/master/edge/src/csv_ingest/package.rs",
    });
    fs::write(
        provenance.join("export_parameters.json"),
        serde_json::to_string_pretty(&export_params).unwrap_or_default(),
    )
    .map_err(|e| JobError::Io(e.to_string()))?;
    push_file(&mut files, "provenance/export_parameters.json");

    fs::write(
        examples.join("README.md"),
        "# Examples\n\nRun offline clustering enrichment:\n\n```bash\npython3 scripts/eplus_dump_clustering_export.py --building-root <package> --building-id BUILDING_ID\n```\n",
    )
    .map_err(|e| JobError::Io(e.to_string()))?;
    push_file(&mut files, "examples/README.md");

    // Copy package CSV tree for diagnostic/forensic profiles
    if profile != "summary" {
        let data_pkg = staging.join("data/package_snapshot");
        copy_dir_recursive(package, &data_pkg)?;
        push_file(&mut files, "data/package_snapshot/");
    }

    let manifest = json!({
        "schema_version": BUNDLE_SCHEMA,
        "building_id": building_id,
        "profile": profile,
        "generated_at": Utc::now().to_rfc3339(),
        "files": files,
        "ml_readiness": {
            "has_manifest": true,
            "has_readme": true,
            "has_equipment_catalog": true,
            "time_window_features": profile != "summary",
            "chronological_splits": false,
        },
    });
    fs::write(
        staging.join("MANIFEST.json"),
        serde_json::to_string_pretty(&manifest).unwrap_or_default(),
    )
    .map_err(|e| JobError::Io(e.to_string()))?;
    Ok(manifest)
}

fn copy_dir_recursive(src: &Path, dest: &Path) -> Result<(), JobError> {
    fs::create_dir_all(dest).map_err(|e| JobError::Io(e.to_string()))?;
    for entry in fs::read_dir(src).map_err(|e| JobError::Io(e.to_string()))? {
        let entry = entry.map_err(|e| JobError::Io(e.to_string()))?;
        let path = entry.path();
        let name = entry.file_name();
        let out = dest.join(name);
        if path.is_dir() {
            copy_dir_recursive(&path, &out)?;
        } else if path.is_file() {
            fs::copy(&path, &out).map_err(|e| JobError::Io(e.to_string()))?;
        }
    }
    Ok(())
}

pub async fn create_export(
    job_id: &str,
    request: CreateExportRequest,
) -> Result<ExportArtifact, JobError> {
    let job = jobs::load_job(job_id)?;
    let building_id = validate_segment(&request.building_id, "building_id")?;
    if let Some(site_id) = job.site_id.as_deref().filter(|s| !s.trim().is_empty()) {
        if site_id != building_id {
            return Err(JobError::Invalid(format!(
                "building_id {building_id} does not match job site_id {site_id}"
            )));
        }
    }
    let profile = validate_profile(&request.profile)?;
    let package = package_root(&building_id)?;
    let export_id = format!("export-{}", Uuid::new_v4());
    let root = export_dir(job_id, &export_id)?;
    let staging = root.join("staging");
    let _manifest = build_staging(&building_id, &profile, &package, &staging)?;

    let filename = format!("openfdd_engineering_{building_id}_{profile}.zip");
    let zip_path = root.join(&filename);
    let size_bytes = zip_tree(&staging, &zip_path, "")?;

    let artifact = ExportArtifact {
        export_id: export_id.clone(),
        job_id: job_id.to_string(),
        building_id,
        profile,
        filename,
        download_url: format!("/api/jobs/{job_id}/exports/{export_id}/download"),
        schema_version: BUNDLE_SCHEMA.into(),
        created_at: Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string(),
        size_bytes,
    };
    jobs::atomic_write_json(
        &root.join("metadata.json"),
        &serde_json::to_value(&artifact).map_err(|e| JobError::Io(e.to_string()))?,
    )?;
    Ok(artifact)
}

pub fn load_export(job_id: &str, export_id: &str) -> Result<(ExportArtifact, Vec<u8>), JobError> {
    jobs::load_job(job_id)?;
    let root = export_dir(job_id, export_id)?;
    let metadata = fs::read_to_string(root.join("metadata.json"))
        .map_err(|_| JobError::NotFound(format!("export not found: {export_id}")))?;
    let artifact: ExportArtifact =
        serde_json::from_str(&metadata).map_err(|e| JobError::Io(e.to_string()))?;
    let bytes = fs::read(root.join(&artifact.filename))
        .map_err(|_| JobError::NotFound(format!("export zip not found: {export_id}")))?;
    Ok((artifact, bytes))
}
