//! CSV UT3 ingest unit and integration tests.

use open_fdd_edge_prototype::csv_ingest::{
    parse::{parse_csv_bytes, sanitize_filename},
    plan::{
        append_rows, auto_detect_mapping, join_rows, parse_file_to_rows, FileMapping, FillPolicy,
        JoinAlignment,
    },
    timestamp::{detect_timestamp_columns, localize_timestamp, parse_timestamp_loose, ParseStatus},
};
use open_fdd_edge_prototype::test_support::with_temp_workspace;
use serde_json::json;

#[test]
fn delimiter_tab_and_bom() {
    let raw = b"\xEF\xBB\xBFa\tb\n1\t2";
    let (p, _) = parse_csv_bytes(raw, None).unwrap();
    assert_eq!(p.delimiter, '\t');
    assert!(p.has_bom);
}

#[test]
fn us_timestamp_parsing() {
    assert!(parse_timestamp_loose("6/19/2013 0:15").is_some());
    assert!(parse_timestamp_loose("2013-01-01T00:00").is_some());
}

#[test]
fn chicago_dst_ambiguous_and_gap() {
    use chrono::NaiveDate;
    let tz: chrono_tz::Tz = "America/Chicago".parse().unwrap();
    let fall = NaiveDate::from_ymd_opt(2013, 11, 3)
        .unwrap()
        .and_hms_opt(1, 30, 0)
        .unwrap();
    assert_eq!(
        localize_timestamp(fall, tz, "first").status,
        ParseStatus::Ambiguous
    );
    let spring = NaiveDate::from_ymd_opt(2013, 3, 10)
        .unwrap()
        .and_hms_opt(2, 30, 0)
        .unwrap();
    assert_eq!(
        localize_timestamp(spring, tz, "first").status,
        ParseStatus::Gap
    );
}

#[test]
fn append_school_samples() {
    let csv = include_str!("fixtures/csv_ingest/school_kw_sample.csv");
    let mapping = FileMapping {
        filename: "school_a.csv".into(),
        timestamp_column: "Date".into(),
        timezone: "America/Chicago".into(),
        value_columns: vec!["kW".into()],
    };
    let rows_a = parse_file_to_rows(csv, &mapping, ',', "first").unwrap();
    let rows_b = parse_file_to_rows(csv, &mapping, ',', "first").unwrap();
    let merged = append_rows(vec![rows_a, rows_b]);
    assert_eq!(merged.len(), 6);
}

#[test]
fn join_weather_floor_hour() {
    let kw_csv = include_str!("fixtures/csv_ingest/school_kw_sample.csv");
    let wx_csv = include_str!("fixtures/csv_ingest/weather_hourly_sample.csv");
    let kw_map = FileMapping {
        filename: "kw.csv".into(),
        timestamp_column: "Date".into(),
        timezone: "America/Chicago".into(),
        value_columns: vec!["kW".into()],
    };
    let wx_map = FileMapping {
        filename: "wx.csv".into(),
        timestamp_column: "time_local".into(),
        timezone: "America/Chicago".into(),
        value_columns: vec!["temp_f".into(), "humidity".into()],
    };
    let left = parse_file_to_rows(kw_csv, &kw_map, ',', "first").unwrap();
    let right = parse_file_to_rows(wx_csv, &wx_map, ',', "first").unwrap();
    let joined = join_rows(left, right, JoinAlignment::FloorHour, FillPolicy::Forward).unwrap();
    assert!(!joined.is_empty());
}

#[test]
fn dataset_save_and_list() {
    with_temp_workspace(|_| {
        let csv = include_str!("fixtures/csv_ingest/school_kw_sample.csv");
        let mapping = auto_detect_mapping("school.csv", &["Date".into(), "kW".into()]);
        let rows = parse_file_to_rows(csv, &mapping, ',', "first").unwrap();
        let report = json!({"warnings": []});
        let out = open_fdd_edge_prototype::csv_ingest::save_dataset(
            "test_school_kw",
            &rows,
            &report,
            &json!({}),
        )
        .unwrap();
        assert_eq!(out.get("ok").and_then(|v| v.as_bool()), Some(true));
        let list = open_fdd_edge_prototype::csv_ingest::list_datasets();
        let datasets = list.get("datasets").and_then(|d| d.as_array()).unwrap();
        assert!(!datasets.is_empty());
    });
}

#[test]
fn path_traversal_filename_rejected() {
    assert!(sanitize_filename("../evil.csv").is_err());
}

#[test]
fn timestamp_column_detection() {
    let headers = vec!["Date".into(), "kW".into()];
    let rows = vec![vec!["6/19/2013 0:15".into(), "1".into()]];
    let cands = detect_timestamp_columns(&headers, &rows);
    assert_eq!(cands[0].0, 0);
}

#[test]
fn plan_api_append_mode() {
    with_temp_workspace(|_| {
        use base64::Engine;
        let prev = open_fdd_edge_prototype::csv_ingest::preview_json_handler(&json!({
            "files": [{
                "filename": "school.csv",
                "content_base64": base64::engine::general_purpose::STANDARD.encode(
                    include_str!("fixtures/csv_ingest/school_kw_sample.csv")
                )
            }]
        }));
        let sid = prev.get("session_id").and_then(|v| v.as_str()).unwrap();
        let plan_body = json!({
            "session_id": sid,
            "plan": {
                "mode": "append",
                "output_dataset_name": "school_kw_test",
                "ambiguous_policy": "first",
                "fill_policy": "none",
                "files": [{
                    "filename": "school.csv",
                    "timestamp_column": "Date",
                    "timezone": "America/Chicago",
                    "value_columns": ["kW"]
                }]
            }
        });
        let planned = open_fdd_edge_prototype::csv_ingest::plan_handler(&plan_body);
        assert_eq!(planned.get("ok").and_then(|v| v.as_bool()), Some(true));
    });
}
