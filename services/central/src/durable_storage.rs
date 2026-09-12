//! Wave M D2  fail readiness when authoritative storage is ephemeral in prod.

use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use tracing::info;

/// When true (Railway / prod), refuse `.cache` or relative WORKDIR paths for
/// authoritative rule results and require a writable parquet/workspace root.
pub fn require_durable_storage() -> bool {
    if let Ok(raw) = std::env::var("OPENFDD_REQUIRE_DURABLE_STORAGE") {
        return matches!(
            raw.trim().to_ascii_lowercase().as_str(),
            "1" | "true" | "yes" | "on"
        );
    }
    // Railway sets RAILWAY_ENVIRONMENT; treat as production unless explicitly off.
    std::env::var("RAILWAY_ENVIRONMENT").is_ok()
}

fn env_path(name: &str) -> Option<PathBuf> {
    std::env::var(name)
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .map(PathBuf::from)
}

/// Resolve the directory used for rule result JSON (authoritative).
pub fn resolve_rule_results_base() -> PathBuf {
    if let Some(p) = env_path("OPENFDD_RULE_RESULTS_DIR") {
        return p;
    }
    if let Some(root) = env_path("OPENFDD_PARQUET_ROOT") {
        return root.join("rule_results");
    }
    if let Some(url) = std::env::var("OPENFDD_STORAGE_URL").ok() {
        if let Some(path) = url.strip_prefix("file://") {
            let trimmed = path.trim();
            if !trimmed.is_empty() {
                return PathBuf::from(trimmed).join("rule_results");
            }
        }
    }
    if let Some(ws) = env_path("OPENFDD_WORKSPACE") {
        return ws.join("openfdd").join("rule_results");
    }
    PathBuf::from(".cache/rule_results")
}

fn looks_ephemeral(path: &Path) -> bool {
    let s = path.to_string_lossy();
    s.contains(".cache")
        || s.starts_with("/app/")
        || s == "/app"
        || (!path.is_absolute() && s.starts_with(".cache"))
}

/// Validate authoritative local storage before accepting traffic.
pub fn assert_authoritative_storage() -> Result<()> {
    let results = resolve_rule_results_base();
    let parquet = env_path("OPENFDD_PARQUET_ROOT");
    let workspace = env_path("OPENFDD_WORKSPACE");
    let require = require_durable_storage();

    if require {
        if looks_ephemeral(&results) {
            bail!(
                "authoritative rule results resolve to ephemeral path {} \
                 (set OPENFDD_RULE_RESULTS_DIR or OPENFDD_PARQUET_ROOT under a volume)",
                results.display()
            );
        }
        let Some(root) = parquet.or_else(|| {
            workspace
                .as_ref()
                .map(|w| w.join("openfdd"))
        }) else {
            bail!(
                "OPENFDD_REQUIRE_DURABLE_STORAGE / Railway requires \
                 OPENFDD_PARQUET_ROOT or OPENFDD_WORKSPACE"
            );
        };
        if looks_ephemeral(&root) {
            bail!(
                "authoritative parquet root looks ephemeral: {}",
                root.display()
            );
        }
        std::fs::create_dir_all(&root)
            .with_context(|| format!("create authoritative root {}", root.display()))?;
        std::fs::create_dir_all(&results)
            .with_context(|| format!("create rule results dir {}", results.display()))?;
        // Prove writability without leaving debris.
        let probe = results.join(".openfdd_storage_probe");
        std::fs::write(&probe, b"ok").with_context(|| {
            format!("authoritative storage not writable at {}", results.display())
        })?;
        let _ = std::fs::remove_file(&probe);
    } else {
        let _ = std::fs::create_dir_all(&results);
    }

    info!(
        results_dir = %results.display(),
        require_durable = require,
        "authoritative storage check passed"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_env_lock::lock_env;
    use tempfile::tempdir;

    #[test]
    fn ephemeral_detection() {
        assert!(looks_ephemeral(Path::new(".cache/rule_results")));
        assert!(looks_ephemeral(Path::new("/app/.cache/x")));
        assert!(!looks_ephemeral(Path::new("/workspace/openfdd/rule_results")));
    }

    #[test]
    fn prefers_parquet_root_over_cache() {
        let _g = lock_env();
        let dir = tempdir().unwrap();
        let root = dir.path().join("openfdd");
        std::env::set_var("OPENFDD_PARQUET_ROOT", &root);
        std::env::remove_var("OPENFDD_RULE_RESULTS_DIR");
        let resolved = resolve_rule_results_base();
        std::env::remove_var("OPENFDD_PARQUET_ROOT");
        assert_eq!(resolved, root.join("rule_results"));
    }
}
