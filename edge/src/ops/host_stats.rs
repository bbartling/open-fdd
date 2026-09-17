//! Host resource stats for the Host / Data Management UI.

use crate::data_management;
use chrono::Utc;
use fdd_store::stats::HistorianStats;
use fdd_store::HistorianConfig;
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

fn read_to_string(path: &str) -> Option<String> {
    fs::read_to_string(path).ok()
}

fn read_u64_file(path: &Path) -> Option<u64> {
    let raw = fs::read_to_string(path).ok()?;
    let trimmed = raw.trim();
    if trimmed.eq_ignore_ascii_case("max") {
        return None;
    }
    trimmed.parse().ok()
}

fn logical_cores() -> u64 {
    read_to_string("/proc/cpuinfo")
        .map(|s| s.lines().filter(|l| l.starts_with("processor")).count() as u64)
        .filter(|n| *n > 0)
        .unwrap_or(1)
}

fn load_averages() -> (Option<f64>, Option<f64>, Option<f64>) {
    let Some(line) = read_to_string("/proc/loadavg") else {
        return (None, None, None);
    };
    let parts: Vec<&str> = line.split_whitespace().collect();
    if parts.len() < 3 {
        return (None, None, None);
    }
    (
        parts[0].parse().ok(),
        parts[1].parse().ok(),
        parts[2].parse().ok(),
    )
}

fn cgroup_memory_paths() -> Vec<PathBuf> {
    let mut bases = Vec::new();
    if let Ok(custom) = env::var("OPENFDD_CGROUP_DIR") {
        let trimmed = custom.trim();
        if !trimmed.is_empty() {
            bases.push(PathBuf::from(trimmed));
        }
    }
    bases.push(PathBuf::from("/sys/fs/cgroup"));
    bases
}

fn cgroup_memory_block() -> Value {
    for base in cgroup_memory_paths() {
        let current_v2 = base.join("memory.current");
        let max_v2 = base.join("memory.max");
        if current_v2.is_file() {
            let used = read_u64_file(&current_v2);
            let limit = read_u64_file(&max_v2);
            if let Some(used_bytes) = used {
                let (total_bytes, percent_used) = match limit {
                    Some(limit_bytes) if limit_bytes > 0 => {
                        let pct = (used_bytes as f64 / limit_bytes as f64) * 100.0;
                        (Some(limit_bytes), Some((pct * 10.0).round() / 10.0))
                    }
                    _ => (None, None),
                };
                return json!({
                    "available": true,
                    "source": "cgroup",
                    "used_bytes": used_bytes,
                    "total_bytes": total_bytes,
                    "available_bytes": total_bytes.map(|t| t.saturating_sub(used_bytes)),
                    "percent_used": percent_used,
                    "note": "Container cgroup memory (preferred over host /proc/meminfo on shared nodes)"
                });
            }
        }
        let current_v1 = base.join("memory/memory.usage_in_bytes");
        let max_v1 = base.join("memory/memory.limit_in_bytes");
        if current_v1.is_file() {
            let used = read_u64_file(&current_v1);
            let limit = read_u64_file(&max_v1);
            if let Some(used_bytes) = used {
                let (total_bytes, percent_used) = match limit {
                    Some(limit_bytes) if limit_bytes > 0 && limit_bytes < u64::MAX / 2 => {
                        let pct = (used_bytes as f64 / limit_bytes as f64) * 100.0;
                        (Some(limit_bytes), Some((pct * 10.0).round() / 10.0))
                    }
                    _ => (None, None),
                };
                return json!({
                    "available": true,
                    "source": "cgroup",
                    "used_bytes": used_bytes,
                    "total_bytes": total_bytes,
                    "available_bytes": total_bytes.map(|t| t.saturating_sub(used_bytes)),
                    "percent_used": percent_used,
                    "note": "Container cgroup memory (v1)"
                });
            }
        }
    }
    json!({
        "available": false,
        "source": "unavailable",
        "note": "Cgroup memory stats not found — falling back to host /proc/meminfo when present"
    })
}

fn host_meminfo_block() -> Value {
    let meminfo = match read_to_string("/proc/meminfo") {
        Some(s) => s,
        None => {
            return json!({
                "available": false,
                "source": "host_proc",
                "note": "Memory stats unavailable in this container"
            });
        }
    };
    let mut total_kb = 0_u64;
    let mut avail_kb = 0_u64;
    for line in meminfo.lines() {
        if let Some(v) = line.strip_prefix("MemTotal:") {
            total_kb = v.trim().trim_end_matches(" kB").parse().unwrap_or(0);
        } else if let Some(v) = line.strip_prefix("MemAvailable:") {
            avail_kb = v.trim().trim_end_matches(" kB").parse().unwrap_or(0);
        }
    }
    if total_kb == 0 {
        return json!({"available": false, "source": "host_proc", "note": "Could not parse /proc/meminfo"});
    }
    let total_bytes = total_kb * 1024;
    let available_bytes = avail_kb * 1024;
    let used_bytes = total_bytes.saturating_sub(available_bytes);
    let percent_used = (used_bytes as f64 / total_bytes as f64) * 100.0;
    json!({
        "available": true,
        "source": "host_proc",
        "total_bytes": total_bytes,
        "used_bytes": used_bytes,
        "available_bytes": available_bytes,
        "free_bytes": available_bytes,
        "percent_used": (percent_used * 10.0).round() / 10.0,
        "note": "Host node memory — may include RAM outside this container on shared Railway nodes"
    })
}

fn memory_block() -> Value {
    let cgroup = cgroup_memory_block();
    if cgroup.get("available") == Some(&json!(true)) {
        return cgroup;
    }
    host_meminfo_block()
}

fn statvfs_bytes(path: &Path) -> Option<(u64, u64, u64)> {
    use std::ffi::CString;
    let c_path = CString::new(path.to_string_lossy().as_ref()).ok()?;
    let mut stat: libc::statvfs = unsafe { std::mem::zeroed() };
    if unsafe { libc::statvfs(c_path.as_ptr(), &mut stat) } != 0 {
        return None;
    }
    let block = u64::from(stat.f_frsize);
    let total = block.saturating_mul(u64::from(stat.f_blocks));
    let avail = block.saturating_mul(u64::from(stat.f_bavail));
    let used = total.saturating_sub(avail);
    Some((total, used, avail))
}

fn disk_for_path(path: &Path) -> Value {
    if !path.exists() {
        return json!({
            "available": false,
            "label": "Workspace volume",
            "path": path.display().to_string(),
            "note": "Path not present in container"
        });
    }
    let mut used_bytes = 0_u64;
    if path.is_dir() {
        if let Ok(rd) = fs::read_dir(path) {
            for entry in rd.flatten() {
                if let Ok(meta) = entry.metadata() {
                    used_bytes = used_bytes.saturating_add(meta.len());
                }
            }
        }
    } else if let Ok(meta) = fs::metadata(path) {
        used_bytes = meta.len();
    }
    let storage_summary = data_management::storage_summary();
    let mut block = json!({
        "available": true,
        "label": "Workspace volume",
        "path": path.display().to_string(),
        "used_bytes": used_bytes,
        "percent_used": null,
        "note": "Open-FDD workspace mount",
        "breakdown": storage_summary.get("by_subdir").cloned().unwrap_or(json!({}))
    });
    if let Some((total_bytes, df_used, avail_bytes)) = statvfs_bytes(path) {
        let pct = if total_bytes > 0 {
            Some(((df_used as f64 / total_bytes as f64) * 1000.0).round() / 10.0)
        } else {
            None
        };
        block["total_bytes"] = json!(total_bytes);
        block["used_bytes"] = json!(df_used);
        block["available_bytes"] = json!(avail_bytes);
        block["percent_used"] = json!(pct);
        block["source"] = json!("statvfs");
    }
    block
}

fn uptime_seconds() -> Option<u64> {
    read_to_string("/proc/uptime").and_then(|line| {
        line.split_whitespace()
            .next()
            .and_then(|s| s.parse::<f64>().ok())
            .map(|s| s as u64)
    })
}

fn parquet_historian_summary() -> Value {
    let Ok(config) = HistorianConfig::from_env() else {
        return json!({"available": false, "note": "Historian config unavailable"});
    };
    match fdd_store::local_historian_stats_from_config(&config) {
        Ok(HistorianStats {
            parquet_files,
            total_bytes,
            small_files,
            ..
        }) => json!({
            "available": true,
            "file_count": parquet_files,
            "small_file_count": small_files,
            "estimated_bytes": total_bytes,
            "target_file_mb": config.target_file_mb,
        }),
        Err(err) => json!({
            "available": false,
            "note": err.to_string(),
        }),
    }
}

fn merged_data_management() -> Value {
    let mut dm = data_management::storage_summary();
    if let Some(obj) = dm.as_object_mut() {
        obj.insert("parquet".to_string(), parquet_historian_summary());
    }
    dm
}

pub fn stats_json() -> Value {
    let collected_at = Utc::now().to_rfc3339();
    let hostname = env::var("HOSTNAME")
        .or_else(|_| env::var("OPENFDD_HOSTNAME"))
        .unwrap_or_else(|_| "openfdd-edge".into());
    let (load_1, load_5, load_15) = load_averages();
    let cores = logical_cores();
    let usage_percent = load_1.map(|l| ((l / cores as f64) * 100.0).min(100.0));
    let workspace = crate::historian::store::workspace_dir();
    let storage = disk_for_path(&workspace);
    let dm = merged_data_management();

    json!({
        "ok": true,
        "collected_at": collected_at,
        "host": {
            "hostname": hostname,
            "platform": env::consts::OS,
            "platform_release": env::consts::ARCH,
            "machine": env::consts::ARCH,
            "python_version": "n/a (Rust edge)",
            "uptime_seconds": uptime_seconds()
        },
        "cpu": {
            "logical_cores": cores,
            "usage_percent": usage_percent,
            "load_1": load_1,
            "load_5": load_5,
            "load_15": load_15,
            "note": usage_percent.is_none().then_some("CPU percent estimated from load average when available")
        },
        "memory": memory_block(),
        "storage": storage,
        "network": {"available": false, "note": "Network counters not collected in Rust edge yet"},
        "container_revisions": {
            "image_tag": env::var("OPENFDD_IMAGE_TAG").unwrap_or_else(|_| "local".into()),
            "git_sha": env::var("OPENFDD_GIT_SHA").unwrap_or_else(|_| "unknown".into()),
            "services": [{
                "id": "openfdd-bridge",
                "label": "Rust edge bridge",
                "image": env::var("OPENFDD_IMAGE").unwrap_or_else(|_| "openfdd-edge:local".into()),
                "api_version": env!("CARGO_PKG_VERSION")
            }]
        },
        "data_management": dm
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn host_stats_shape_ok() {
        let body = stats_json();
        assert_eq!(body.get("ok"), Some(&json!(true)));
        assert!(body.get("collected_at").and_then(|v| v.as_str()).is_some());
        assert!(body.get("host").is_some());
        assert!(body.get("storage").is_some());
        let mem = body.get("memory").and_then(|v| v.as_object());
        assert!(mem.is_some());
        assert!(mem.unwrap().contains_key("source"));
    }
}
