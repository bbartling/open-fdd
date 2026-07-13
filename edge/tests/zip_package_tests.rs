//! ZIP package parity tests (Phase 1 / #481).

use open_fdd_edge_prototype::csv_ingest::zip_package::{
    extract_zip_bytes, inspect_zip_bytes, plan_handler, safe_member_path, PackageCaps,
};
use open_fdd_edge_prototype::test_support::with_temp_workspace;
use serde_json::json;
use std::io::{Cursor, Write};
use std::path::PathBuf;
use zip::write::SimpleFileOptions;
use zip::CompressionMethod;

fn tight_caps() -> PackageCaps {
    PackageCaps {
        max_zip_bytes: 2 * 1024 * 1024,
        max_uncompressed_bytes: 2 * 1024 * 1024,
        max_entries: 50,
        max_ratio: 100.0,
        max_single_entry_bytes: 1 * 1024 * 1024,
    }
}

fn write_zip(entries: &[(&str, &[u8])]) -> Vec<u8> {
    let mut cursor = Cursor::new(Vec::new());
    {
        let mut zip = zip::ZipWriter::new(&mut cursor);
        let opts = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);
        for (name, data) in entries {
            if name.ends_with('/') {
                zip.add_directory(*name, opts).unwrap();
            } else {
                zip.start_file(*name, opts).unwrap();
                zip.write_all(data).unwrap();
            }
        }
        zip.finish().unwrap();
    }
    cursor.into_inner()
}

#[test]
fn fixture_tiny_package_zip_valid() {
    let bytes = include_bytes!("fixtures/zip_package/tiny_package.zip");
    let metas = inspect_zip_bytes(bytes, &tight_caps()).unwrap();
    assert!(metas.iter().any(|m| {
        m.rel_path
            .to_string_lossy()
            .contains("AHU_1/history_wide.csv")
    }));
    assert!(metas
        .iter()
        .any(|m| { m.rel_path.to_string_lossy().ends_with("column_map.json") }));
}

#[test]
fn fixture_nested_extract_and_plan() {
    with_temp_workspace(|ws| {
        let bytes = include_bytes!("fixtures/zip_package/tiny_package.zip");
        let dest = ws.join("extract");
        let metas = extract_zip_bytes(bytes, &dest, &tight_caps()).unwrap();
        assert!(metas.len() >= 4);

        // Store as package then plan via handler
        let pkg = open_fdd_edge_prototype::csv_ingest::zip_package::inspect_handler(
            "application/json",
            &serde_json::to_vec(&json!({
                "filename": "tiny_package.zip",
                "content_base64": base64::Engine::encode(
                    &base64::engine::general_purpose::STANDARD,
                    bytes
                ),
            }))
            .unwrap(),
        );
        assert_eq!(pkg["ok"], json!(true), "{pkg}");
        assert!(pkg["csv_files"].as_array().unwrap().len() >= 2);
        assert_eq!(pkg["mapping_status"]["valid"], json!(true));

        let pid = pkg["package_id"].as_str().unwrap();
        let planned = plan_handler(&json!({ "package_id": pid }));
        assert_eq!(planned["ok"], json!(true), "{planned}");
        assert!(planned["session_id"].as_str().unwrap().starts_with("csv-"));
        assert_eq!(planned["mapping_applied"], json!(true));
        assert!(planned["files"].as_array().unwrap().len() >= 2);
    });
}

#[test]
fn missing_mapping_reported() {
    with_temp_workspace(|_| {
        let data = write_zip(&[
            (
                "manifest.json",
                br#"{"schema_version":"openfdd_package_v1","building_id":"X","grid_minutes":5,"timezone":"UTC"}"#,
            ),
            ("equip/history_wide.csv", b"timestamp,oa_t\n2024-01-01T00:00:00Z,1\n"),
        ]);
        let pkg = open_fdd_edge_prototype::csv_ingest::zip_package::inspect_handler(
            "application/json",
            &serde_json::to_vec(&json!({
                "filename": "nomap.zip",
                "content_base64": base64::Engine::encode(
                    &base64::engine::general_purpose::STANDARD,
                    &data
                ),
            }))
            .unwrap(),
        );
        assert_eq!(pkg["ok"], json!(true), "{pkg}");
        assert_eq!(pkg["mapping_status"]["present"], json!(false));
        let planned = plan_handler(&json!({ "package_id": pkg["package_id"] }));
        assert_eq!(planned["ok"], json!(true), "{planned}");
        assert_eq!(planned["mapping_applied"], json!(false));
    });
}

#[test]
fn invalid_mapping_reported() {
    with_temp_workspace(|_| {
        let data = write_zip(&[
            (
                "column_map.json",
                br#"{"version":1,"dataset_id":"x","timezone":"UTC","timestamp_column":"ts","equipment":"e","column_map":{"a":"oa_t","b":"oa_t"}}"#,
            ),
            ("history_wide.csv", b"timestamp,a,b\n2024-01-01T00:00:00Z,1,2\n"),
        ]);
        let pkg = open_fdd_edge_prototype::csv_ingest::zip_package::inspect_handler(
            "application/json",
            &serde_json::to_vec(&json!({
                "filename": "badmap.zip",
                "content_base64": base64::Engine::encode(
                    &base64::engine::general_purpose::STANDARD,
                    &data
                ),
            }))
            .unwrap(),
        );
        assert_eq!(pkg["ok"], json!(true), "{pkg}");
        // Duplicate roles → not a valid Phase-1 doc; find_column_map may still return it
        // if it has column_map + version + dataset_id, then mapping_status.valid=false.
        assert_eq!(pkg["mapping_status"]["present"], json!(true));
        assert_eq!(pkg["mapping_status"]["valid"], json!(false));
    });
}

#[test]
fn traversal_attack_rejected() {
    assert!(safe_member_path("../etc/passwd").is_err());
    let data = write_zip(&[("../escape.csv", b"a,b\n1,2\n")]);
    let err = inspect_zip_bytes(&data, &tight_caps()).unwrap_err();
    assert!(
        err.contains("traversal") || err.contains("absolute"),
        "{err}"
    );
}

#[test]
fn oversized_rejected() {
    let caps = PackageCaps {
        max_single_entry_bytes: 16,
        ..tight_caps()
    };
    let big = vec![b'a'; 64];
    let data = write_zip(&[("big.csv", big.as_slice())]);
    let err = inspect_zip_bytes(&data, &caps).unwrap_err();
    assert!(
        err.contains("exceeds") || err.contains("single-file"),
        "{err}"
    );
}

#[test]
fn corrupted_rejected() {
    let err = inspect_zip_bytes(b"PK\x03\x04truncateded", &tight_caps()).unwrap_err();
    assert!(
        err.contains("corrupted") || err.contains("invalid"),
        "{err}"
    );
}

#[test]
fn duplicate_names_rejected() {
    let data = write_zip(&[
        (
            "AHU_1/history_wide.csv",
            b"timestamp,oa_t\n2024-01-01T00:00:00Z,1\n",
        ),
        (
            "ahu_1/history_wide.csv",
            b"timestamp,oa_t\n2024-01-01T00:00:00Z,2\n",
        ),
    ]);
    let err = inspect_zip_bytes(&data, &tight_caps()).unwrap_err();
    assert!(
        err.contains("duplicate") || err.contains("case-colliding"),
        "{err}"
    );
}

#[test]
fn unsupported_contents_rejected() {
    let data = write_zip(&[("payload.bin", b"\x00\x01\x02")]);
    let err = inspect_zip_bytes(&data, &tight_caps()).unwrap_err();
    assert!(err.contains("unsupported"), "{err}");
}

#[test]
fn absolute_path_rejected() {
    assert!(safe_member_path("/tmp/x.csv").is_err());
    assert_eq!(
        safe_member_path("weather/history_wide.csv").unwrap(),
        PathBuf::from("weather/history_wide.csv")
    );
}
