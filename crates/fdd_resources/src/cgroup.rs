//! Linux cgroup / CPU discovery with fixture-friendly roots.

use std::fs;
use std::path::{Path, PathBuf};

use serde::Serialize;

/// Memory capacity discovery result. Never prefers host RAM over a tighter
/// container ceiling when the hierarchy is visible.
/// Linux cgroup v1 PAGE_COUNTER_MAX × PAGE_SIZE sentinel on 64-bit 4 KiB pages.
/// Slightly below `u64::MAX/2`; treating only `>= u64::MAX/2` as unlimited misses it (M70-09).
pub const CGROUP_V1_UNLIMITED_SENTINEL: u64 = 9_223_372_036_854_771_712;

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct MemoryDiscovery {
    pub available: bool,
    pub hard_limit_bytes: Option<u64>,
    pub current_bytes: Option<u64>,
    /// Throttle threshold (`memory.high`) — not a measured peak.
    pub high_bytes: Option<u64>,
    /// Historical peak from `memory.peak` when available; never substituted from high/current.
    pub peak_bytes: Option<u64>,
    pub source: String,
    pub hierarchy_complete: bool,
    pub notes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct CpuDiscovery {
    pub logical_cores: u64,
    pub cpuset_cores: Option<u64>,
    pub quota_cores: Option<f64>,
    pub effective_cores: u64,
    pub source: String,
    pub notes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct CapacityDiscovery {
    pub memory: MemoryDiscovery,
    pub cpu: CpuDiscovery,
}

/// Discover capacity from live `/proc` + cgroup roots, or from an override root
/// (tests / `OPENFDD_CGROUP_DIR`).
pub fn discover_capacity() -> CapacityDiscovery {
    let override_root = std::env::var("OPENFDD_CGROUP_DIR")
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .map(PathBuf::from);
    discover_capacity_at(override_root.as_deref(), Path::new("/proc"))
}

pub fn discover_capacity_at(cgroup_override: Option<&Path>, proc_root: &Path) -> CapacityDiscovery {
    let memory = discover_memory(cgroup_override, proc_root);
    let cpu = discover_cpu(cgroup_override, proc_root);
    CapacityDiscovery { memory, cpu }
}

fn discover_memory(cgroup_override: Option<&Path>, proc_root: &Path) -> MemoryDiscovery {
    let mut notes = Vec::new();
    if let Some(root) = cgroup_override {
        if let Some(m) = read_cgroup_v2_memory(root, proc_root, &mut notes) {
            return m;
        }
        if let Some(m) = read_cgroup_v1_memory(root, proc_root, &mut notes) {
            return m;
        }
        notes.push(format!(
            "OPENFDD_CGROUP_DIR={} had no readable memory controller",
            root.display()
        ));
    }

    // Prefer process membership when /proc is available.
    if let Some(path) = resolve_self_cgroup_v2(proc_root) {
        if let Some(m) = read_cgroup_v2_memory(&path, proc_root, &mut notes) {
            return m;
        }
    }
    if let Some(path) = resolve_self_cgroup_v1_memory(proc_root) {
        if let Some(m) = read_cgroup_v1_memory(&path, proc_root, &mut notes) {
            return m;
        }
    }

    // Fixed roots as last resort (containers often mount cgroup at /sys/fs/cgroup).
    for root in [Path::new("/sys/fs/cgroup")] {
        if cgroup_override.is_some() {
            break;
        }
        if let Some(m) = read_cgroup_v2_memory(root, proc_root, &mut notes) {
            return m;
        }
        if let Some(m) = read_cgroup_v1_memory(root, proc_root, &mut notes) {
            return m;
        }
    }

    let host = host_meminfo(proc_root);
    MemoryDiscovery {
        available: host.is_some(),
        hard_limit_bytes: host,
        current_bytes: None,
        high_bytes: None,
        peak_bytes: None,
        source: if host.is_some() {
            "host_meminfo".into()
        } else {
            "unavailable".into()
        },
        hierarchy_complete: false,
        notes: {
            notes.push(
                "No enforceable cgroup memory limit visible — host MemTotal is fallback only"
                    .into(),
            );
            notes
        },
    }
}

fn read_cgroup_v2_memory(
    root: &Path,
    proc_root: &Path,
    notes: &mut Vec<String>,
) -> Option<MemoryDiscovery> {
    let current_path = root.join("memory.current");
    if !current_path.is_file() {
        return None;
    }
    let current = read_u64_file(&current_path);
    let max_raw = fs::read_to_string(root.join("memory.max")).ok();
    let high_raw = fs::read_to_string(root.join("memory.high")).ok();
    let peak = read_u64_file(&root.join("memory.peak"));
    let leaf_hard = max_raw.as_deref().and_then(parse_cgroup_limit);
    let high = high_raw.as_deref().and_then(parse_cgroup_limit);
    // Effective hard limit is the tightest finite memory.max on the visible
    // ancestor chain (M70-09). Sibling headroom is still incomplete without
    // ancestor usage; mark hierarchy_complete only when a finite limit exists.
    let (hard, ancestor_note) = effective_v2_hard_limit(root, leaf_hard);
    if let Some(note) = ancestor_note {
        notes.push(note);
    }
    if peak.is_none() {
        notes.push("memory.peak unavailable — peak_bytes left unset (not high/current)".into());
    }
    if hard.is_none() {
        notes.push("cgroup v2 memory.max is max/unlimited or unreadable".into());
        if let Some(host) = host_meminfo(proc_root) {
            notes.push(format!(
                "using host MemTotal {host} bytes as portable hard limit (edge shed/abort)"
            ));
            return Some(MemoryDiscovery {
                available: true,
                hard_limit_bytes: Some(host),
                current_bytes: current,
                high_bytes: high,
                peak_bytes: peak,
                source: "host_meminfo".into(),
                // Unlimited leaf under host fallback is not a complete hierarchy proof.
                hierarchy_complete: false,
                notes: notes.clone(),
            });
        }
    }
    Some(MemoryDiscovery {
        available: true,
        hard_limit_bytes: hard,
        current_bytes: current,
        high_bytes: high,
        peak_bytes: peak,
        source: format!("cgroup_v2:{}", root.display()),
        hierarchy_complete: hard.is_some(),
        notes: notes.clone(),
    })
}

/// Walk parents for the smallest finite `memory.max` (hierarchical constraint).
fn effective_v2_hard_limit(leaf: &Path, leaf_hard: Option<u64>) -> (Option<u64>, Option<String>) {
    let mut best = leaf_hard;
    let mut walked = 0u32;
    let mut cur = leaf.to_path_buf();
    for _ in 0..32 {
        let Some(parent) = cur.parent().map(Path::to_path_buf) else {
            break;
        };
        if parent == cur {
            break;
        }
        let parent_max = fs::read_to_string(parent.join("memory.max"))
            .ok()
            .as_deref()
            .and_then(parse_cgroup_limit);
        if let Some(p) = parent_max {
            walked += 1;
            best = Some(best.map(|b| b.min(p)).unwrap_or(p));
        }
        // Stop at filesystem root or when memory.current disappears (left controller tree).
        if !parent.join("memory.current").is_file() && !parent.join("memory.max").is_file() {
            break;
        }
        cur = parent;
    }
    let note = if walked > 0 {
        Some(format!(
            "effective hard limit uses min(leaf, {walked} ancestor memory.max values)"
        ))
    } else {
        None
    };
    (best, note)
}

fn read_cgroup_v1_memory(
    root: &Path,
    proc_root: &Path,
    notes: &mut Vec<String>,
) -> Option<MemoryDiscovery> {
    let usage = root.join("memory.usage_in_bytes");
    let limit = root.join("memory.limit_in_bytes");
    // Also accept memory/ subdirectory layout.
    let (usage, limit) = if usage.is_file() {
        (usage, limit)
    } else {
        let nested_usage = root.join("memory/memory.usage_in_bytes");
        let nested_limit = root.join("memory/memory.limit_in_bytes");
        if nested_usage.is_file() {
            (nested_usage, nested_limit)
        } else {
            return None;
        }
    };
    let current = read_u64_file(&usage);
    let hard = read_u64_file(&limit).and_then(|n| {
        // Real kernel sentinel is PAGE_COUNTER_MAX*PAGE_SIZE; also treat >= MAX/2.
        if n >= CGROUP_V1_UNLIMITED_SENTINEL || n >= u64::MAX / 2 {
            notes.push(format!(
                "cgroup v1 memory.limit_in_bytes is unlimited sentinel ({n})"
            ));
            None
        } else {
            Some(n)
        }
    });
    let peak = read_u64_file(&root.join("memory.max_usage_in_bytes"))
        .or_else(|| read_u64_file(&root.join("memory/memory.max_usage_in_bytes")));
    if hard.is_none() {
        if let Some(host) = host_meminfo(proc_root) {
            notes.push(format!(
                "using host MemTotal {host} bytes as portable hard limit (edge shed/abort)"
            ));
            return Some(MemoryDiscovery {
                available: true,
                hard_limit_bytes: Some(host),
                current_bytes: current,
                high_bytes: None,
                peak_bytes: peak,
                source: "host_meminfo".into(),
                hierarchy_complete: false,
                notes: notes.clone(),
            });
        }
    }
    Some(MemoryDiscovery {
        available: true,
        hard_limit_bytes: hard,
        current_bytes: current,
        high_bytes: None,
        peak_bytes: peak,
        source: format!("cgroup_v1:{}", root.display()),
        hierarchy_complete: hard.is_some(),
        notes: notes.clone(),
    })
}

fn resolve_self_cgroup_v2(proc_root: &Path) -> Option<PathBuf> {
    let cgroup = fs::read_to_string(proc_root.join("self/cgroup")).ok()?;
    // v2 unified: "0::/path"
    for line in cgroup.lines() {
        if let Some(rel) = line.strip_prefix("0::") {
            let rel = rel.trim().trim_start_matches('/');
            let mount = find_cgroup2_mount(proc_root)?;
            let path = if rel.is_empty() {
                mount
            } else {
                mount.join(rel)
            };
            if path.join("memory.current").is_file() {
                return Some(path);
            }
        }
    }
    None
}

fn resolve_self_cgroup_v1_memory(proc_root: &Path) -> Option<PathBuf> {
    let cgroup = fs::read_to_string(proc_root.join("self/cgroup")).ok()?;
    for line in cgroup.lines() {
        // e.g. "4:memory:/docker/abc"
        let mut parts = line.splitn(3, ':');
        let _id = parts.next()?;
        let controllers = parts.next()?;
        let rel = parts.next()?;
        if !controllers.split(',').any(|c| c == "memory") {
            continue;
        }
        let rel = rel.trim().trim_start_matches('/');
        let base = PathBuf::from("/sys/fs/cgroup/memory");
        let path = if rel.is_empty() { base } else { base.join(rel) };
        if path.join("memory.usage_in_bytes").is_file() {
            return Some(path);
        }
    }
    None
}

fn find_cgroup2_mount(proc_root: &Path) -> Option<PathBuf> {
    let mountinfo = fs::read_to_string(proc_root.join("self/mountinfo")).ok()?;
    for line in mountinfo.lines() {
        // ... - cgroup2 <options>
        if line.contains(" - cgroup2 ") {
            let mut parts = line.split_whitespace();
            let _id = parts.next()?;
            let _parent = parts.next()?;
            let _major_minor = parts.next()?;
            let _root = parts.next()?;
            let mount_point = parts.next()?;
            return Some(PathBuf::from(mount_point));
        }
    }
    // Common default when mountinfo is stubbed in fixtures.
    let fallback = PathBuf::from("/sys/fs/cgroup");
    if fallback.join("memory.current").is_file() || fallback.is_dir() {
        return Some(fallback);
    }
    None
}

fn discover_cpu(cgroup_override: Option<&Path>, proc_root: &Path) -> CpuDiscovery {
    let mut notes = Vec::new();
    let logical = logical_cores(proc_root);
    let mut cpuset_cores = None;
    let mut quota_cores = None;
    let mut source = "host_proc".to_string();

    let roots: Vec<PathBuf> = match cgroup_override {
        Some(r) => vec![r.to_path_buf()],
        None => vec![PathBuf::from("/sys/fs/cgroup")],
    };
    for root in roots {
        if let Some(n) = parse_cpuset_cores(&root.join("cpuset.cpus.effective"))
            .or_else(|| parse_cpuset_cores(&root.join("cpuset.cpus")))
        {
            cpuset_cores = Some(n);
            source = format!("cgroup_cpuset:{}", root.display());
        }
        if let Some(q) = parse_cpu_quota(&root.join("cpu.max")) {
            quota_cores = Some(q);
            source = format!("cgroup_cpu_max:{}", root.display());
        }
        // v1
        if quota_cores.is_none() {
            if let Some(q) = parse_cpu_quota_v1(&root) {
                quota_cores = Some(q);
                source = format!("cgroup_v1_cpu:{}", root.display());
            }
        }
    }

    let mut effective = logical.max(1);
    if let Some(n) = cpuset_cores {
        effective = effective.min(n.max(1));
    }
    if let Some(q) = quota_cores {
        let q_floor = q.floor().max(1.0) as u64;
        effective = effective.min(q_floor);
        if q < 1.0 {
            notes.push(format!(
                "cpu quota {q} cores < 1; clamping effective_cores to 1"
            ));
        }
    }

    CpuDiscovery {
        logical_cores: logical,
        cpuset_cores,
        quota_cores,
        effective_cores: effective.max(1),
        source,
        notes,
    }
}

fn logical_cores(proc_root: &Path) -> u64 {
    fs::read_to_string(proc_root.join("cpuinfo"))
        .ok()
        .map(|s| s.lines().filter(|l| l.starts_with("processor")).count() as u64)
        .filter(|n| *n > 0)
        .unwrap_or(1)
}

fn parse_cpuset_cores(path: &Path) -> Option<u64> {
    let raw = fs::read_to_string(path).ok()?;
    let raw = raw.trim();
    if raw.is_empty() {
        return None;
    }
    let mut count = 0u64;
    for part in raw.split(',') {
        let part = part.trim();
        if part.is_empty() {
            continue;
        }
        if let Some((a, b)) = part.split_once('-') {
            let start: u64 = a.parse().ok()?;
            let end: u64 = b.parse().ok()?;
            if end >= start {
                count = count.saturating_add(end - start + 1);
            }
        } else {
            let _: u64 = part.parse().ok()?;
            count = count.saturating_add(1);
        }
    }
    (count > 0).then_some(count)
}

fn parse_cpu_quota(path: &Path) -> Option<f64> {
    let raw = fs::read_to_string(path).ok()?;
    let mut parts = raw.split_whitespace();
    let quota = parts.next()?;
    let period = parts.next()?;
    if quota.eq_ignore_ascii_case("max") {
        return None;
    }
    let quota: f64 = quota.parse().ok()?;
    let period: f64 = period.parse().ok()?;
    if period <= 0.0 || quota < 0.0 {
        return None;
    }
    Some(quota / period)
}

fn parse_cpu_quota_v1(root: &Path) -> Option<f64> {
    let quota_path = if root.join("cpu.cfs_quota_us").is_file() {
        root.join("cpu.cfs_quota_us")
    } else {
        root.join("cpu/cpu.cfs_quota_us")
    };
    let period_path = if root.join("cpu.cfs_period_us").is_file() {
        root.join("cpu.cfs_period_us")
    } else {
        root.join("cpu/cpu.cfs_period_us")
    };
    let quota: i64 = fs::read_to_string(quota_path).ok()?.trim().parse().ok()?;
    let period: f64 = fs::read_to_string(period_path).ok()?.trim().parse().ok()?;
    if quota < 0 || period <= 0.0 {
        return None;
    }
    Some(quota as f64 / period)
}

fn host_meminfo(proc_root: &Path) -> Option<u64> {
    let meminfo = fs::read_to_string(proc_root.join("meminfo")).ok()?;
    for line in meminfo.lines() {
        if let Some(v) = line.strip_prefix("MemTotal:") {
            let kb: u64 = v.trim().trim_end_matches(" kB").trim().parse().ok()?;
            return Some(kb.saturating_mul(1024));
        }
    }
    None
}

fn read_u64_file(path: &Path) -> Option<u64> {
    let raw = fs::read_to_string(path).ok()?;
    parse_cgroup_limit(&raw)
}

fn parse_cgroup_limit(raw: &str) -> Option<u64> {
    let trimmed = raw.trim();
    if trimmed.is_empty() || trimmed.eq_ignore_ascii_case("max") {
        return None;
    }
    trimmed.parse().ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::TempDir;

    fn write(path: &Path, body: &str) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        let mut f = fs::File::create(path).unwrap();
        f.write_all(body.as_bytes()).unwrap();
    }

    #[test]
    fn nested_v2_prefers_cgroup_limit_over_host() {
        let tmp = TempDir::new().unwrap();
        let cg = tmp.path().join("cg");
        write(&cg.join("memory.current"), "1000\n");
        write(&cg.join("memory.max"), "24000000000\n");
        write(&cg.join("memory.high"), "max\n");
        let proc = tmp.path().join("proc");
        write(&proc.join("meminfo"), "MemTotal:       338368128 kB\n");
        write(&proc.join("cpuinfo"), "processor\t: 0\nprocessor\t: 1\n");
        write(&cg.join("cpu.max"), "200000 100000\n");
        write(&cg.join("cpuset.cpus.effective"), "0-3\n");

        let cap = discover_capacity_at(Some(&cg), &proc);
        assert_eq!(cap.memory.hard_limit_bytes, Some(24_000_000_000));
        assert_ne!(cap.memory.source, "host_proc_fallback");
        assert_eq!(cap.cpu.effective_cores, 2); // quota 2.0 beats cpuset 4 / logical 2 → min=2
        assert!(cap.memory.hierarchy_complete);
    }

    #[test]
    fn unlimited_v2_falls_back_without_claiming_hard_limit() {
        let tmp = TempDir::new().unwrap();
        let cg = tmp.path().join("cg");
        write(&cg.join("memory.current"), "500\n");
        write(&cg.join("memory.max"), "max\n");
        let proc = tmp.path().join("proc");
        write(&proc.join("meminfo"), "MemTotal:        16384000 kB\n");
        write(&proc.join("cpuinfo"), "processor\t: 0\n");

        let cap = discover_capacity_at(Some(&cg), &proc);
        assert!(cap.memory.available);
        assert_eq!(cap.memory.hard_limit_bytes, Some(16_384_000 * 1024));
        assert_eq!(cap.memory.source, "host_meminfo");
        // Host fallback is not a complete cgroup hierarchy proof (M70-09).
        assert!(!cap.memory.hierarchy_complete);
    }

    #[test]
    fn v1_unlimited_sentinel_ignored() {
        let tmp = TempDir::new().unwrap();
        let cg = tmp.path().join("cg");
        write(&cg.join("memory/memory.usage_in_bytes"), "1234\n");
        write(
            &cg.join("memory/memory.limit_in_bytes"),
            &format!("{}\n", u64::MAX),
        );
        let proc = tmp.path().join("proc");
        write(&proc.join("meminfo"), "MemTotal:         8192000 kB\n");
        write(&proc.join("cpuinfo"), "processor\t: 0\n");

        let cap = discover_capacity_at(Some(&cg), &proc);
        assert_eq!(cap.memory.hard_limit_bytes, Some(8_192_000 * 1024));
        assert_eq!(cap.memory.source, "host_meminfo");
    }

    #[test]
    fn v1_page_counter_max_sentinel_ignored() {
        let tmp = TempDir::new().unwrap();
        let cg = tmp.path().join("cg");
        write(&cg.join("memory/memory.usage_in_bytes"), "1234\n");
        write(
            &cg.join("memory/memory.limit_in_bytes"),
            &format!("{CGROUP_V1_UNLIMITED_SENTINEL}\n"),
        );
        let proc = tmp.path().join("proc");
        write(&proc.join("meminfo"), "MemTotal:         8192000 kB\n");
        write(&proc.join("cpuinfo"), "processor\t: 0\n");

        let cap = discover_capacity_at(Some(&cg), &proc);
        assert_eq!(cap.memory.hard_limit_bytes, Some(8_192_000 * 1024));
        assert_eq!(cap.memory.source, "host_meminfo");
        assert!(!cap.memory.hierarchy_complete);
    }

    #[test]
    fn v2_reads_peak_separate_from_high() {
        let tmp = TempDir::new().unwrap();
        let cg = tmp.path().join("cg");
        write(&cg.join("memory.current"), "500\n");
        write(&cg.join("memory.max"), "10000\n");
        write(&cg.join("memory.high"), "700\n");
        write(&cg.join("memory.peak"), "900\n");
        let proc = tmp.path().join("proc");
        write(&proc.join("meminfo"), "MemTotal:       999999999 kB\n");
        write(&proc.join("cpuinfo"), "processor\t: 0\n");

        let cap = discover_capacity_at(Some(&cg), &proc);
        assert_eq!(cap.memory.current_bytes, Some(500));
        assert_eq!(cap.memory.high_bytes, Some(700));
        assert_eq!(cap.memory.peak_bytes, Some(900));
        assert_eq!(cap.memory.hard_limit_bytes, Some(10000));
    }

    #[test]
    fn v2_ancestor_tighter_max_wins() {
        let tmp = TempDir::new().unwrap();
        let parent = tmp.path().join("parent");
        let leaf = parent.join("leaf");
        write(&parent.join("memory.current"), "100\n");
        write(&parent.join("memory.max"), "5000\n");
        write(&leaf.join("memory.current"), "100\n");
        write(&leaf.join("memory.max"), "10000\n");
        write(&leaf.join("memory.peak"), "200\n");
        let proc = tmp.path().join("proc");
        write(&proc.join("meminfo"), "MemTotal:       999999999 kB\n");
        write(&proc.join("cpuinfo"), "processor\t: 0\n");

        let cap = discover_capacity_at(Some(&leaf), &proc);
        assert_eq!(cap.memory.hard_limit_bytes, Some(5000));
        assert_eq!(cap.memory.peak_bytes, Some(200));
    }

    #[test]
    fn v1_finite_limit() {
        let tmp = TempDir::new().unwrap();
        let cg = tmp.path().join("cg");
        write(&cg.join("memory/memory.usage_in_bytes"), "100\n");
        write(&cg.join("memory/memory.limit_in_bytes"), "104857600\n");
        let proc = tmp.path().join("proc");
        write(&proc.join("meminfo"), "MemTotal:       999999999 kB\n");
        write(&proc.join("cpuinfo"), "processor\t: 0\n");

        let cap = discover_capacity_at(Some(&cg), &proc);
        assert_eq!(cap.memory.hard_limit_bytes, Some(104_857_600));
    }
}
