//! Optional operator-env TADCO smoke — no committed CSV in repo.
//! Run: OPENFDD_TADCO_IMPORT_DIR=/path/to/hvac_systems_CLEANED cargo test tadco_env_preflight -- --ignored

use open_fdd_edge_prototype::csv_ingest;
use open_fdd_edge_prototype::test_support::with_temp_workspace;
use serde_json::json;
use std::env;
use std::fs;
use std::path::Path;

#[test]
#[ignore = "requires OPENFDD_TADCO_IMPORT_DIR with operator-sidecar CSVs"]
fn tadco_env_preflight() {
    let dir = env::var("OPENFDD_TADCO_IMPORT_DIR").expect("OPENFDD_TADCO_IMPORT_DIR");
    let dir_path = Path::new(&dir);
    assert!(dir_path.is_dir(), "import dir missing: {dir}");

    with_temp_workspace(|_| {
        let mut files = Vec::new();
        for entry in fs::read_dir(dir_path).unwrap() {
            let entry = entry.unwrap();
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) == Some("csv") {
                files.push(json!({
                    "filename": path.file_name().unwrap().to_string_lossy(),
                    "path": path.display().to_string()
                }));
            }
        }
        assert!(!files.is_empty(), "no CSV files in {dir}");

        let preview = csv_ingest::preview_json_handler(&json!({ "files": files }));
        assert_eq!(preview.get("ok").and_then(|v| v.as_bool()), Some(true));
        let sid = preview.get("session_id").and_then(|v| v.as_str()).unwrap();

        // Operator must supply plan via MCP/API; this test only asserts preview + preflight API shape.
        let preflight = csv_ingest::preflight_handler(&json!({ "session_id": sid }));
        assert!(preflight.get("verdict").is_some());
        assert!(preflight.get("validation").is_some());
    });
}
