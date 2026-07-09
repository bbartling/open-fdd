#[cfg(test)]
mod tests {
    //! Regression test for the ECON-4 confirm-streak parity bug (Stage 4 fix).
    //!
    //! `econ4_low_oa_frac.sql` grouped its confirm streak by the cumulative count of
    //! `raw_fault = 0` rows. That gives every run of consecutive true rows a one-row
    //! "head start" from the false row immediately preceding it, so the SQL confirmed
    //! faults after only `CONFIRM_ROWS - 1` consecutive true samples instead of
    //! `CONFIRM_ROWS` — over-counting fault hours vs. the pandas `confirm_fault()`
    //! oracle (see `rules/base.py`), which groups on `raw != raw.shift()`.
    //!
    //! This builds a synthetic AHU_1-style sample sequence with an isolated one-row
    //! blip plus two longer runs, and asserts the shipped SQL now agrees with the
    //! pandas-equivalent confirmed count.

    use std::io::Write;
    use std::path::Path;

    use fdd_sql::{register_parquet_tree, run_sql};
    use fdd_store::ingest_building;

    use crate::params::{rule_params, substitute_sql};

    fn write_ahu1_fixture(building_root: &Path) {
        std::fs::write(
            building_root.join("manifest.json"),
            r#"{"grid_minutes": 5}"#,
        )
        .unwrap();
        let ahu = building_root.join("AHU_1");
        std::fs::create_dir_all(&ahu).unwrap();
        std::fs::write(
            ahu.join("columns.csv"),
            "col,point_role\nmat_col,mat\nrat_col,rat\noat_col,oa_t\nfan_col,fan_cmd\n",
        )
        .unwrap();

        // rat=70, oa_t=30 constant -> |rat-oa_t|=40 > 2.2 always true.
        // fan_cmd=50 -> normalized 0.5 > 0.01 always on.
        // oa_frac = (mat-rat)/(oa_t-rat)*100 = (70-mat)*2.5
        //   mat=50 -> oa_frac=50.0  (>= 21, not a fault)
        //   mat=65 -> oa_frac=12.5  (< 21, is a fault)
        // raw_fault sequence:  0    0    1    1    1    0    1    1    0    1
        let mats = [50.0, 50.0, 65.0, 65.0, 65.0, 50.0, 65.0, 65.0, 50.0, 65.0];

        let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,mat_col,rat_col,oat_col,fan_col").unwrap();
        for (i, mat) in mats.iter().enumerate() {
            let minute = i * 5;
            writeln!(f, "2026-01-01T00:{minute:02}:00Z,{mat},70.0,30.0,50.0").unwrap();
        }
    }

    #[tokio::test]
    async fn econ4_confirm_streak_matches_pandas_reference() {
        let tmp = tempfile::TempDir::new().unwrap();
        let data_root = tmp.path().join("data");
        let building = data_root.join("BUILDING_100");
        std::fs::create_dir_all(&building).unwrap();
        write_ahu1_fixture(&building);

        let parquet_root = tmp.path().join("parquet");
        ingest_building(&data_root, "BUILDING_100", &parquet_root).unwrap();

        let ctx = datafusion::prelude::SessionContext::new();
        register_parquet_tree(&ctx, &parquet_root).await.unwrap();

        let sql_path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("sql_rules")
            .join("econ4_low_oa_frac.sql");
        let raw_sql = std::fs::read_to_string(&sql_path)
            .unwrap_or_else(|e| panic!("read {}: {e}", sql_path.display()));

        // registry.yaml: ECON-4 confirm_seconds = 600 -> CONFIRM_ROWS = ceil(600/300) = 2.
        let params = rule_params(300.0, 600);
        let sql = substitute_sql(&raw_sql, &params);
        let result = run_sql(&ctx, &sql).await.unwrap();

        assert_eq!(result.row_count, 1);
        let fault_hours = result.rows[0]
            .get("fault_hours")
            .and_then(|v| v.as_f64())
            .unwrap();

        // pandas confirm_fault() reference on 0,0,1,1,1,0,1,1,0,1 with rows=2:
        // only samples at index 3,4,7 confirm (3 samples) = 3 * 300s / 3600 = 0.25h.
        // Pre-fix the buggy streak grouping confirmed index 2,3,4,6,7,9 (6 samples) = 0.5h.
        assert!(
            (fault_hours - 0.25).abs() < 1e-6,
            "expected 0.25h (pandas-equivalent confirm), got {fault_hours}"
        );
    }
}
