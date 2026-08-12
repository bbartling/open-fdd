//! OFDD-067: `building_id` scoping.
//!
//! Two fake building parquet trees under one `OPENFDD_PARQUET_ROOT` must yield
//! distinct FDD results, site-scoped results directories, and echoed
//! `building_id` — proving B50 and B100 no longer collide in the shared cache.
//! Runs without any Liberty zip (none are shipped in CI).

use std::path::Path;
use std::sync::Arc;

use arrow::array::{ArrayRef, Float64Array, StringArray, TimestampMillisecondArray};
use arrow::datatypes::{DataType, Field, Schema, TimeUnit};
use arrow::record_batch::RecordBatch;
use datafusion::parquet::arrow::ArrowWriter;
use serde_json::{json, Value};

/// Write `building={id}/equipment=VAV_1/part-0.parquet`. When `zone_t` is
/// `Some`, a constant zone temp makes VAV-1 comfort faults deterministic; when
/// `None`, the `zone_t` role is absent so VAV-1 must SKIP (not fail).
/// Equipment id is VAV_1 so `equipment_kinds: [vav, zone]` applies (AHU_1 is N/A).
fn write_building(parquet_root: &Path, building_id: &str, zone_t: Option<f64>, rows: usize) {
    let dir = parquet_root
        .join(format!("building={building_id}"))
        .join("equipment=VAV_1");
    std::fs::create_dir_all(&dir).unwrap();

    let equipment: Vec<&str> = vec!["VAV_1"; rows];
    // Millisecond epoch @ 5-min cadence so window ORDER BY works on a real
    // timestamp column (string columns break DataFusion RANGE frames).
    let ts: Vec<i64> = (0..rows as i64)
        .map(|i| 1_767_225_600_000 + i * 300_000)
        .collect();

    let mut fields = vec![
        Field::new("equipment_id", DataType::Utf8, false),
        Field::new(
            "timestamp_utc",
            DataType::Timestamp(TimeUnit::Millisecond, None),
            false,
        ),
    ];
    let mut columns: Vec<ArrayRef> = vec![
        Arc::new(StringArray::from(equipment)) as ArrayRef,
        Arc::new(TimestampMillisecondArray::from(ts)) as ArrayRef,
    ];
    match zone_t {
        Some(z) => {
            fields.push(Field::new("zone_t", DataType::Float64, false));
            columns.push(Arc::new(Float64Array::from(vec![z; rows])) as ArrayRef);
        }
        None => {
            // A benign column so the parquet is non-empty but lacks zone_t.
            fields.push(Field::new("fan_cmd", DataType::Float64, false));
            columns.push(Arc::new(Float64Array::from(vec![1.0; rows])) as ArrayRef);
        }
    }

    let schema = Arc::new(Schema::new(fields));
    let batch = RecordBatch::try_new(schema, columns).unwrap();

    let file = std::fs::File::create(dir.join("part-0.parquet")).unwrap();
    let mut writer = ArrowWriter::try_new(file, batch.schema(), None).unwrap();
    writer.write(&batch).unwrap();
    writer.close().unwrap();
}

fn total_fault_hours(v: &Value) -> f64 {
    v["results"]
        .as_array()
        .map(|rows| {
            rows.iter()
                .map(|r| r["fault_hours"].as_f64().unwrap_or(0.0))
                .sum()
        })
        .unwrap_or(0.0)
}

#[test]
fn building_id_scopes_results_and_faults() {
    let tmp = std::env::temp_dir().join(format!("ofdd-bldg-scope-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&tmp);
    let parquet_root = tmp.join("parquet");
    let results_root = tmp.join("results");
    std::fs::create_dir_all(&parquet_root).unwrap();

    // B50 sits inside the comfort band (no faults); B100 is far above it so
    // VAV-1 confirms a fault streak — the two sites MUST differ.
    write_building(&parquet_root, "B50", Some(72.0), 60);
    write_building(&parquet_root, "B100", Some(95.0), 60);
    // BNOROLE lacks zone_t entirely → VAV-1 must SKIP, not fail (OFDD-066).
    write_building(&parquet_root, "BNOROLE", None, 60);

    let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    let sql_rules = manifest_dir.join("../sql_rules");
    assert!(
        sql_rules.join("registry.yaml").is_file(),
        "sql_rules missing"
    );

    std::env::set_var("OPENFDD_PARQUET_ROOT", &parquet_root);
    std::env::set_var("OPENFDD_RULE_RESULTS_DIR", &results_root);
    std::env::set_var("OPENFDD_SQL_RULES_DIR", &sql_rules);

    let run = |bid: &str| {
        let payload = json!({
            "mode": "registry",
            "rule_ids": ["VAV-1"],
            "building_id": bid,
        });
        open_fdd_edge_prototype::fdd::registry_api::run_registry(&payload)
    };

    let b50 = run("B50");
    let b100 = run("B100");

    assert_eq!(b50["ok"], json!(true), "B50 run: {b50}");
    assert_eq!(b100["ok"], json!(true), "B100 run: {b100}");
    assert_eq!(b50["building_id"], json!("B50"), "B50 echo: {b50}");
    assert_eq!(b100["building_id"], json!("B100"), "B100 echo: {b100}");

    // Site-scoped results directories are distinct and both populated.
    let b50_file = results_root.join("building=B50").join("VAV-1.json");
    let b100_file = results_root.join("building=B100").join("VAV-1.json");
    assert!(b50_file.is_file(), "missing scoped results {b50_file:?}");
    assert!(b100_file.is_file(), "missing scoped results {b100_file:?}");

    // FAULT totals must differ (the OFDD-067 smoking gun: they used to match).
    let f50 = total_fault_hours(&b50);
    let f100 = total_fault_hours(&b100);
    assert!(f100 > 0.0, "expected B100 to fault: {b100}");
    assert!(
        f50 < f100,
        "expected B50 fewer faults than B100: {f50} vs {f100}"
    );

    // Equipment listing is scoped to the requested building.
    let eq = open_fdd_edge_prototype::fdd::registry_api::equipment_response(Some("B50"));
    assert_eq!(eq["ok"], json!(true), "equipment: {eq}");
    let ids: Vec<String> = eq["equipment"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|e| e["equipment_id"].as_str().map(str::to_string))
        .collect();
    assert!(ids.contains(&"VAV_1".to_string()), "equipment: {eq}");

    // results_response reads each scoped dir independently.
    let r50 = open_fdd_edge_prototype::fdd::registry_api::results_response(Some("B50"));
    let r100 = open_fdd_edge_prototype::fdd::registry_api::results_response(Some("B100"));
    assert!(
        total_fault_hours(&r50) < total_fault_hours(&r100),
        "scoped results_response must differ: {r50} vs {r100}"
    );

    // OFDD-066: a building missing the required role SKIPS rather than failing.
    let skip = run("BNOROLE");
    assert_eq!(skip["ok"], json!(true), "skip run: {skip}");
    assert_eq!(
        skip["rules_failed"],
        json!(0),
        "missing role must not count as failure: {skip}"
    );
    assert_eq!(
        skip["rules_skipped"].as_u64().unwrap_or(0),
        1,
        "expected VAV-1 skipped: {skip}"
    );
    let skip_status = skip["results"][0]["status"].as_str().unwrap_or("");
    assert_eq!(skip_status, "SKIPPED_MISSING_ROLES", "skip status: {skip}");
    let missing = skip["results"][0]["missing_roles"]
        .as_array()
        .map(|a| a.iter().filter_map(|v| v.as_str()).any(|s| s == "zone_t"))
        .unwrap_or(false);
    assert!(missing, "expected zone_t in missing_roles: {skip}");

    let _ = std::fs::remove_dir_all(&tmp);
}
