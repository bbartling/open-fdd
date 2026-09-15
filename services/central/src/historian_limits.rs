//! Wave O6 — hub-admin historian retain window + size cap.
//!
//! Defaults: 365 days OR 5 GiB (whichever binds first). Stored under
//! `workspace/control_plane/historian_limits.json`. Env bootstrap:
//! `OPENFDD_HISTORIAN_RETAIN_DAYS`, `OPENFDD_HISTORIAN_SIZE_GIB`.
//! Import admission: `OPENFDD_IMPORT_MAX_INFLIGHT` (default 2).

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{Arc, OnceLock};

use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};
use tokio::sync::{OwnedSemaphorePermit, Semaphore};
use utoipa::ToSchema;

const DEFAULT_RETAIN_DAYS: u32 = 365;
const DEFAULT_SIZE_GIB: f64 = 5.0;
const DEFAULT_IMPORT_MAX_INFLIGHT: usize = 2;

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema, PartialEq)]
pub struct HistorianLimits {
    /// Keep / accept history no older than this many days.
    pub retain_days: u32,
    /// Soft size cap in GiB (tenant when MT ON, else hub / building).
    pub size_gib: f64,
}

impl Default for HistorianLimits {
    fn default() -> Self {
        Self {
            retain_days: DEFAULT_RETAIN_DAYS,
            size_gib: DEFAULT_SIZE_GIB,
        }
    }
}

impl HistorianLimits {
    pub fn path_under_workspace(workspace: &Path) -> PathBuf {
        workspace
            .join("control_plane")
            .join("historian_limits.json")
    }

    pub fn load(workspace: &Path) -> Self {
        let path = Self::path_under_workspace(workspace);
        let mut lim = if path.is_file() {
            fs::read_to_string(&path)
                .ok()
                .and_then(|s| serde_json::from_str(&s).ok())
                .unwrap_or_default()
        } else {
            Self::default()
        };
        if let Ok(v) = std::env::var("OPENFDD_HISTORIAN_RETAIN_DAYS") {
            if let Ok(d) = v.trim().parse::<u32>() {
                if d > 0 {
                    lim.retain_days = d;
                }
            }
        }
        if let Ok(v) = std::env::var("OPENFDD_HISTORIAN_SIZE_GIB") {
            if let Ok(g) = v.trim().parse::<f64>() {
                if g > 0.0 && g.is_finite() {
                    lim.size_gib = g;
                }
            }
        }
        lim.sanitize();
        lim
    }

    pub fn sanitize(&mut self) {
        if self.retain_days == 0 {
            self.retain_days = DEFAULT_RETAIN_DAYS;
        }
        self.retain_days = self.retain_days.min(3650);
        if !(self.size_gib.is_finite() && self.size_gib > 0.0) {
            self.size_gib = DEFAULT_SIZE_GIB;
        }
        self.size_gib = self.size_gib.clamp(0.1, 500.0);
    }

    pub fn save(&self, workspace: &Path) -> Result<(), String> {
        let mut lim = self.clone();
        lim.sanitize();
        let path = Self::path_under_workspace(workspace);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|e| format!("mkdir control_plane: {e}"))?;
        }
        let body = serde_json::to_string_pretty(&lim).map_err(|e| e.to_string())?;
        let tmp = path.with_extension("json.tmp");
        {
            let mut f = fs::File::create(&tmp).map_err(|e| format!("create tmp: {e}"))?;
            f.write_all(body.as_bytes())
                .map_err(|e| format!("write tmp: {e}"))?;
            f.write_all(b"\n")
                .map_err(|e| format!("write tmp nl: {e}"))?;
            f.sync_all().map_err(|e| format!("sync tmp: {e}"))?;
        }
        fs::rename(&tmp, &path).map_err(|e| format!("rename historian_limits: {e}"))?;
        Ok(())
    }

    pub fn size_cap_bytes(&self) -> u64 {
        (self.size_gib * 1024.0 * 1024.0 * 1024.0).round() as u64
    }

    /// Earliest UTC instant still inside the retain window.
    pub fn retain_floor_utc(&self) -> DateTime<Utc> {
        Utc::now() - Duration::days(i64::from(self.retain_days))
    }

    /// Clamp an optional query/FDD start to the retain floor (no silent mid-query truncate of results).
    pub fn clamp_start(&self, start: Option<DateTime<Utc>>) -> Option<DateTime<Utc>> {
        let Some(s) = start else {
            return None;
        };
        let floor = self.retain_floor_utc();
        Some(if s < floor { floor } else { s })
    }
}

/// Local file historian root (`OPENFDD_STORAGE_URL` / `OPENFDD_PARQUET_ROOT` / workspace fallback).
pub fn storage_root() -> PathBuf {
    if let Some(p) = fdd_store::local_file_root_from_env() {
        return p;
    }
    let workspace = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
    PathBuf::from(workspace).join("data/openfdd")
}

fn import_semaphore() -> &'static Arc<Semaphore> {
    static SEM: OnceLock<Arc<Semaphore>> = OnceLock::new();
    SEM.get_or_init(|| {
        let n = std::env::var("OPENFDD_IMPORT_MAX_INFLIGHT")
            .ok()
            .and_then(|s| s.trim().parse::<usize>().ok())
            .filter(|n| *n > 0)
            .unwrap_or(DEFAULT_IMPORT_MAX_INFLIGHT);
        Arc::new(Semaphore::new(n))
    })
}

/// Fail closed with 429 when too many package imports are in flight.
pub async fn acquire_import_slot() -> Result<OwnedSemaphorePermit, String> {
    let sem = import_semaphore().clone();
    match sem.try_acquire_owned() {
        Ok(p) => Ok(p),
        Err(_) => Err(
            "package import admission limit reached (OPENFDD_IMPORT_MAX_INFLIGHT); retry later"
                .into(),
        ),
    }
}

/// Recursive byte size of a directory (files only). Missing path → 0.
pub fn dir_size_bytes(root: &Path) -> u64 {
    if !root.exists() {
        return 0;
    }
    let mut total = 0u64;
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let Ok(rd) = fs::read_dir(&dir) else {
            continue;
        };
        for ent in rd.flatten() {
            let path = ent.path();
            let Ok(meta) = ent.metadata() else {
                continue;
            };
            if meta.is_dir() {
                stack.push(path);
            } else if meta.is_file() {
                total = total.saturating_add(meta.len());
            }
        }
    }
    total
}

/// Historian parquet root for a building (hub layout).
pub fn building_history_dir(storage_root: &Path, building_id: &str) -> PathBuf {
    storage_root
        .join("history")
        .join(format!("building_id={building_id}"))
}

/// Deny when building history already at/over the size cap.
pub fn deny_if_over_size(
    limits: &HistorianLimits,
    storage: &Path,
    building_id: &str,
) -> Option<String> {
    let dir = building_history_dir(storage, building_id);
    let used = dir_size_bytes(&dir);
    let cap = limits.size_cap_bytes();
    if used >= cap {
        Some(format!(
            "historian size cap reached for building {building_id}: used≈{used} bytes, cap≈{cap} bytes ({:.2} GiB)",
            limits.size_gib
        ))
    } else {
        None
    }
}

/// Load limits + size check for a building under the configured storage root.
pub fn deny_building_over_size(workspace: &Path, building_id: &str) -> Option<String> {
    let limits = HistorianLimits::load(workspace);
    deny_if_over_size(&limits, &storage_root(), building_id)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn defaults_and_sanitize() {
        let mut lim = HistorianLimits::default();
        assert_eq!(lim.retain_days, 365);
        assert!((lim.size_gib - 5.0).abs() < 1e-9);
        lim.retain_days = 0;
        lim.size_gib = f64::NAN;
        lim.sanitize();
        assert_eq!(lim.retain_days, 365);
        assert!((lim.size_gib - 5.0).abs() < 1e-9);
    }

    #[test]
    fn save_load_roundtrip() {
        let dir = tempdir().unwrap();
        let lim = HistorianLimits {
            retain_days: 90,
            size_gib: 2.5,
        };
        lim.save(dir.path()).unwrap();
        let loaded = HistorianLimits::load(dir.path());
        assert_eq!(loaded.retain_days, 90);
        assert!((loaded.size_gib - 2.5).abs() < 1e-9);
    }

    #[test]
    fn dir_size_and_deny() {
        let dir = tempdir().unwrap();
        let hist = dir
            .path()
            .join("history")
            .join("building_id=ACME")
            .join("equipment_id=x");
        fs::create_dir_all(&hist).unwrap();
        fs::write(hist.join("part.parquet"), vec![0u8; 1024]).unwrap();
        let used = dir_size_bytes(&dir.path().join("history").join("building_id=ACME"));
        assert_eq!(used, 1024);
        let lim = HistorianLimits {
            retain_days: 365,
            size_gib: 0.000000001, // tiny → immediate deny
        };
        assert!(deny_if_over_size(&lim, dir.path(), "ACME").is_some());
    }
}
