//! Job-native WattLab dump generation (deprecated alias for [`engineering_bundle`] export).

use serde::{Deserialize, Serialize};

use crate::engineering_bundle;
use crate::jobs::JobError;

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
