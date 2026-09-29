//! Local/edge disk budget for historian parquet and analytics result parquet.
//!
//! Default cap is 100 GiB, oldest partition first, newest kept. Railway volume
//! policy is a separate knob: when `RAILWAY_ENVIRONMENT` is set and
//! `OPENFDD_DATA_BUDGET_ENABLED` is unset, eviction stays off.
//!
//! Update preflight refuses an on-box backup that would need another full copy
//! of live data on a small disk. Test deploys skip that backup unless the
//! operator asks. #1049 field proof on a real edge disk is out of band; this
//! module is the decision and eviction logic.

use std::fs;
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

use anyhow::{Context, Result};
use chrono::{TimeZone, Utc};

use crate::analytics_cache::RESULTS_DIR;

pub const DEFAULT_LOCAL_DATA_BUDGET_GIB: u64 = 100;
pub const GIB: u64 = 1024 * 1024 * 1024;
pub const DEFAULT_RESERVED_FREE_PERCENT: u8 = 10;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DataBudget {
    pub budget_bytes: u64,
    pub enabled: bool,
    pub reserved_free_percent: u8,
}

impl DataBudget {
    pub fn local_default() -> Self {
        Self {
            budget_bytes: DEFAULT_LOCAL_DATA_BUDGET_GIB.saturating_mul(GIB),
            enabled: true,
            reserved_free_percent: DEFAULT_RESERVED_FREE_PERCENT,
        }
    }

    /// `enabled` follows the local default unless Railway is detected and the
    /// operator did not set `OPENFDD_DATA_BUDGET_ENABLED`.
    pub fn from_env() -> Self {
        let railway = std::env::var("RAILWAY_ENVIRONMENT")
            .ok()
            .is_some_and(|v| !v.trim().is_empty());
        let enabled = match std::env::var("OPENFDD_DATA_BUDGET_ENABLED") {
            Ok(v) => env_truthy(&v),
            Err(_) => !railway,
        };
        let gib = std::env::var("OPENFDD_LOCAL_DATA_BUDGET_GIB")
            .ok()
            .and_then(|s| s.trim().parse::<u64>().ok())
            .filter(|n| *n > 0)
            .unwrap_or(DEFAULT_LOCAL_DATA_BUDGET_GIB);
        let reserved = std::env::var("OPENFDD_DISK_RESERVED_FREE_PERCENT")
            .ok()
            .and_then(|s| s.trim().parse::<u8>().ok())
            .map(|n| n.clamp(1, 50))
            .unwrap_or(DEFAULT_RESERVED_FREE_PERCENT);
        Self {
            budget_bytes: gib.saturating_mul(GIB),
            enabled,
            reserved_free_percent: reserved,
        }
    }
}

fn env_truthy(value: &str) -> bool {
    matches!(
        value.trim(),
        "1" | "true" | "TRUE" | "yes" | "YES" | "on" | "ON"
    )
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BudgetObject {
    pub path: PathBuf,
    pub bytes: u64,
    /// Smaller means older. `YYYYMMDDHHMMSS`.
    pub order_key: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EvictionPlan {
    pub drop: Vec<PathBuf>,
    pub drop_bytes: u64,
    pub keep_bytes: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EvictionReport {
    pub applied: bool,
    pub reason: String,
    pub dropped: Vec<PathBuf>,
    pub dropped_bytes: u64,
    pub keep_bytes: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreflightInput {
    pub disk_total_bytes: u64,
    pub disk_free_bytes: u64,
    pub backup_bytes: u64,
    pub reserved_free_percent: u8,
    pub bytes_over_budget: u64,
    pub operator_requested_backup: bool,
    pub test_deploy: bool,
    pub backup_required: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PreflightDecision {
    ProceedWithBackup,
    SkipBackup { reason: String },
    PruneThenBackup { reclaim_bytes: u64 },
    FailClosed { reason: String },
}

pub fn order_key_from_path(path: &Path, mtime_unix: u64) -> u64 {
    let text = path.to_string_lossy();
    if let Some(key) = part_stamp_key(&text) {
        return key;
    }
    if let Some(key) = year_month_key(&text) {
        return key;
    }
    mtime_key(mtime_unix)
}

pub fn plan_oldest_first(objects: &[BudgetObject], budget_bytes: u64) -> EvictionPlan {
    let mut ordered = objects.to_vec();
    ordered.sort_by(|a, b| {
        a.order_key
            .cmp(&b.order_key)
            .then_with(|| a.path.cmp(&b.path))
    });
    let total: u64 = ordered.iter().map(|o| o.bytes).sum();
    if total <= budget_bytes {
        return EvictionPlan {
            drop: Vec::new(),
            drop_bytes: 0,
            keep_bytes: total,
        };
    }
    let mut drop = Vec::new();
    let mut dropped = 0u64;
    let mut remaining = ordered.len();
    for obj in &ordered {
        if total.saturating_sub(dropped) <= budget_bytes {
            break;
        }
        if remaining <= 1 {
            break;
        }
        drop.push(obj.path.clone());
        dropped = dropped.saturating_add(obj.bytes);
        remaining -= 1;
    }
    EvictionPlan {
        drop,
        drop_bytes: dropped,
        keep_bytes: total.saturating_sub(dropped),
    }
}

pub fn collect_budget_objects(storage_root: &Path) -> Vec<BudgetObject> {
    let mut out = Vec::new();
    if !storage_root.is_dir() {
        return out;
    }
    let mut stack = vec![storage_root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let Ok(rd) = fs::read_dir(&dir) else {
            continue;
        };
        for ent in rd.flatten() {
            let path = ent.path();
            if !path.starts_with(storage_root) {
                continue;
            }
            let Ok(meta) = ent.metadata() else {
                continue;
            };
            if meta.is_dir() {
                if !dir_in_budget(&path, storage_root) {
                    continue;
                }
                stack.push(path);
                continue;
            }
            if !meta.is_file() || !is_parquet(&path) {
                continue;
            }
            if !file_in_budget(&path, storage_root) {
                continue;
            }
            let mtime = meta
                .modified()
                .ok()
                .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
                .map(|d| d.as_secs())
                .unwrap_or(0);
            out.push(BudgetObject {
                path,
                bytes: meta.len(),
                order_key: order_key_from_path(&ent.path(), mtime),
            });
        }
    }
    out
}

pub fn apply_eviction(storage_root: &Path, plan: &EvictionPlan) -> Result<u64> {
    let root = storage_root.canonicalize().unwrap_or_else(|_| storage_root.to_path_buf());
    let mut deleted = 0u64;
    for path in &plan.drop {
        let Ok(meta) = fs::metadata(path) else {
            continue;
        };
        let canonical = path.canonicalize().unwrap_or_else(|_| path.clone());
        if !canonical.starts_with(&root) && !path.starts_with(storage_root) {
            continue;
        }
        if meta.is_file() {
            fs::remove_file(path).with_context(|| format!("remove {}", path.display()))?;
            deleted = deleted.saturating_add(meta.len());
            prune_empty_parents(path, storage_root);
        }
    }
    Ok(deleted)
}

pub fn apply_data_budget(storage_root: &Path, budget: &DataBudget) -> Result<EvictionReport> {
    if !budget.enabled {
        return Ok(EvictionReport {
            applied: false,
            reason: "data budget disabled".into(),
            dropped: Vec::new(),
            dropped_bytes: 0,
            keep_bytes: collect_budget_objects(storage_root)
                .iter()
                .map(|o| o.bytes)
                .sum(),
        });
    }
    let objects = collect_budget_objects(storage_root);
    let plan = plan_oldest_first(&objects, budget.budget_bytes);
    if plan.drop.is_empty() {
        return Ok(EvictionReport {
            applied: false,
            reason: "within budget".into(),
            dropped: Vec::new(),
            dropped_bytes: 0,
            keep_bytes: plan.keep_bytes,
        });
    }
    let dropped_bytes = apply_eviction(storage_root, &plan)?;
    Ok(EvictionReport {
        applied: true,
        reason: "evicted oldest parquet under the data budget".into(),
        dropped: plan.drop,
        dropped_bytes,
        keep_bytes: plan.keep_bytes,
    })
}

pub fn bytes_over_budget(used: u64, budget_bytes: u64) -> u64 {
    used.saturating_sub(budget_bytes)
}

pub fn preflight_update(input: &PreflightInput) -> PreflightDecision {
    let pct = u64::from(input.reserved_free_percent.clamp(0, 50));
    let reserved = input.disk_total_bytes.saturating_mul(pct) / 100;
    let free_after_prune = input
        .disk_free_bytes
        .saturating_add(input.bytes_over_budget);

    if input.test_deploy && !input.operator_requested_backup {
        if input.disk_free_bytes < reserved && input.bytes_over_budget == 0 {
            return PreflightDecision::FailClosed {
                reason: "free space is below the reserved percent; refusing the update".into(),
            };
        }
        return PreflightDecision::SkipBackup {
            reason: "test deploy skips on-box backup unless OPENFDD_BACKUP_ON_UPDATE=1".into(),
        };
    }

    let free_for_backup = if input.bytes_over_budget > 0 {
        free_after_prune
    } else {
        input.disk_free_bytes
    };
    let fits = free_for_backup >= input.backup_bytes.saturating_add(reserved);

    if fits {
        if input.bytes_over_budget > 0 {
            return PreflightDecision::PruneThenBackup {
                reclaim_bytes: input.bytes_over_budget,
            };
        }
        return PreflightDecision::ProceedWithBackup;
    }

    if free_for_backup < reserved {
        return PreflightDecision::FailClosed {
            reason: "free space stays below the reserved percent even without an on-box backup"
                .into(),
        };
    }
    if input.backup_required {
        return PreflightDecision::FailClosed {
            reason: "on-box backup plus reserved free space exceeds disk headroom".into(),
        };
    }
    PreflightDecision::SkipBackup {
        reason: "insufficient headroom for an on-box backup; do not assume 2x live data fits on a ~200 GiB edge"
            .into(),
    }
}

fn part_stamp_key(text: &str) -> Option<u64> {
    let bytes = text.as_bytes();
    let marker = b"part-";
    let mut search = 0;
    while let Some(rel) = text[search..].find("part-") {
        let start = search + rel + marker.len();
        let rest = &bytes.get(start..)?;
        if rest.len() >= 15
            && rest[8] == b'T'
            && rest.get(15).is_some_and(|c| *c == b'Z' || *c == b'-' || *c == b'.')
        {
            let digits = format!(
                "{}{}{}{}{}{}",
                std::str::from_utf8(rest.get(0..4)?).ok()?,
                std::str::from_utf8(rest.get(4..6)?).ok()?,
                std::str::from_utf8(rest.get(6..8)?).ok()?,
                std::str::from_utf8(rest.get(9..11)?).ok()?,
                std::str::from_utf8(rest.get(11..13)?).ok()?,
                std::str::from_utf8(rest.get(13..15)?).ok()?,
            );
            if digits.chars().all(|c| c.is_ascii_digit()) {
                if let Ok(n) = digits.parse::<u64>() {
                    return Some(n);
                }
            }
        }
        search = start;
        if search >= text.len() {
            break;
        }
    }
    None
}

fn year_month_key(text: &str) -> Option<u64> {
    let year = capture_eq_number(text, "year=")?;
    let month = capture_eq_number(text, "month=")?;
    if !(1..=12).contains(&month) || !(1970..=9999).contains(&year) {
        return None;
    }
    Some(year * 10_000_000_000 + month * 100_000_000 + 1_000_000)
}

fn capture_eq_number(text: &str, marker: &str) -> Option<u64> {
    let start = text.find(marker)? + marker.len();
    let rest = &text[start..];
    let digits: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
    if digits.is_empty() {
        return None;
    }
    digits.parse().ok()
}

fn mtime_key(unix: u64) -> u64 {
    let dt = Utc.timestamp_opt(unix as i64, 0).single();
    let Some(dt) = dt else {
        return 0;
    };
    let y = dt.format("%Y%m%d%H%M%S").to_string();
    y.parse().unwrap_or(0)
}

fn is_parquet(path: &Path) -> bool {
    path.extension()
        .and_then(|e| e.to_str())
        .is_some_and(|e| e.eq_ignore_ascii_case("parquet"))
}

fn dir_in_budget(path: &Path, root: &Path) -> bool {
    if path == root {
        return true;
    }
    file_in_budget(path, root) || ancestor_is_budget_tree(path, root)
}

fn ancestor_is_budget_tree(path: &Path, root: &Path) -> bool {
    let Ok(rel) = path.strip_prefix(root) else {
        return false;
    };
    let mut cur = PathBuf::new();
    for comp in rel.components() {
        cur.push(comp);
        if component_is_budget_root(cur.as_path()) {
            return true;
        }
    }
    false
}

fn file_in_budget(path: &Path, root: &Path) -> bool {
    let Ok(rel) = path.strip_prefix(root) else {
        return false;
    };
    let parts: Vec<String> = rel
        .components()
        .filter_map(|c| c.as_os_str().to_str().map(str::to_string))
        .collect();
    if parts.is_empty() {
        return false;
    }
    if parts.iter().any(|p| p == "backups" || p == "archives") {
        return false;
    }
    budget_tree(&parts)
}

fn component_is_budget_root(rel: &Path) -> bool {
    let parts: Vec<String> = rel
        .components()
        .filter_map(|c| c.as_os_str().to_str().map(str::to_string))
        .collect();
    budget_tree(&parts)
}

fn budget_tree(parts: &[String]) -> bool {
    if parts.is_empty() {
        return false;
    }
    if parts[0] == "history" || parts[0] == RESULTS_DIR {
        return true;
    }
    if parts[0].starts_with("building=") {
        return true;
    }
    if parts[0] == "tenants" {
        return parts.iter().any(|p| p == "history" || p == RESULTS_DIR)
            || parts.len() <= 2;
    }
    false
}

fn prune_empty_parents(file: &Path, root: &Path) {
    let mut cur = file.parent().map(Path::to_path_buf);
    while let Some(dir) = cur {
        if dir == root || !dir.starts_with(root) {
            break;
        }
        let empty = fs::read_dir(&dir)
            .map(|mut rd| rd.next().is_none())
            .unwrap_or(false);
        if !empty {
            break;
        }
        if fs::remove_dir(&dir).is_err() {
            break;
        }
        cur = dir.parent().map(Path::to_path_buf);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn obj(name: &str, bytes: u64, key: u64) -> BudgetObject {
        BudgetObject {
            path: PathBuf::from(name),
            bytes,
            order_key: key,
        }
    }

    #[test]
    fn default_budget_is_100_gib() {
        let budget = DataBudget::local_default();
        assert_eq!(DEFAULT_LOCAL_DATA_BUDGET_GIB, 100);
        assert_eq!(budget.budget_bytes, 100 * GIB);
        assert!(budget.enabled);
        assert_eq!(budget.reserved_free_percent, 10);
    }

    #[test]
    fn oldest_first_keeps_newest_and_stops_at_budget() {
        let objects = vec![
            obj("old", 40, 20240101000000),
            obj("mid", 40, 20240601000000),
            obj("new", 40, 20241201000000),
        ];
        let plan = plan_oldest_first(&objects, 50);
        assert_eq!(
            plan.drop,
            vec![PathBuf::from("old"), PathBuf::from("mid")]
        );
        assert_eq!(plan.keep_bytes, 40);
        let under = plan_oldest_first(&objects, 120);
        assert!(under.drop.is_empty());
        assert_eq!(under.keep_bytes, 120);
    }

    #[test]
    fn single_newest_file_over_budget_is_kept() {
        let objects = vec![obj("only", 500, 20260101000000)];
        let plan = plan_oldest_first(&objects, 100);
        assert!(plan.drop.is_empty());
        assert_eq!(plan.keep_bytes, 500);
    }

    #[test]
    fn apply_deletes_oldest_historian_and_analytics_parquet_only() {
        let tmp = tempfile::tempdir().unwrap();
        let old = tmp.path().join(
            "history/building_id=site-a/equipment_id=ahu/year=2024/month=01/part-20240101T000000Z-live.parquet",
        );
        let new = tmp.path().join(
            "history/building_id=site-a/equipment_id=ahu/year=2026/month=06/part-20260601T000000Z-live.parquet",
        );
        let analytics = tmp
            .path()
            .join("analytics_results/building_id=site-a/query_id=runtime/part-20240102T000000Z.parquet");
        let archive = tmp.path().join("archives/keep.parquet");
        for path in [&old, &new, &analytics, &archive] {
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, vec![1u8; 32]).unwrap();
        }
        let budget = DataBudget {
            budget_bytes: 40,
            enabled: true,
            reserved_free_percent: 10,
        };
        let report = apply_data_budget(tmp.path(), &budget).unwrap();
        assert!(report.applied);
        assert!(!old.exists());
        assert!(!analytics.exists());
        assert!(new.exists(), "newest historian part stays");
        assert!(archive.exists(), "off-box archives are not eviction targets");
    }

    #[test]
    fn disabled_budget_does_not_delete() {
        let tmp = tempfile::tempdir().unwrap();
        let file = tmp
            .path()
            .join("history/building_id=site-a/part-20240101T000000Z.parquet");
        fs::create_dir_all(file.parent().unwrap()).unwrap();
        fs::write(&file, vec![1u8; 8]).unwrap();
        let budget = DataBudget {
            budget_bytes: 1,
            enabled: false,
            reserved_free_percent: 10,
        };
        let report = apply_data_budget(tmp.path(), &budget).unwrap();
        assert!(!report.applied);
        assert!(file.exists());
    }

    fn input(partial: PreflightInput) -> PreflightInput {
        partial
    }

    #[test]
    fn preflight_cases() {
        let gib = GIB;
        let base = PreflightInput {
            disk_total_bytes: 200 * gib,
            disk_free_bytes: 80 * gib,
            backup_bytes: 40 * gib,
            reserved_free_percent: 10,
            bytes_over_budget: 0,
            operator_requested_backup: false,
            test_deploy: false,
            backup_required: false,
        };

        let test_skip = preflight_update(&input(PreflightInput {
            test_deploy: true,
            ..base.clone()
        }));
        assert!(matches!(test_skip, PreflightDecision::SkipBackup { .. }));

        let test_asked = preflight_update(&input(PreflightInput {
            test_deploy: true,
            operator_requested_backup: true,
            ..base.clone()
        }));
        assert_eq!(test_asked, PreflightDecision::ProceedWithBackup);

        let tight_test = preflight_update(&input(PreflightInput {
            test_deploy: true,
            disk_free_bytes: 1 * gib,
            ..base.clone()
        }));
        assert!(matches!(tight_test, PreflightDecision::FailClosed { .. }));

        let no_room_for_copy = preflight_update(&input(PreflightInput {
            disk_free_bytes: 30 * gib,
            backup_bytes: 90 * gib,
            operator_requested_backup: true,
            ..base.clone()
        }));
        assert!(
            matches!(no_room_for_copy, PreflightDecision::SkipBackup { .. }),
            "{no_room_for_copy:?}"
        );

        let required = preflight_update(&input(PreflightInput {
            disk_free_bytes: 30 * gib,
            backup_bytes: 90 * gib,
            operator_requested_backup: true,
            backup_required: true,
            ..base.clone()
        }));
        assert!(matches!(required, PreflightDecision::FailClosed { .. }));

        let prune = preflight_update(&input(PreflightInput {
            disk_free_bytes: 20 * gib,
            backup_bytes: 50 * gib,
            bytes_over_budget: 60 * gib,
            operator_requested_backup: true,
            ..base.clone()
        }));
        assert_eq!(
            prune,
            PreflightDecision::PruneThenBackup {
                reclaim_bytes: 60 * gib
            }
        );

        let ok = preflight_update(&input(PreflightInput {
            operator_requested_backup: true,
            ..base
        }));
        assert_eq!(ok, PreflightDecision::ProceedWithBackup);
    }

    #[test]
    fn part_stamp_orders_before_later_month() {
        let old = order_key_from_path(
            Path::new("history/building_id=s/part-20240115T120000Z-live.parquet"),
            0,
        );
        let newer = order_key_from_path(
            Path::new("history/building_id=s/year=2026/month=06/file.parquet"),
            0,
        );
        assert!(old < newer);
        assert_eq!(old, 20240115120000);
        assert_eq!(newer, 20260601000000);
    }
}
