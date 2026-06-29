//! Manual Lake Geneva CSV integration — set OPENFDD_CSV_FIXTURE_DIR to operator test folder.

use open_fdd_edge_prototype::csv_ingest::{
    parse::parse_csv_bytes,
    plan::{append_rows, join_rows, parse_file_to_rows, FileMapping, FillPolicy, JoinAlignment},
};
use std::fs;
use std::path::PathBuf;

fn fixture_dir() -> Option<PathBuf> {
    std::env::var("OPENFDD_CSV_FIXTURE_DIR")
        .ok()
        .map(PathBuf::from)
        .filter(|p| p.is_dir())
}

#[test]
#[ignore = "requires OPENFDD_CSV_FIXTURE_DIR with Lake Geneva CSV files"]
fn lake_geneva_append_four_school_files() {
    let dir = fixture_dir().expect("OPENFDD_CSV_FIXTURE_DIR");
    let names = [
        "School_2013_2014_KW.csv",
        "School_2014_2015 KW.csv",
        "School_2015_2016 KW.csv",
        "School_2016_2017_KW.csv",
    ];
    let mut batches = Vec::new();
    for name in names {
        let raw = fs::read(dir.join(name)).expect("school file");
        let (profile, text) = parse_csv_bytes(&raw, None).expect("parse");
        let mapping = FileMapping {
            filename: name.to_string(),
            timestamp_column: "Date".into(),
            timezone: "America/Chicago".into(),
            value_columns: vec!["kW".into()],
        };
        let rows = parse_file_to_rows(&text, &mapping, profile.delimiter, "first").unwrap();
        assert!(rows.len() > 1000, "{name} should have substantial rows");
        batches.push(rows);
    }
    let merged = append_rows(batches);
    assert!(merged.len() > 50_000);
}

#[test]
#[ignore = "requires OPENFDD_CSV_FIXTURE_DIR with Lake Geneva CSV files"]
fn lake_geneva_join_weather_to_kw() {
    let dir = fixture_dir().expect("OPENFDD_CSV_FIXTURE_DIR");
    let wx_raw =
        fs::read(dir.join("lake_geneva_wi_open_meteo_2013_2018_hourly.csv")).expect("weather");
    let (wx_profile, wx_text) = parse_csv_bytes(&wx_raw, None).unwrap();
    let school_raw = fs::read(dir.join("School_2013_2014_KW.csv")).unwrap();
    let (kw_profile, kw_text) = parse_csv_bytes(&school_raw, None).unwrap();

    let kw_map = FileMapping {
        filename: "school.csv".into(),
        timestamp_column: "Date".into(),
        timezone: "America/Chicago".into(),
        value_columns: vec!["kW".into()],
    };
    let wx_map = FileMapping {
        filename: "weather.csv".into(),
        timestamp_column: "time_local".into(),
        timezone: "America/Chicago".into(),
        value_columns: wx_profile
            .headers
            .iter()
            .filter(|h| *h != "time_local")
            .take(5)
            .cloned()
            .collect(),
    };
    let left = parse_file_to_rows(&kw_text, &kw_map, kw_profile.delimiter, "first").unwrap();
    let right = parse_file_to_rows(&wx_text, &wx_map, wx_profile.delimiter, "first").unwrap();
    let joined = join_rows(left, right, JoinAlignment::FloorHour, FillPolicy::Forward).unwrap();
    assert!(!joined.is_empty());
}
