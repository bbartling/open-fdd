//! Job-native WattLab dump generation via the vendored agent_afdd / cookbook exporter.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Stdio;

use chrono::Utc;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::engineering_bundle;
use crate::jobs::{self, JobError};

const PROFILES: &[&str] = &["summary", "diagnostic", "forensic"];

#[derive(Debug, Deserialize)]
pub struct CreateDumpRequest {
    pub building_id: String,
    #[serde(default = "default_profile")]
    pub profile: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DumpArtifact {
    pub dump_id: String,
    pub job_id: String,
    pub building_id: String,
    pub profile: String,
    pub filename: String,
    pub download_url: String,
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
    let root = root
        .canonicalize()
        .map_err(|e| JobError::Io(e.to_string()))?;
    let package = package
        .canonicalize()
        .map_err(|e| JobError::Io(e.to_string()))?;
    if !package.starts_with(&root) {
        return Err(JobError::Invalid("package path traversal rejected".into()));
    }
    Ok(package)
}

fn agent_script() -> Result<PathBuf, JobError> {
    if let Ok(path) = std::env::var("OPENFDD_AGENT_AFDD_SCRIPT") {
        let path = PathBuf::from(path);
        if path.is_file() {
            return Ok(path);
        }
        return Err(JobError::Io(format!(
            "OPENFDD_AGENT_AFDD_SCRIPT not found: {}",
            path.display()
        )));
    }

    let mut candidates = Vec::new();
    if let Ok(root) = std::env::var("OPENFDD_REPO_ROOT") {
        candidates.push(PathBuf::from(root).join("tools/wattlab_export/agent_afdd.py"));
    }
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.join("tools/wattlab_export/agent_afdd.py"));
        candidates.push(cwd.join("../tools/wattlab_export/agent_afdd.py"));
    }
    candidates.push(
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tools/wattlab_export/agent_afdd.py"),
    );

    candidates.into_iter().find(|p| p.is_file()).ok_or_else(|| {
        JobError::Io(
            "agent_afdd.py not found; set OPENFDD_AGENT_AFDD_SCRIPT or OPENFDD_REPO_ROOT".into(),
        )
    })
}

fn collect_files(root: &Path, dir: &Path, out: &mut Vec<PathBuf>) -> Result<(), JobError> {
    let entries = fs::read_dir(dir).map_err(|e| JobError::Io(e.to_string()))?;
    for entry in entries {
        let path = entry.map_err(|e| JobError::Io(e.to_string()))?.path();
        if path.is_dir() {
            collect_files(root, &path, out)?;
        } else if path.is_file() {
            let rel = path
                .strip_prefix(root)
                .map_err(|e| JobError::Io(e.to_string()))?;
            if rel.components().count() > 0 {
                out.push(path);
            }
        }
    }
    Ok(())
}

fn zip_directory(source: &Path, destination: &Path) -> Result<u64, JobError> {
    let file = fs::File::create(destination).map_err(|e| JobError::Io(e.to_string()))?;
    let mut writer = zip::ZipWriter::new(file);
    let options = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated);
    let mut files = Vec::new();
    collect_files(source, source, &mut files)?;
    files.sort();
    if files.is_empty() {
        return Err(JobError::Io("cookbook exporter wrote no artifacts".into()));
    }
    for path in files {
        let rel = path
            .strip_prefix(source)
            .map_err(|e| JobError::Io(e.to_string()))?
            .to_string_lossy()
            .replace('\\', "/");
        writer
            .start_file(rel, options)
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

fn dump_dir(job_id: &str, dump_id: &str) -> Result<PathBuf, JobError> {
    jobs::validate_job_id(job_id)?;
    let dump_id = validate_segment(dump_id, "dump_id")?;
    if !dump_id.starts_with("dump-") {
        return Err(JobError::Invalid(format!("invalid dump_id: {dump_id}")));
    }
    Ok(jobs::job_dir(job_id)?
        .join("wattlab")
        .join("dumps")
        .join(dump_id))
}

pub async fn create_dump(
    job_id: &str,
    request: CreateDumpRequest,
) -> Result<DumpArtifact, JobError> {
    let export = engineering_bundle::create_export(
        job_id,
        engineering_bundle::CreateExportRequest {
            building_id: request.building_id,
            profile: request.profile,
        },
    )
    .await?;
    Ok(DumpArtifact {
        dump_id: export.export_id,
        job_id: export.job_id,
        building_id: export.building_id,
        profile: export.profile,
        filename: export.filename,
        download_url: export.download_url,
        created_at: export.created_at,
        size_bytes: export.size_bytes,
    })
}

pub fn load_dump(job_id: &str, dump_id: &str) -> Result<(DumpArtifact, Vec<u8>), JobError> {
    let export_id = if dump_id.starts_with("dump-") {
        dump_id.replacen("dump-", "export-", 1)
    } else {
        dump_id.to_string()
    };
    let (export, bytes) = engineering_bundle::load_export(job_id, &export_id)?;
    Ok((
        DumpArtifact {
            dump_id: export.export_id.clone(),
            job_id: export.job_id,
            building_id: export.building_id,
            profile: export.profile,
            filename: export.filename,
            download_url: export.download_url,
            created_at: export.created_at,
            size_bytes: export.size_bytes,
        },
        bytes,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn validates_building_and_profile_segments() {
        assert_eq!(
            validate_segment("BUILDING_100", "building_id").unwrap(),
            "BUILDING_100"
        );
        assert!(validate_segment("../etc", "building_id").is_err());
        assert_eq!(validate_profile("Diagnostic").unwrap(), "diagnostic");
        assert!(validate_profile("everything").is_err());
    }

    #[test]
    fn zips_exported_files_with_forward_slash_names() {
        let temp = tempfile::tempdir().unwrap();
        let source = temp.path().join("contents");
        fs::create_dir_all(source.join("nested")).unwrap();
        fs::write(source.join("MANIFEST.json"), "{}").unwrap();
        fs::write(source.join("nested/data.csv"), "a,b\n1,2\n").unwrap();
        let destination = temp.path().join("dump.zip");

        assert!(zip_directory(&source, &destination).unwrap() > 0);
        let file = fs::File::open(destination).unwrap();
        let mut archive = zip::ZipArchive::new(file).unwrap();
        assert!(archive.by_name("MANIFEST.json").is_ok());
        assert!(archive.by_name("nested/data.csv").is_ok());
    }
}
