//! Host resource stats for the Host / Data Management UI.

use crate::data_management;
use chrono::Utc;
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::path::Path;

fn read_to_string(path: &str) -> Option<String> {
    fs::read_to_string(path).ok()
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

fn memory_block() -> Value {
    let meminfo = match read_to_string("/proc/meminfo") {
        Some(s) => s,
        None => {
            return json!({
                "available": false,
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
        return json!({"available": false, "note": "Could not parse /proc/meminfo"});
    }
    let total_bytes = total_kb * 1024;
    let available_bytes = avail_kb * 1024;
    let used_bytes = total_bytes.saturating_sub(available_bytes);
    let percent_used = (used_bytes as f64 / total_bytes as f64) * 100.0;
    json!({
        "available": true,
        "total_bytes": total_bytes,
        "used_bytes": used_bytes,
        "available_bytes": available_bytes,
        "free_bytes": available_bytes,
        "percent_used": (percent_used * 10.0).round() / 10.0
    })
}

fn disk_for_path(path: &Path) -> Value {
    if !path.exists() {
        return json!({
            "available": false,
            "label": "Data directory",
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
    let feather_bytes = storage_summary
        .get("estimated_bytes")
        .and_then(|v| v.as_u64())
        .unwrap_or(used_bytes);
    json!({
        "available": true,
        "label": "Open-FDD workspace data",
        "path": path.display().to_string(),
        "used_bytes": used_bytes,
        "feather_bytes": feather_bytes,
        "percent_used": null,
        "note": "Container filesystem — host disk totals may differ",
        "breakdown": storage_summary.get("by_subdir").cloned().unwrap_or(json!({}))
    })
}

fn uptime_seconds() -> Option<u64> {
    read_to_string("/proc/uptime").and_then(|line| {
        line.split_whitespace()
            .next()
            .and_then(|s| s.parse::<f64>().ok())
            .map(|s| s as u64)
    })
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
    let dm = data_management::storage_summary();

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
        "ollama": {
            "api_ok": false,
            "interactive_chat_enabled": false,
            "error": "Ollama not wired in Rust edge host stats"
        },
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
    }
}
