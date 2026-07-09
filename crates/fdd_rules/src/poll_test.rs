#[cfg(test)]
mod poll_interval {
    use std::io::Write;
    use tempfile::TempDir;

    use crate::{poll_params, substitute_sql};
    use fdd_store::ingest_building;

    #[test]
    fn non_300_second_grid_substituted_in_sql() {
        let tmp = TempDir::new().unwrap();
        let building = tmp.path().join("B15");
        std::fs::create_dir_all(&building).unwrap();
        std::fs::write(building.join("manifest.json"), r#"{"grid_minutes":15}"#).unwrap();
        let ahu = building.join("AHU_1");
        std::fs::create_dir_all(&ahu).unwrap();
        std::fs::write(
            ahu.join("columns.csv"),
            "col,point_role\nzone_t,zone_temp\n",
        )
        .unwrap();
        let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,zone_t").unwrap();
        writeln!(f, "2026-01-01T00:00:00Z,70").unwrap();

        let parquet = tmp.path().join("parquet");
        ingest_building(tmp.path(), "B15", &parquet).unwrap();
        let manifest = std::fs::read_to_string(parquet.join("manifest.json")).unwrap();
        assert!(manifest.contains("900"));

        let sql = "SELECT COUNT(*) * {{POLL_SECONDS}} / 3600.0 AS hours FROM history";
        let out = substitute_sql(sql, &poll_params(900.0));
        assert!(out.contains("900"));
    }
}
