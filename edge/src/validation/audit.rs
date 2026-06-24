//! Production hardcoding audit — forbidden bench-specific terms outside dev paths.

use std::path::{Path, PathBuf};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AuditViolation {
    pub path: PathBuf,
    pub line: usize,
    pub pattern: String,
    pub snippet: String,
}

const FORBIDDEN: &[&str] = &[
    "bench_5007",
    "bench-5007",
    "BENCH_5007",
    "Bench 5007",
    "bench 5007",
    "/bench-5007",
    "/api/bench/5007",
];

const ALLOWED_PREFIXES: &[&str] = &[
    "scripts/",
    "scripts\\",
    "docs/testing/",
    "docs\\testing\\",
    "docs/verification/",
    "docs\\verification\\",
    "workspace/smoke-profiles/",
    "workspace\\smoke-profiles\\",
    ".github/workflows/",
];

const ALLOWED_FILES: &[&str] = &[
    "scripts/bench_5007_long_smoke.sh",
    "docs/verification/bench-5007-long-smoke.md",
    "edge/src/validation/audit.rs",
    "edge/src/main.rs",
];

pub fn path_allowed(rel: &str) -> bool {
    if ALLOWED_FILES.iter().any(|f| rel.ends_with(f) || rel == *f) {
        return true;
    }
    ALLOWED_PREFIXES
        .iter()
        .any(|p| rel.starts_with(p) || rel.contains(p))
}

pub fn scan_line_for_violations(rel: &str, line_no: usize, line: &str) -> Vec<AuditViolation> {
    if path_allowed(rel) {
        return Vec::new();
    }
    if rel.contains("/tests/") || rel.contains("\\tests\\") || rel.ends_with("_test.rs") {
        return Vec::new();
    }
    if rel.contains("/fixtures/") || rel.contains("\\fixtures\\") {
        return Vec::new();
    }
    let mut out = Vec::new();
    for pat in FORBIDDEN {
        if line.contains(pat) {
            out.push(AuditViolation {
                path: PathBuf::from(rel),
                line: line_no,
                pattern: (*pat).to_string(),
                snippet: line.trim().chars().take(120).collect(),
            });
        }
    }
    if line.contains("5007") && !rel.contains("docker-compose.bacnet-live.yml") {
        let lower = line.to_ascii_lowercase();
        if lower.contains("5007")
            && (lower.contains("bench")
                || lower.contains("/api/bench")
                || lower.contains("device 5007"))
        {
            out.push(AuditViolation {
                path: PathBuf::from(rel),
                line: line_no,
                pattern: "5007+bench".into(),
                snippet: line.trim().chars().take(120).collect(),
            });
        }
    }
    out
}

pub fn audit_text_file(rel: &str, text: &str) -> Vec<AuditViolation> {
    text.lines()
        .enumerate()
        .flat_map(|(i, line)| scan_line_for_violations(rel, i + 1, line))
        .collect()
}

pub fn expected_phase_fault_state(phase: &str) -> (&'static str, bool) {
    match phase {
        "fault" | "fault_high" | "fault_low" => ("raw_fault", true),
        "clear" | "normal" | "" => ("no_fault", false),
        _ => ("unknown", false),
    }
}

pub fn confirmation_met(minutes_in_fault: f64, required_minutes: i64) -> bool {
    minutes_in_fault >= required_minutes as f64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allows_dev_script_paths() {
        assert!(path_allowed("scripts/bench_5007_long_smoke.sh"));
        assert!(path_allowed("docs/testing/live-fdd-validation.md"));
    }

    #[test]
    fn flags_production_ui_label() {
        let hits = scan_line_for_violations(
            "workspace/dashboard/src/pages/SmokePage.tsx",
            1,
            r#"<PageHeader title="Bench 5007 — FDD wiresheet" />"#,
        );
        assert!(!hits.is_empty());
    }

    #[test]
    fn phase_expectations() {
        assert_eq!(expected_phase_fault_state("fault"), ("raw_fault", true));
        assert_eq!(expected_phase_fault_state("normal"), ("no_fault", false));
    }

    #[test]
    fn confirmation_delay() {
        assert!(!confirmation_met(4.0, 5));
        assert!(confirmation_met(5.0, 5));
    }

    #[test]
    fn summary_schema_required_fields() {
        let required = [
            "timestamp_utc",
            "sample_index",
            "api_health_ok",
            "stack_health_ok",
            "docker_ok",
            "smoke_device_instance",
            "fdd_sql_ok",
            "expected_phase",
            "modbus_ok",
            "json_api_ok",
        ];
        let sample = serde_json::json!({
            "timestamp_utc": "2026-06-23T00:00:00Z",
            "sample_index": 1,
            "api_health_ok": true,
            "stack_health_ok": true,
            "docker_ok": true,
            "docker_error_count": 0,
            "source_id": "source:validation",
            "smoke_device_instance": 0,
            "bacnet_device_seen": true,
            "bacnet_poll_ok": true,
            "historian_rows_written": 1,
            "fdd_sql_ok": true,
            "raw_fault_count": 0,
            "confirmed_fault_count": 0,
            "minutes_in_fault": 0,
            "confirmation_required_minutes": 5,
            "expected_phase": "live",
            "expected_fault_state": "no_fault",
            "actual_fault_state": "no_fault",
            "modbus_ok": true,
            "modbus_registers_read": 0,
            "json_api_ok": true,
            "json_api_points_read": 1,
            "override_scan_ok": false,
            "error": ""
        });
        for key in required {
            assert!(sample.get(key).is_some(), "missing {key}");
        }
    }

    #[test]
    fn modbus_offline_is_degraded_not_fatal_by_default() {
        assert!(!crate::validation::profile::require_modbus());
    }
}
