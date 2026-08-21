//! Restart-safe execution for H6 legacy historian migration.
//!
//! Eligible legacy Parquet sources are read in bounded Arrow batches and written
//! into a staging tree that is not query-visible. An atomic receipt records the
//! exact canonical publish plan before any staged part is renamed into `history/`.
//! If migration stops mid-publish, rerunning resumes that exact plan instead of
//! producing duplicate canonical parts.

use std::fs;
use std::io::{BufReader, Read};
use std::path::{Component, Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{anyhow, bail, Context, Result};
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::historian::LocalStorage;
use crate::migration::{discover_legacy_historian, LegacyHistorianCandidate, LegacyHistorianFormat};
use crate::parquet_parts::{ParquetPart, ParquetPartWriter, DEFAULT_ROW_GROUP_ROWS};

const RECEIPT_VERSION: u32 = 1;
const METADATA_DIR: &str = ".openfdd-migration";
const HASH_BUFFER_BYTES: usize = 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MigrationSourceStatus {
    Migrated,
    Resumed,
    AlreadyMigrated,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MigrationPart {
    pub relative_path: String,
    pub rows: usize,
    pub bytes: usize,
    pub year: i32,
    pub month: u32,
    pub first_timestamp_utc: String,
    pub last_timestamp_utc: String,
    pub sha256: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct MigrationSourceReport {
    pub source_path: String,
    pub source_relative_path: String,
    pub building_id: String,
    pub equipment_id: String,
    pub source_sha256: String,
    pub source_size_bytes: u64,
    pub source_rows: u64,
    pub canonical_rows: u64,
    pub status: MigrationSourceStatus,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub first_timestamp_utc: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub last_timestamp_utc: Option<String>,
    pub parts: Vec<MigrationPart>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct MigrationRunReport {
    pub source_root: String,
    pub destination_root: String,
    pub eligible_parquet_sources: usize,
    pub migrated_sources: usize,
    pub resumed_sources: usize,
    pub already_migrated_sources: usize,
    pub source_rows_verified: u64,
    pub canonical_rows_verified: u64,
    pub parts_verified: usize,
    pub sources: Vec<MigrationSourceReport>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum ReceiptState {
    Staged,
    Complete,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct Receipt {
    version: u32,
    state: ReceiptState,
    source_relative_path: String,
    source_sha256: String,
    source_size_bytes: u64,
    source_modified_unix_seconds: u64,
    building_id: String,
    equipment_id: String,
    source_rows: u64,
    canonical_rows: u64,
    parts: Vec<MigrationPart>,
}

#[derive(Debug, Clone)]
struct SourceFingerprint {
    size_bytes: u64,
    modified: SystemTime,
    modified_unix_seconds: u64,
    sha256: String,
}

/// Migrate every eligible legacy `building=<id>/equipment=<id>/history.parquet`
/// source under `source_root` into canonical monthly Parquet parts.
///
/// The destination must be local canonical storage. This command is intended for
/// explicit operator/offline migration, not concurrent live ingest.
pub fn migrate_legacy_parquet(
    source_root: &Path,
    destination: &LocalStorage,
) -> Result<MigrationRunReport> {
    let inventory = discover_legacy_historian(source_root)?;
    let candidates: Vec<_> = inventory
        .candidates
        .into_iter()
        .filter(|candidate| {
            candidate.eligible && candidate.format == LegacyHistorianFormat::Parquet
        })
        .collect();

    let mut sources = Vec::with_capacity(candidates.len());
    for candidate in &candidates {
        sources.push(migrate_candidate(source_root, destination, candidate)?);
    }

    Ok(MigrationRunReport {
        source_root: source_root.display().to_string(),
        destination_root: destination.root().display().to_string(),
        eligible_parquet_sources: candidates.len(),
        migrated_sources: count_status(&sources, MigrationSourceStatus::Migrated),
        resumed_sources: count_status(&sources, MigrationSourceStatus::Resumed),
        already_migrated_sources: count_status(
            &sources,
            MigrationSourceStatus::AlreadyMigrated,
        ),
        source_rows_verified: sources.iter().map(|source| source.source_rows).sum(),
        canonical_rows_verified: sources.iter().map(|source| source.canonical_rows).sum(),
        parts_verified: sources.iter().map(|source| source.parts.len()).sum(),
        sources,
    })
}

fn count_status(sources: &[MigrationSourceReport], status: MigrationSourceStatus) -> usize {
    sources.iter().filter(|source| source.status == status).count()
}

fn migrate_candidate(
    source_root: &Path,
    destination: &LocalStorage,
    candidate: &LegacyHistorianCandidate,
) -> Result<MigrationSourceReport> {
    let building_id = candidate
        .building_id
        .as_deref()
        .ok_or_else(|| anyhow!("eligible migration candidate is missing building identity"))?;
    let equipment_id = candidate
        .equipment_id
        .as_deref()
        .ok_or_else(|| anyhow!("eligible migration candidate is missing equipment identity"))?;
    let source_path = PathBuf::from(&candidate.path);
    let source_relative_path = slash_path(
        source_path
            .strip_prefix(source_root)
            .context("legacy migration candidate escaped discovery root")?,
    );
    let migration_id = migration_id(&source_relative_path, building_id, equipment_id);
    let receipt_path = receipt_path(&migration_id);
    let fingerprint = fingerprint_source(&source_path)?;

    if destination.exists(&receipt_path)? {
        let mut receipt: Receipt = serde_json::from_slice(&destination.read(&receipt_path)?)
            .context("parse historian migration receipt")?;
        validate_receipt(
            &receipt,
            &source_relative_path,
            building_id,
            equipment_id,
            &fingerprint,
        )?;
        return match receipt.state {
            ReceiptState::Complete => {
                verify_published_parts(destination, &receipt.parts)?;
                Ok(report_from_receipt(
                    &source_path,
                    receipt,
                    MigrationSourceStatus::AlreadyMigrated,
                ))
            }
            ReceiptState::Staged => {
                let staging_root = staging_root(destination, &migration_id);
                publish_staged_parts(destination, &staging_root, &receipt.parts)?;
                receipt.state = ReceiptState::Complete;
                write_receipt(destination, &receipt_path, &receipt)?;
                verify_published_parts(destination, &receipt.parts)?;
                Ok(report_from_receipt(
                    &source_path,
                    receipt,
                    MigrationSourceStatus::Resumed,
                ))
            }
        };
    }

    let staging_root = staging_root(destination, &migration_id);
    if staging_root.exists() {
        fs::remove_dir_all(&staging_root)
            .with_context(|| format!("clear stale migration staging {}", staging_root.display()))?;
    }
    fs::create_dir_all(&staging_root)?;

    let writer = ParquetPartWriter::new(LocalStorage::new(&staging_root));
    let source_file = fs::File::open(&source_path)
        .with_context(|| format!("open legacy Parquet {}", source_path.display()))?;
    let reader = ParquetRecordBatchReaderBuilder::try_new(source_file)
        .context("read legacy Parquet metadata")?
        .with_batch_size(DEFAULT_ROW_GROUP_ROWS)
        .build()
        .context("build legacy Parquet batch reader")?;

    let mut source_rows = 0u64;
    let mut canonical_rows = 0u64;
    let mut parts = Vec::new();
    for batch in reader {
        let batch = batch.context("read legacy Parquet batch")?;
        source_rows += batch.num_rows() as u64;
        let written = writer
            .write_history_batch(building_id, equipment_id, &batch)
            .with_context(|| format!("migrate legacy batch from {}", source_path.display()))?;
        let batch_rows = written.iter().map(|part| part.rows as u64).sum::<u64>();
        if batch_rows != batch.num_rows() as u64 {
            bail!(
                "legacy migration row mismatch for {}: source batch {} != canonical {}",
                source_relative_path,
                batch.num_rows(),
                batch_rows
            );
        }
        canonical_rows += batch_rows;
        for part in written {
            parts.push(migration_part(&staging_root, part)?);
        }
    }

    if source_rows != canonical_rows {
        bail!(
            "legacy migration row mismatch for {}: source {} != canonical {}",
            source_relative_path,
            source_rows,
            canonical_rows
        );
    }
    ensure_source_unchanged(&source_path, &fingerprint)?;

    let mut receipt = Receipt {
        version: RECEIPT_VERSION,
        state: ReceiptState::Staged,
        source_relative_path,
        source_sha256: fingerprint.sha256.clone(),
        source_size_bytes: fingerprint.size_bytes,
        source_modified_unix_seconds: fingerprint.modified_unix_seconds,
        building_id: building_id.to_string(),
        equipment_id: equipment_id.to_string(),
        source_rows,
        canonical_rows,
        parts,
    };

    write_receipt(destination, &receipt_path, &receipt)?;
    publish_staged_parts(destination, &staging_root, &receipt.parts)?;
    receipt.state = ReceiptState::Complete;
    write_receipt(destination, &receipt_path, &receipt)?;
    verify_published_parts(destination, &receipt.parts)?;

    Ok(report_from_receipt(
        &source_path,
        receipt,
        MigrationSourceStatus::Migrated,
    ))
}

fn fingerprint_source(path: &Path) -> Result<SourceFingerprint> {
    let before = fs::metadata(path).with_context(|| format!("stat {}", path.display()))?;
    let modified = before.modified()?;
    let sha256 = file_sha256(path)?;
    let after = fs::metadata(path).with_context(|| format!("restat {}", path.display()))?;
    if before.len() != after.len() || modified != after.modified()? {
        bail!("legacy source changed while fingerprinting {}", path.display());
    }
    Ok(SourceFingerprint {
        size_bytes: before.len(),
        modified,
        modified_unix_seconds: modified.duration_since(UNIX_EPOCH)?.as_secs(),
        sha256,
    })
}

fn ensure_source_unchanged(path: &Path, fingerprint: &SourceFingerprint) -> Result<()> {
    let metadata = fs::metadata(path).with_context(|| format!("restat {}", path.display()))?;
    if metadata.len() != fingerprint.size_bytes || metadata.modified()? != fingerprint.modified {
        bail!("legacy source changed during migration {}", path.display());
    }
    Ok(())
}

fn migration_id(source_relative_path: &str, building_id: &str, equipment_id: &str) -> String {
    let mut hash = Sha256::new();
    hash.update(b"openfdd-h6-migration\0");
    hash.update(source_relative_path.as_bytes());
    hash.update(b"\0");
    hash.update(building_id.as_bytes());
    hash.update(b"\0");
    hash.update(equipment_id.as_bytes());
    format!("{:x}", hash.finalize())
}

fn receipt_path(migration_id: &str) -> PathBuf {
    PathBuf::from(METADATA_DIR)
        .join("receipts")
        .join(format!("{migration_id}.json"))
}

fn staging_root(destination: &LocalStorage, migration_id: &str) -> PathBuf {
    destination
        .root()
        .join(METADATA_DIR)
        .join("staging")
        .join(migration_id)
}

fn migration_part(staging_root: &Path, part: ParquetPart) -> Result<MigrationPart> {
    let staged_path = validated_part_path(staging_root, &part.relative_path)?;
    Ok(MigrationPart {
        relative_path: part.relative_path,
        rows: part.rows,
        bytes: part.bytes,
        year: part.year,
        month: part.month,
        first_timestamp_utc: part.first_timestamp_utc,
        last_timestamp_utc: part.last_timestamp_utc,
        sha256: file_sha256(&staged_path)?,
    })
}

fn validate_receipt(
    receipt: &Receipt,
    source_relative_path: &str,
    building_id: &str,
    equipment_id: &str,
    fingerprint: &SourceFingerprint,
) -> Result<()> {
    if receipt.version != RECEIPT_VERSION {
        bail!("unsupported historian migration receipt version");
    }
    if receipt.source_relative_path != source_relative_path
        || receipt.building_id != building_id
        || receipt.equipment_id != equipment_id
    {
        bail!("historian migration receipt identity mismatch");
    }
    if receipt.source_size_bytes != fingerprint.size_bytes
        || receipt.source_sha256 != fingerprint.sha256
    {
        bail!(
            "legacy source changed since migration receipt was created: {}",
            source_relative_path
        );
    }
    if receipt.source_rows != receipt.canonical_rows {
        bail!("historian migration receipt contains a row preservation mismatch");
    }
    Ok(())
}

fn write_receipt(destination: &LocalStorage, path: &Path, receipt: &Receipt) -> Result<()> {
    destination.write_atomic(path, &serde_json::to_vec_pretty(receipt)?)
}

fn publish_staged_parts(
    destination: &LocalStorage,
    staging_root: &Path,
    parts: &[MigrationPart],
) -> Result<()> {
    for part in parts {
        let canonical = validated_part_path(destination.root(), &part.relative_path)?;
        let staged = validated_part_path(staging_root, &part.relative_path)?;
        if canonical.exists() {
            verify_file(&canonical, part)?;
            if staged.exists() {
                verify_file(&staged, part)?;
                fs::remove_file(&staged)?;
            }
            continue;
        }
        if !staged.is_file() {
            bail!("migration publish plan lost staged part {}", part.relative_path);
        }
        verify_file(&staged, part)?;
        let parent = canonical
            .parent()
            .ok_or_else(|| anyhow!("canonical migration part has no parent"))?;
        fs::create_dir_all(parent)?;
        fs::rename(&staged, &canonical).with_context(|| {
            format!(
                "publish staged historian part {} -> {}",
                staged.display(),
                canonical.display()
            )
        })?;
    }
    if staging_root.exists() {
        fs::remove_dir_all(staging_root)?;
    }
    Ok(())
}

fn verify_published_parts(destination: &LocalStorage, parts: &[MigrationPart]) -> Result<()> {
    for part in parts {
        let path = validated_part_path(destination.root(), &part.relative_path)?;
        if !path.is_file() {
            bail!("migrated historian part is missing: {}", part.relative_path);
        }
        verify_file(&path, part)?;
    }
    Ok(())
}

fn verify_file(path: &Path, part: &MigrationPart) -> Result<()> {
    if fs::metadata(path)?.len() != part.bytes as u64 {
        bail!("migrated historian part size mismatch: {}", path.display());
    }
    if file_sha256(path)? != part.sha256 {
        bail!("migrated historian part hash mismatch: {}", path.display());
    }
    Ok(())
}

fn validated_part_path(root: &Path, relative_path: &str) -> Result<PathBuf> {
    let relative = Path::new(relative_path);
    if relative.is_absolute() {
        bail!("migration part path must be relative");
    }
    let mut components = relative.components();
    match components.next() {
        Some(Component::Normal(first)) if first.to_str() == Some("history") => {}
        _ => bail!("migration part must remain inside canonical history/"),
    }
    if components.any(|component| !matches!(component, Component::Normal(_))) {
        bail!("migration part contains unsafe path components");
    }
    Ok(root.join(relative))
}

fn file_sha256(path: &Path) -> Result<String> {
    let file = fs::File::open(path).with_context(|| format!("open {} for hashing", path.display()))?;
    let mut reader = BufReader::with_capacity(HASH_BUFFER_BYTES, file);
    let mut buffer = vec![0u8; HASH_BUFFER_BYTES];
    let mut hash = Sha256::new();
    loop {
        let read = reader.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hash.update(&buffer[..read]);
    }
    Ok(format!("{:x}", hash.finalize()))
}

fn report_from_receipt(
    source_path: &Path,
    receipt: Receipt,
    status: MigrationSourceStatus,
) -> MigrationSourceReport {
    let first_timestamp_utc = receipt
        .parts
        .iter()
        .map(|part| part.first_timestamp_utc.as_str())
        .min()
        .map(ToOwned::to_owned);
    let last_timestamp_utc = receipt
        .parts
        .iter()
        .map(|part| part.last_timestamp_utc.as_str())
        .max()
        .map(ToOwned::to_owned);
    MigrationSourceReport {
        source_path: source_path.display().to_string(),
        source_relative_path: receipt.source_relative_path,
        building_id: receipt.building_id,
        equipment_id: receipt.equipment_id,
        source_sha256: receipt.source_sha256,
        source_size_bytes: receipt.source_size_bytes,
        source_rows: receipt.source_rows,
        canonical_rows: receipt.canonical_rows,
        status,
        first_timestamp_utc,
        last_timestamp_utc,
        parts: receipt.parts,
    }
}

fn slash_path(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;
    use arrow::array::{Float64Array, TimestampNanosecondArray};
    use arrow::datatypes::{DataType, Field, Schema, TimeUnit};
    use arrow::record_batch::RecordBatch;
    use chrono::{DateTime, Utc};
    use parquet::arrow::ArrowWriter;
    use tempfile::TempDir;

    fn write_legacy_parquet(path: &Path, times: &[&str]) {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        let timestamps = times
            .iter()
            .map(|raw| {
                DateTime::parse_from_rfc3339(raw)
                    .unwrap()
                    .with_timezone(&Utc)
                    .timestamp_nanos_opt()
                    .unwrap()
            })
            .collect::<Vec<_>>();
        let schema = Arc::new(Schema::new(vec![
            Field::new(
                "timestamp_utc",
                DataType::Timestamp(TimeUnit::Nanosecond, None),
                false,
            ),
            Field::new("sat", DataType::Float64, true),
        ]));
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(TimestampNanosecondArray::from(timestamps)),
                Arc::new(Float64Array::from(
                    (0..times.len())
                        .map(|index| Some(50.0 + index as f64))
                        .collect::<Vec<_>>(),
                )),
            ],
        )
        .unwrap();
        let file = fs::File::create(path).unwrap();
        let mut writer = ArrowWriter::try_new(file, schema, None).unwrap();
        writer.write(&batch).unwrap();
        writer.close().unwrap();
    }

    fn legacy_path(root: &Path) -> PathBuf {
        root.join("building=BLDG_1/equipment=AHU_1/history.parquet")
    }

    #[test]
    fn preserves_rows_and_month_partitions() {
        let source = TempDir::new().unwrap();
        let destination = TempDir::new().unwrap();
        write_legacy_parquet(
            &legacy_path(source.path()),
            &[
                "2026-08-31T23:55:00Z",
                "2026-09-01T00:00:00Z",
                "2026-08-01T00:00:00Z",
            ],
        );
        let storage = LocalStorage::new(destination.path());

        let report = migrate_legacy_parquet(source.path(), &storage).unwrap();
        assert_eq!(report.migrated_sources, 1);
        assert_eq!(report.source_rows_verified, 3);
        assert_eq!(report.canonical_rows_verified, 3);
        assert_eq!(report.parts_verified, 2);
        assert!(report.sources[0]
            .parts
            .iter()
            .any(|part| part.relative_path.contains("year=2026/month=08/")));
        assert!(report.sources[0]
            .parts
            .iter()
            .any(|part| part.relative_path.contains("year=2026/month=09/")));
    }

    #[test]
    fn completed_receipt_makes_rerun_idempotent() {
        let source = TempDir::new().unwrap();
        let destination = TempDir::new().unwrap();
        write_legacy_parquet(
            &legacy_path(source.path()),
            &["2026-08-20T12:00:00Z", "2026-08-20T12:05:00Z"],
        );
        let storage = LocalStorage::new(destination.path());

        let first = migrate_legacy_parquet(source.path(), &storage).unwrap();
        let files_before = storage.list_recursive(Path::new("history")).unwrap();
        let second = migrate_legacy_parquet(source.path(), &storage).unwrap();
        let files_after = storage.list_recursive(Path::new("history")).unwrap();

        assert_eq!(first.migrated_sources, 1);
        assert_eq!(second.already_migrated_sources, 1);
        assert_eq!(files_before.len(), files_after.len());
        assert_eq!(first.sources[0].parts, second.sources[0].parts);
    }

    #[test]
    fn changed_source_after_receipt_fails_closed() {
        let source = TempDir::new().unwrap();
        let destination = TempDir::new().unwrap();
        let history = legacy_path(source.path());
        write_legacy_parquet(&history, &["2026-08-20T12:00:00Z"]);
        let storage = LocalStorage::new(destination.path());
        migrate_legacy_parquet(source.path(), &storage).unwrap();

        write_legacy_parquet(
            &history,
            &["2026-08-20T12:00:00Z", "2026-08-20T12:05:00Z"],
        );
        let error = migrate_legacy_parquet(source.path(), &storage).unwrap_err();
        assert!(error.to_string().contains("changed since migration receipt"));
    }
}
