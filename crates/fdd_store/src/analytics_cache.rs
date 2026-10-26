//! Analytics / RCx / fault result cache identity and freshness.
//!
//! The cache rows live in the PostgreSQL `analytics_result` table (central
//! `analytics::result_store`). This module only defines the cache key, the
//! provenance stamped on each row, and the freshness rules that decide hit,
//! stale, miss, incompatible, or unavailable.

use std::fs;
use std::path::Path;

use anyhow::{bail, Context, Result};
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::historian::safe_partition_value;

/// Directory of the retired Parquet result cache. Central never writes it.
pub const RESULTS_DIR: &str = "analytics_results";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CacheFreshness {
    Hit,
    Stale,
    Miss,
    /// Persisted envelope is missing identity or does not match the current
    /// contract, pack, or model. Callers recompute. They do not serve it as fresh.
    Incompatible,
    /// The current watermark read failed or is otherwise unknown. Never a hit.
    Unavailable,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StaleAction {
    /// Return the cached table and set `stale` so charts are not silently fresh.
    ServeStale,
    /// Recompute when the historian watermark moved.
    Recompute,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ReadPlan {
    pub recompute: bool,
    pub serve_cached: bool,
    pub stale: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AnalyticsCacheKey {
    pub building_id: String,
    pub query_id: String,
    pub query_version: String,
    pub window_start: String,
    pub window_end: String,
    pub config_hash: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct AnalyticsResultTable {
    pub rows: Vec<Value>,
    pub equipment: Vec<Value>,
    pub points: Vec<Value>,
    pub skipped: Vec<Value>,
    pub warnings: Vec<String>,
    pub coverage: Option<Value>,
    pub engine: String,
    pub result_query_version: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CacheProvenance {
    pub building_id: String,
    pub query_id: String,
    pub query_version: String,
    pub window_start: String,
    pub window_end: String,
    pub config_hash: String,
    pub watermark_order: u64,
    pub watermark_utc: String,
    pub generated_at: String,
    pub engine: String,
    pub result_query_version: String,
    /// Semantic result contract. Empty means an unstamped pre-upgrade envelope.
    pub result_contract: String,
    /// Analytics SQL pack plus FDD pack fingerprint.
    pub sql_pack: String,
    /// Site model fingerprint. Empty means the revision was not recorded.
    pub model_revision: String,
    /// `timescale` or `parquet` when the watermark read succeeded.
    pub watermark_source: String,
    /// `known` only after a successful watermark read. Never inferred from 0.
    pub watermark_status: String,
    /// Scoped input coverage (counts and bounds), not only the max timestamp.
    pub coverage: String,
}

pub fn config_hash(material: &str) -> String {
    let digest = Sha256::digest(material.as_bytes());
    hex_encode(&digest)
}

pub fn read_plan(freshness: CacheFreshness, refresh: bool, on_stale: StaleAction) -> ReadPlan {
    if refresh {
        return ReadPlan {
            recompute: true,
            serve_cached: false,
            stale: false,
        };
    }
    match freshness {
        CacheFreshness::Hit => ReadPlan {
            recompute: false,
            serve_cached: true,
            stale: false,
        },
        CacheFreshness::Stale => match on_stale {
            StaleAction::ServeStale => ReadPlan {
                recompute: false,
                serve_cached: true,
                stale: true,
            },
            StaleAction::Recompute => ReadPlan {
                recompute: true,
                serve_cached: false,
                stale: false,
            },
        },
        CacheFreshness::Miss | CacheFreshness::Incompatible => ReadPlan {
            recompute: true,
            serve_cached: false,
            stale: false,
        },
        // A failed read must not certify the last envelope as fresh.
        CacheFreshness::Unavailable => {
            if refresh {
                ReadPlan {
                    recompute: true,
                    serve_cached: false,
                    stale: false,
                }
            } else {
                ReadPlan {
                    recompute: false,
                    serve_cached: true,
                    stale: true,
                }
            }
        }
    }
}

/// Order-only comparison. Equal orders are a hit, including `0 == 0`.
/// Callers must not pass `0` for a failed or skipped read. Use
/// [`freshness_for_identity`] for result contract, pack, model, and coverage.
pub fn freshness_for_watermark(cached_order: u64, historian_order: u64) -> CacheFreshness {
    if historian_order > cached_order {
        CacheFreshness::Stale
    } else {
        CacheFreshness::Hit
    }
}

/// Computation identity compared with a persisted envelope.
///
/// `result_contract`, `sql_pack`, and `model_revision` are part of the cache
/// key. Watermark and coverage are compared here so a newer Timescale input
/// can still find the previous envelope and mark it stale.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CacheIdentity {
    pub result_contract: String,
    pub sql_pack: String,
    pub model_revision: String,
    pub watermark: InputWatermark,
}

/// Scoped historian input. `Unavailable` is a failed or missing read.
/// It is not an empty successful scan.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InputWatermark {
    Known {
        source: String,
        order: u64,
        utc: String,
        coverage: String,
    },
    Unavailable {
        reason: String,
    },
}

/// Compatible only when the persisted envelope carries the same non-empty
/// contract, pack, and model and was written from a known watermark.
/// A failed current read is [`CacheFreshness::Unavailable`], never a hit.
pub fn freshness_for_identity(cached: &CacheProvenance, current: &CacheIdentity) -> CacheFreshness {
    if !stamped_identity_matches(cached, current) {
        return CacheFreshness::Incompatible;
    }
    match &current.watermark {
        InputWatermark::Unavailable { .. } => CacheFreshness::Unavailable,
        InputWatermark::Known {
            source,
            order,
            coverage,
            ..
        } => {
            if cached.watermark_source != *source {
                return CacheFreshness::Incompatible;
            }
            if cached.watermark_order != *order || cached.coverage != *coverage {
                CacheFreshness::Stale
            } else {
                CacheFreshness::Hit
            }
        }
    }
}

fn stamped_identity_matches(cached: &CacheProvenance, current: &CacheIdentity) -> bool {
    !cached.result_contract.is_empty()
        && cached.result_contract == current.result_contract
        && !cached.sql_pack.is_empty()
        && cached.sql_pack == current.sql_pack
        && !cached.model_revision.is_empty()
        && cached.model_revision == current.model_revision
        && cached.watermark_status == "known"
}

/// Delete one building's derived analytics parquet cache.
///
/// Historian parts and labeled rule-result files live outside `analytics_results/`
/// and are not removed.
pub fn remove_derived_result_cache(storage_root: &Path, building_id: &str) -> Result<u64> {
    let building = safe_partition_value(building_id, "building_id")?;
    let dir = storage_root
        .join(RESULTS_DIR)
        .join(format!("building_id={building}"));
    if !dir.exists() {
        return Ok(0);
    }
    if !dir.is_dir() {
        bail!("derived cache path is not a directory: {}", dir.display());
    }
    let removed = count_files(&dir)?;
    fs::remove_dir_all(&dir).with_context(|| format!("remove derived cache {}", dir.display()))?;
    Ok(removed)
}

fn count_files(dir: &Path) -> Result<u64> {
    let mut count = 0u64;
    let mut stack = vec![dir.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let rd = fs::read_dir(&dir).with_context(|| format!("read {}", dir.display()))?;
        for ent in rd {
            let ent = ent.with_context(|| format!("read entry under {}", dir.display()))?;
            let path = ent.path();
            let meta = ent
                .metadata()
                .with_context(|| format!("stat {}", path.display()))?;
            if meta.is_dir() {
                stack.push(path);
            } else if meta.is_file() {
                count += 1;
            }
        }
    }
    Ok(count)
}

fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0f) as usize] as char);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(hash: &str) -> AnalyticsCacheKey {
        AnalyticsCacheKey {
            building_id: "site-a".into(),
            query_id: "runtime".into(),
            query_version: "runtime-v1".into(),
            window_start: "2026-01-01T00:00:00Z".into(),
            window_end: "2026-01-08T00:00:00Z".into(),
            config_hash: hash.into(),
        }
    }

    fn provenance(key: &AnalyticsCacheKey, hash: &str, order: u64) -> CacheProvenance {
        CacheProvenance {
            building_id: key.building_id.clone(),
            query_id: key.query_id.clone(),
            query_version: key.query_version.clone(),
            window_start: key.window_start.clone(),
            window_end: key.window_end.clone(),
            config_hash: hash.to_string(),
            watermark_order: order,
            watermark_utc: String::new(),
            generated_at: "t".into(),
            engine: "timescale-sql".into(),
            result_query_version: key.query_version.clone(),
            result_contract: "analytics-result-contract-v2".into(),
            sql_pack: "pack".into(),
            model_revision: "model".into(),
            watermark_source: "timescale".into(),
            watermark_status: "known".into(),
            coverage: format!("samples={order};series=1"),
        }
    }

    #[test]
    fn watermark_past_cache_is_stale_and_not_a_fresh_hit() {
        assert_eq!(
            freshness_for_watermark(20260101000000, 20260102000000),
            CacheFreshness::Stale
        );
        assert_eq!(
            freshness_for_watermark(20260102000000, 20260102000000),
            CacheFreshness::Hit
        );
        let stale = read_plan(CacheFreshness::Stale, false, StaleAction::ServeStale);
        assert!(stale.serve_cached && stale.stale && !stale.recompute);
        let refresh = read_plan(CacheFreshness::Hit, true, StaleAction::ServeStale);
        assert!(refresh.recompute && !refresh.stale);
        let recompute = read_plan(CacheFreshness::Stale, false, StaleAction::Recompute);
        assert!(recompute.recompute && !recompute.serve_cached);
    }

    fn known_identity(model: &str, order: u64, coverage: &str) -> CacheIdentity {
        CacheIdentity {
            result_contract: "analytics-result-contract-v2".into(),
            sql_pack: "pack".into(),
            model_revision: model.into(),
            watermark: InputWatermark::Known {
                source: "timescale".into(),
                order,
                utc: String::new(),
                coverage: coverage.into(),
            },
        }
    }

    #[test]
    fn unstamped_zero_watermark_is_not_a_fresh_hit() {
        let cached = provenance(&key("h"), "h", 0);
        let mut unstamped = cached.clone();
        unstamped.result_contract.clear();
        unstamped.sql_pack.clear();
        unstamped.model_revision.clear();
        unstamped.watermark_status.clear();
        unstamped.coverage.clear();
        let current = known_identity("model", 0, "samples=0;series=0");
        assert_eq!(
            freshness_for_identity(&unstamped, &current),
            CacheFreshness::Incompatible
        );
        let mut other_source = cached.clone();
        other_source.watermark_source = "legacy".into();
        assert_eq!(
            freshness_for_identity(&other_source, &current),
            CacheFreshness::Incompatible
        );
        let mut timescale = cached;
        timescale.watermark_source = "timescale".into();
        timescale.coverage = "samples=0;series=0".into();
        assert_eq!(
            freshness_for_identity(&timescale, &current),
            CacheFreshness::Hit
        );
    }

    #[test]
    fn coverage_or_model_change_and_failed_read_are_not_fresh() {
        let cached = provenance(&key("h"), "h", 10);
        let mut timescale = cached;
        timescale.watermark_source = "timescale".into();
        timescale.coverage = "samples=2;series=1".into();
        let same = known_identity("model", 10, "samples=2;series=1");
        assert_eq!(
            freshness_for_identity(&timescale, &same),
            CacheFreshness::Hit
        );
        assert_eq!(
            freshness_for_identity(
                &timescale,
                &known_identity("model", 10, "samples=3;series=1")
            ),
            CacheFreshness::Stale
        );
        assert_eq!(
            freshness_for_identity(
                &timescale,
                &known_identity("model-b", 10, "samples=2;series=1")
            ),
            CacheFreshness::Incompatible
        );
        let mut failed = same;
        failed.watermark = InputWatermark::Unavailable {
            reason: "timescale watermark read failed".into(),
        };
        assert_eq!(
            freshness_for_identity(&timescale, &failed),
            CacheFreshness::Unavailable
        );
        let plan = read_plan(CacheFreshness::Unavailable, false, StaleAction::ServeStale);
        assert!(plan.serve_cached && plan.stale && !plan.recompute);
        let incompatible = read_plan(CacheFreshness::Incompatible, false, StaleAction::ServeStale);
        assert!(incompatible.recompute && !incompatible.serve_cached);
    }

    #[test]
    fn derived_cache_repair_keeps_historian_and_labeled_results() {
        let tmp = tempfile::tempdir().unwrap();
        let history = tmp
            .path()
            .join("history/building_id=site-a/equipment_id=ahu/year=2026/month=06");
        fs::create_dir_all(&history).unwrap();
        let sample = history.join("part-20260601T000000Z-live.parquet");
        fs::write(&sample, b"sample").unwrap();
        let labeled = tmp.path().join("rule_results/site-a");
        fs::create_dir_all(&labeled).unwrap();
        let rule = labeled.join("FC1.json");
        fs::write(&rule, br#"{"rule_id":"FC1","rows":[{"status":"PASS"}]}"#).unwrap();
        let other = tmp
            .path()
            .join("analytics_results/building_id=site-b/query_id=runtime");
        fs::create_dir_all(&other).unwrap();
        fs::write(other.join("results.parquet"), b"other").unwrap();
        let mine = tmp
            .path()
            .join("analytics_results/building_id=site-a/query_id=runtime");
        fs::create_dir_all(&mine).unwrap();
        fs::write(mine.join("results.parquet"), b"mine").unwrap();

        let removed = remove_derived_result_cache(tmp.path(), "site-a").unwrap();
        assert!(removed >= 1);
        assert!(sample.is_file());
        assert!(rule.is_file());
        assert!(other.join("results.parquet").is_file());
        assert!(!mine.exists());
        assert_eq!(
            remove_derived_result_cache(tmp.path(), "site-a").unwrap(),
            0
        );
    }
}
