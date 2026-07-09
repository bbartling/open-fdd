use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SidecarMeta {
    pub building_id: String,
    pub equipment_id: String,
    pub source_csv: String,
    pub source_size_bytes: u64,
    pub source_modified_unix: u64,
    pub source_sha256: String,
    pub parquet_path: String,
    pub row_count: u64,
    pub generated_at: String,
}

pub fn meta_path_for(parquet_path: &Path) -> PathBuf {
    parquet_path.with_extension("meta.json")
}

pub fn write_meta(path: &Path, meta: &SidecarMeta) -> anyhow::Result<()> {
    let text = serde_json::to_string_pretty(meta)?;
    std::fs::write(path, text)?;
    Ok(())
}

pub fn read_meta(path: &Path) -> anyhow::Result<SidecarMeta> {
    let text = std::fs::read_to_string(path)?;
    Ok(serde_json::from_str(&text)?)
}

pub fn source_fingerprint(path: &Path) -> anyhow::Result<(u64, u64, String)> {
    use sha2::{Digest, Sha256};
    let meta = std::fs::metadata(path)?;
    let bytes = std::fs::read(path)?;
    let hash = format!("{:x}", Sha256::digest(&bytes));
    Ok((
        meta.len(),
        meta.modified()?
            .duration_since(std::time::UNIX_EPOCH)?
            .as_secs(),
        hash,
    ))
}
