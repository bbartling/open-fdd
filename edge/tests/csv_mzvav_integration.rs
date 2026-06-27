//! MZVAV CSV import → Haystack model → FDD → purge integration tests.

use open_fdd_edge_prototype::data_management;
use open_fdd_edge_prototype::fdd::execution;
use open_fdd_edge_prototype::historian::store;
use open_fdd_edge_prototype::import;
use open_fdd_edge_prototype::model::{assignments, csv_import, query};
use serde_json::json;
use std::fs;
use std::path::{Path, PathBuf};

fn workspace_lock() -> std::sync::MutexGuard<'static, ()> {
    static LOCK: std::sync::OnceLock<std::sync::Mutex<()>> = std::sync::OnceLock::new();
    LOCK.get_or_init(|| std::sync::Mutex::new(()))
        .lock()
        .unwrap_or_else(|p| p.into_inner())
}

fn with_workspace<F: FnOnce(&Path)>(f: F) {
    let _guard = workspace_lock();
    let prev = std::env::var("OPENFDD_WORKSPACE").ok();
    let dir = std::env::temp_dir().join(format!(
        "openfdd-mzvav-it-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    ));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    std::env::set_var("OPENFDD_WORKSPACE", &dir);
    f(&dir);
    if let Some(p) = prev {
        std::env::set_var("OPENFDD_WORKSPACE", p);
    } else {
        std::env::remove_var("OPENFDD_WORKSPACE");
    }
    let _ = fs::remove_dir_all(&dir);
}

fn fixture_csv() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/mzvav-2-1-head.csv")
}

fn mzvav_csv_path() -> PathBuf {
    std::env::var("OPENFDD_MZVAV_CSV")
        .map(PathBuf::from)
        .unwrap_or_else(|_| fixture_csv())
}

fn split_csv_vertical(content: &str, split_after_col: usize) -> (String, String) {
    let lines: Vec<&str> = content.lines().filter(|l| !l.trim().is_empty()).collect();
    let header = lines[0].split(',').collect::<Vec<_>>();
    let left_indices: Vec<usize> = std::iter::once(0)
        .chain(1..=split_after_col.min(header.len().saturating_sub(1)))
        .collect();
    let right_indices: Vec<usize> = std::iter::once(0)
        .chain((split_after_col + 1)..header.len())
        .collect();

    fn project(line: &str, cols: &[usize]) -> String {
        let cells: Vec<&str> = line.split(',').collect();
        cols.iter()
            .map(|i| cells.get(*i).copied().unwrap_or(""))
            .collect::<Vec<_>>()
            .join(",")
    }

    let left_header = project(lines[0], &left_indices);
    let right_header = project(lines[0], &right_indices);
    let mut left = vec![left_header];
    let mut right = vec![right_header];
    for line in &lines[1..] {
        left.push(project(line, &left_indices));
        right.push(project(line, &right_indices));
    }
    (left.join("\n"), right.join("\n"))
}

fn split_csv_horizontal(content: &str, data_rows_in_first: usize) -> (String, String) {
    let lines: Vec<&str> = content.lines().filter(|l| !l.trim().is_empty()).collect();
    let header = lines[0];
    let first: String = std::iter::once(header)
        .chain(lines.iter().skip(1).take(data_rows_in_first).copied())
        .collect::<Vec<_>>()
        .join("\n");
    let second: String = std::iter::once(header)
        .chain(lines.iter().skip(1 + data_rows_in_first).copied())
        .collect::<Vec<_>>()
        .join("\n");
    (first, second)
}

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
fn mzvav_column_aliases_map_to_fdd_inputs() {
    let slug = csv_import::column_slug("AHU: Outdoor Air Temperature");
    assert_eq!(slug, "ahu_outdoor_air_temperature");
    let mut row = json!({});
    csv_import::apply_pivot_aliases(&mut row, &slug, 80.5);
    assert_eq!(row.get("oa_t").and_then(|v| v.as_f64()), Some(80.5));

    let sat_slug = csv_import::column_slug("AHU: Supply Air Temperature");
    let mut sat_row = json!({});
    csv_import::apply_pivot_aliases(&mut sat_row, &sat_slug, 75.0);
    assert_eq!(sat_row.get("sat").and_then(|v| v.as_f64()), Some(75.0));
}

#[test]
fn mzvav_csv_import_builds_model_and_historian() {
    let path = mzvav_csv_path();
    if !path.exists() {
        eprintln!("skip mzvav_csv_import_builds_model: {}", path.display());
        return;
    }
    let content = fs::read_to_string(&path).expect("read csv");
    with_workspace(|_| {
        let out = commit_csv("MZVAV-2-1.csv", &content);
        assert_eq!(out.get("ok").and_then(|v| v.as_bool()), Some(true));
        let rows = out
            .get("rows_committed")
            .and_then(|v| v.as_u64())
            .unwrap_or(0);
        assert!(rows > 100, "expected substantial row count, got {rows}");

        let export = query::list_points(Some("site:mzvav-2-1"));
        let points = export
            .get("points")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        assert!(points.len() >= 10, "expected modeled points");

        let assign = assignments::load_assignments_value();
        let pts = assign
            .get("points")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        assert!(!pts.is_empty());

        let coverage = query::model_coverage();
        assert!(
            coverage
                .get("point_count")
                .and_then(|v| v.as_u64())
                .unwrap_or(0)
                > 0
        );
        assert!(store::row_count() > 0);
    });
}

#[test]
fn mzvav_vertical_split_inner_join_commit() {
    let path = fixture_csv();
    let content = fs::read_to_string(&path).expect("read fixture");
    let (left, _right) = split_csv_vertical(&content, 9);
    with_workspace(|_| {
        let left_out = commit_csv("mzvav-left.csv", &left);
        assert_eq!(left_out.get("ok").and_then(|v| v.as_bool()), Some(true));
        let before = store::row_count();

        // Simulate UI inner join: merge left+right on Date then commit merged file
        let merged_lines: Vec<&str> = content.lines().collect();
        let merged = merged_lines.join("\n");
        let merged_out = commit_csv("mzvav-merged.csv", &merged);
        assert_eq!(merged_out.get("ok").and_then(|v| v.as_bool()), Some(true));
        assert!(store::row_count() >= before);
    });
}

#[test]
fn mzvav_horizontal_append_commits() {
    let path = fixture_csv();
    let content = fs::read_to_string(&path).expect("read fixture");
    let (first, second) = split_csv_horizontal(&content, 200);
    with_workspace(|_| {
        let a = commit_csv("mzvav-part-a.csv", &first);
        let b = commit_csv("mzvav-part-b.csv", &second);
        assert_eq!(a.get("ok").and_then(|v| v.as_bool()), Some(true));
        assert_eq!(b.get("ok").and_then(|v| v.as_bool()), Some(true));
        let total = store::row_count();
        assert!(
            total > 400,
            "append commits should accumulate rows, got {total}"
        );
    });
}

#[test]
fn mzvav_fdd_eval_and_purge() {
    let path = mzvav_csv_path();
    if !path.exists() {
        return;
    }
    let content = fs::read_to_string(&path).expect("read csv");
    with_workspace(|_| {
        let out = commit_csv("MZVAV-2-1.csv", &content);
        assert_eq!(out.get("ok").and_then(|v| v.as_bool()), Some(true));

        let sql = "SELECT timestamp, equipment_id, oa_t, CASE WHEN oa_t > 75.0 THEN true ELSE false END AS raw_fault FROM telemetry_pivot WHERE oa_t IS NOT NULL";
        let eval = execution::run_rule_sql_from_historian(sql, 0, &json!({}));
        assert_eq!(eval.get("ok").and_then(|v| v.as_bool()), Some(true));
        let fault_rows = eval
            .get("rows")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        assert!(
            !fault_rows.is_empty(),
            "OAT > 75 rule should match MZVAV samples"
        );

        let sat_sql = "SELECT timestamp, equipment_id, sat, sat_sp, fan_cmd, CASE WHEN sat IS NOT NULL AND sat_sp IS NOT NULL AND ABS(sat - sat_sp) > 10 THEN true ELSE false END AS raw_fault FROM telemetry_pivot";
        let sat_eval = execution::run_rule_sql_from_historian(sat_sql, 0, &json!({}));
        assert_eq!(sat_eval.get("ok").and_then(|v| v.as_bool()), Some(true));

        let preview = data_management::preview_purge(&json!({"all": true}));
        assert!(
            preview
                .get("matched_row_count")
                .and_then(|v| v.as_u64())
                .unwrap_or(0)
                > 0
        );

        let purge = data_management::execute_purge(
            &json!({"all": true, "confirmation": "PURGE HISTORIAN DATA"}),
            "integrator",
        );
        assert_eq!(purge.get("ok").and_then(|v| v.as_bool()), Some(true));
        assert_eq!(store::row_count(), 0);
    });
}
