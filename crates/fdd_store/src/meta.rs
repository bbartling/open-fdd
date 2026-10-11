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

/// Stream-hash the source CSV (Soft-OPEN 371 T1d): do not load the whole file.
pub fn source_fingerprint(path: &Path) -> anyhow::Result<(u64, u64, String)> {
    use sha2::{Digest, Sha256};
    use std::io::Read;

    let meta = std::fs::metadata(path)?;
    let mut file = std::fs::File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buf = [0u8; 64 * 1024];
    loop {
        let n = file.read(&mut buf)?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    let hash = format!("{:x}", hasher.finalize());
    Ok((
        meta.len(),
        meta.modified()?
            .duration_since(std::time::UNIX_EPOCH)?
            .as_secs(),
        hash,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use sha2::{Digest, Sha256};
    use std::io::Write;

    #[test]
    fn source_fingerprint_matches_full_file_digest_without_loading_via_fs_read_api() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("history_wide.csv");
        let mut f = std::fs::File::create(&path).unwrap();
        // Larger than the 64 KiB stream buffer to exercise the loop.
        let payload = "timestamp_utc,sat\n".to_string() + &"2026-01-01T00:00:00Z,70\n".repeat(5000);
        f.write_all(payload.as_bytes()).unwrap();
        drop(f);
        let (_size, _mtime, streamed) = source_fingerprint(&path).unwrap();
        let expected = format!("{:x}", Sha256::digest(payload.as_bytes()));
        assert_eq!(streamed, expected);
    }
}
