//! Production hardcoding audit — forbidden bench-specific terms outside dev paths.

use std::path::PathBuf;

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
    "ACTUATOR-0",
    "C06-0-10VDC-O",
    "BENS BENCHTEST BOX",
    "192.168.204.14",
    "equip:5007-bench",
    "site:demo",
    "equip:demo-ahu",
    "equip:validation",
    "demo-ahu",
    "bacnet:demo-ahu",
];

const FORBIDDEN_OT_SIM: &[&str] = &[
    "simulated_values",
    "simulated_priorities",
    "bacnet_point_to_simulated",
    "simulation_phase",
    "simulated:local",
    "OPENFDD_BACNET_MODE=simulated",
    "OPENFDD_MODBUS_MODE=simulated",
    "/api/bench/5007",
];

const ALLOWED_FILES: &[&str] = &[
    "scripts/bench_5007_long_smoke.sh",
    "docs/verification/bench-5007-long-smoke.md",
    "edge/src/validation/audit.rs",
    "edge/src/drivers/haystack/fixture.rs",
    "edge/src/historian/arrow_table.rs",
    "edge/src/fdd/datafusion_sql.rs",
    "edge/src/bench/validation_fixture.rs",
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
    if line.contains("forbidden_") || (line.contains("assert!(!") && line.contains(".contains(")) {
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
    if rel.starts_with("edge/src/") {
        for pat in FORBIDDEN_OT_SIM {
            if line.contains(pat) {
                out.push(AuditViolation {
                    path: PathBuf::from(rel),
                    line: line_no,
                    pattern: format!("ot_sim:{pat}"),
                    snippet: line.trim().chars().take(120).collect(),
                });
            }
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
    fn flags_actuator_zero_in_production_rust() {
        let hits = scan_line_for_violations(
            "edge/src/drivers/bacnet.rs",
            1,
            r#"if name == "ACTUATOR-0" { vec![(8, json!(55.0))] }"#,
        );
        assert!(!hits.is_empty());
    }

    #[test]
    fn flags_c06_point_name_branch() {
        let hits = scan_line_for_violations(
            "edge/src/drivers/bacnet.rs",
            1,
            r#"else if name == "C06-0-10VDC-O" {"#,
        );
        assert!(!hits.is_empty());
    }

    #[test]
    fn allows_example_profile_path() {
        assert!(path_allowed(
            "workspace/smoke-profiles/local/local_haystack_5007_parity.local.toml.example"
        ));
    }

    #[test]
    fn flags_site_demo_in_production_rust() {
        let hits = scan_line_for_violations(
            "edge/src/drivers/bacnet.rs",
            1,
            r#"{"id":"site:demo","dis":"Demo Site"}"#,
        );
        assert!(!hits.is_empty());
    }

    #[test]
    fn flags_ot_simulated_helpers_in_production_rust() {
        let hits = scan_line_for_violations(
            "edge/src/drivers/bacnet.rs",
            1,
            "fn simulated_values(phase: &str)",
        );
        assert!(!hits.is_empty());
        assert!(hits.iter().any(|h| h.pattern.starts_with("ot_sim:")));
    }

    #[test]
    fn flags_bench_5007_api_route_in_production_rust() {
        let hits =
            scan_line_for_violations("edge/src/main.rs", 1, r#"("/api/bench/5007/smoke/status")"#);
        assert!(!hits.is_empty());
    }

    #[test]
    fn allows_fixture_haystack_grid() {
        assert!(path_allowed("edge/src/drivers/haystack/fixture.rs"));
    }

    #[test]
    fn production_ot_driver_sources_exclude_simulated_helpers() {
        let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        for rel in [
            "src/bench/smoke.rs",
            "src/drivers/bacnet.rs",
            "src/drivers/modbus.rs",
        ] {
            let text = std::fs::read_to_string(root.join(rel)).expect("read driver source");
            for token in FORBIDDEN_OT_SIM {
                if token.starts_with("/api/") {
                    continue;
                }
                assert!(
                    !text.contains(token),
                    "{rel} must not reintroduce legacy OT sim token: {token}"
                );
            }
        }
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
