//! T1402-1: Postgres persistence for FDD registry runs.

#[cfg(test)]
mod fdd_run_persists_runs_intervals_checkpoint {
    use serde_json::json;
    use sqlx::PgPool;

    use crate::fdd_registry_persist::{
        commit_and_persist_registry_run, fdd_persist_counts, results_from_timescale,
    };
    use open_fdd_edge_prototype::fdd::registry_api::{
        RunGenerationCommit, RunModelEquipment, RunRuleFile,
    };

    async fn pool() -> Option<PgPool> {
        let explicit = std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .filter(|v| !v.trim().is_empty());
        let had_explicit = explicit.is_some();
        let url = explicit
            .unwrap_or_else(|| "postgresql://openfdd:openfdd@127.0.0.1:5432/openfdd".to_string());
        match sqlx::postgres::PgPoolOptions::new()
            .max_connections(2)
            .connect(&url)
            .await
        {
            Ok(pool) => Some(pool),
            Err(_) if had_explicit => panic!("OPENFDD_TEST_DATABASE_URL connect failed"),
            Err(_) => {
                eprintln!("skip: postgres fixture unavailable");
                None
            }
        }
    }

    async fn apply_schema(pool: &PgPool) {
        for statement in
            fdd_tsdb::schema_statements(include_str!("../../../sql/schema/01_bps_core.sql"))
        {
            if statement.contains("fdd_run") {
                crate::test_ddl::execute_idempotent_ddl(pool, statement).await;
            }
        }
        fdd_tsdb::ensure_revision_schema(pool)
            .await
            .expect("revision schema");
        fdd_tsdb::ensure_incremental_schema(pool)
            .await
            .expect("incremental schema");
    }

    fn fixture_commit(site: &str) -> RunGenerationCommit {
        RunGenerationCommit {
            building_id: site.to_string(),
            full_cohort: true,
            equipment: vec![RunModelEquipment {
                equipment_id: "AHU_1".into(),
                equip_type: Some("ahu".into()),
            }],
            rules: vec![RunRuleFile {
                rule_id: "FIXTURE-FAULT".into(),
                body: json!({
                    "rule_id": "FIXTURE-FAULT",
                    "rows": [{
                        "equipment_id": "AHU_1",
                        "status": "FAULT",
                        "output_kind": "diagnostic",
                        "fault_hours": 1.0,
                        "covered_hours": 1.0,
                        "sample_rows": 2,
                        "confirm_seconds": 0.0,
                    }],
                }),
            }],
            config_fingerprint: "fixture-fp".into(),
            window_start: Some("2026-06-01T00:00:00Z".into()),
            window_end: Some("2026-06-01T01:00:00Z".into()),
            watermark: None,
            poll_seconds: 300.0,
            pack: json!({ "pack_version": "test-pack" }),
        }
    }

    #[tokio::test]
    async fn fdd_run_persists_runs_intervals_checkpoint() {
        let Some(pool) = pool().await else {
            return;
        };
        let site = format!("t1402{}", uuid::Uuid::new_v4().simple());
        apply_schema(&pool).await;
        let _ = sqlx::query("DELETE FROM fdd_run WHERE site_id = $1")
            .bind(&site)
            .execute(&pool)
            .await;
        let tsdb = fdd_tsdb::Tsdb::from_pool(pool.clone());
        let summary = commit_and_persist_registry_run(&tsdb, fixture_commit(&site))
            .await
            .expect("persist");
        let (runs, intervals, checkpoints) =
            fdd_persist_counts(&tsdb, &site).await.expect("counts");
        assert!(runs > 0, "fdd_run rows");
        assert_eq!(intervals, 1, "one hourly bucket for the one-hour window");
        assert_eq!(checkpoints, 1, "one incremental checkpoint");
        let api = results_from_timescale(&tsdb, Some(&site), &std::collections::BTreeMap::new())
            .await
            .expect("api");
        assert_eq!(
            api["results"].as_array().map(|a| a.len()).unwrap_or(0),
            summary["results"].as_array().map(|a| a.len()).unwrap_or(0)
        );
        let (runs2, intervals2, checkpoints2) =
            fdd_persist_counts(&tsdb, &site).await.expect("counts2");
        let _ = commit_and_persist_registry_run(&tsdb, fixture_commit(&site))
            .await
            .expect("re-run");
        assert_eq!(runs, runs2);
        assert_eq!(intervals, intervals2);
        assert_eq!(checkpoints, checkpoints2);
        let _ = sqlx::query("DELETE FROM fdd_run WHERE site_id = $1")
            .bind(&site)
            .execute(&pool)
            .await;
    }
}
