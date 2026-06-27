//! Generic CSV import pipeline — filename-derived model, historian, FDD (no bench-specific IDs).

use open_fdd_edge_prototype::fdd::execution;
use open_fdd_edge_prototype::historian::store;
use open_fdd_edge_prototype::import;
use open_fdd_edge_prototype::model::{assignments, csv_import, query};
use open_fdd_edge_prototype::test_support::with_temp_workspace;
use serde_json::json;
use std::fs;

fn commit_csv(filename: &str, body: &str) -> serde_json::Value {
    let created = import::create_job(&json!({"source_filename": filename}));
    let job_id = created
        .get("job_id")
        .and_then(|v| v.as_str())
        .expect("job_id");
    import::upload_csv(job_id, body);
    import::commit_job(job_id)
}

#[test]
fn filename_derives_site_equip_and_source_ids() {
    let (site_id, equip_id, source_id, _) = csv_import::ids_from_filename("Plant-AHU-01.csv");
    assert_eq!(site_id, "site:plant-ahu-01");
    assert_eq!(equip_id, "equip:plant-ahu-01");
    assert_eq!(source_id, "source:csv:plant-ahu-01");
}

#[test]
fn synthetic_csv_builds_model_from_headers_only() {
    let csv = "\
Date,Outdoor Air Temp,Supply Air Temp,Supply Air Temp Setpoint,Fan Status
8/28/2007 0:00,72.0,55.0,55.0,1
8/28/2007 0:05,73.0,56.0,55.0,1
";
    with_temp_workspace(|_| {
        let out = commit_csv("synthetic-ahu.csv", csv);
        assert_eq!(out.get("ok").and_then(|v| v.as_bool()), Some(true));

        let site_id = "site:synthetic-ahu";
        let points = query::list_points(Some(site_id));
        let count = points
            .get("points")
            .and_then(|v| v.as_array())
            .map(|a| a.len())
            .unwrap_or(0);
        assert!(count >= 3, "expected header-derived points, got {count}");

        let assign = assignments::load_assignments_value();
        let bound = assign
            .get("points")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        assert!(!bound.is_empty());
        assert!(
            bound
                .iter()
                .all(|p| p.get("equip_ref").and_then(|v| v.as_str()) == Some("equip:synthetic-ahu")),
            "assignments must reference equipment from filename slug"
        );

        assert!(store::row_count() >= 2);

        let sql = "SELECT timestamp, equipment_id, oa_t, CASE WHEN oa_t > 70.0 THEN true ELSE false END AS raw_fault FROM telemetry_pivot WHERE oa_t IS NOT NULL";
        let eval = execution::run_rule_sql_from_historian(sql, 0, &json!({}));
        assert_eq!(eval.get("ok").and_then(|v| v.as_bool()), Some(true));
    });
}

#[test]
fn optional_large_csv_via_env() {
    let path = std::env::var("OPENFDD_LARGE_CSV")
        .ok()
        .map(std::path::PathBuf::from)
        .or_else(|| {
            std::env::var("OPENFDD_MZVAV_CSV")
                .ok()
                .map(std::path::PathBuf::from)
        });
    let Some(path) = path.filter(|p| p.exists()) else {
        return;
    };
    let filename = path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("import.csv");
    let content = fs::read_to_string(&path).expect("read large csv");
    with_temp_workspace(|_| {
        let out = commit_csv(filename, &content);
        assert_eq!(out.get("ok").and_then(|v| v.as_bool()), Some(true));
        let rows = out
            .get("rows_committed")
            .and_then(|v| v.as_u64())
            .unwrap_or(0);
        assert!(rows > 100);
        assert!(store::row_count() > 0);
    });
}
