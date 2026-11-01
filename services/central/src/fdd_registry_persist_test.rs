//! T1402-1 / UP-03: Postgres persistence for FDD registry runs and interval evidence.

#[cfg(test)]
mod fdd_run_persists_runs_intervals_checkpoint {
    use serde_json::json;
    use sqlx::PgPool;

    use crate::fdd_registry_persist::{
        commit_and_persist_registry_run, results_from_timescale, IntervalPersistReasonCode,
        INTERVAL_EVIDENCE_UNKNOWN,
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

    async fn fdd_persist_counts(tsdb: &fdd_tsdb::Tsdb, site_id: &str) -> (i64, i64, i64) {
        let pool = tsdb.pool();
        let runs: i64 =
            sqlx::query_scalar("SELECT COUNT(*)::bigint FROM fdd_run WHERE site_id = $1")
                .bind(site_id)
                .fetch_one(pool)
                .await
                .expect("fdd_run count");
        let intervals: i64 = sqlx::query_scalar(
            "SELECT COUNT(*)::bigint FROM fdd_interval_result WHERE site_id = $1",
        )
        .bind(site_id)
        .fetch_one(pool)
        .await
        .expect("interval count");
        let checkpoints: i64 = sqlx::query_scalar(
            "SELECT COUNT(*)::bigint FROM fdd_incremental_checkpoint WHERE site_id = $1",
        )
        .bind(site_id)
        .fetch_one(pool)
        .await
        .expect("checkpoint count");
        (runs, intervals, checkpoints)
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
        let (runs, intervals, checkpoints) = fdd_persist_counts(&tsdb, &site).await;
        assert!(runs > 0, "fdd_run rows");
        assert_eq!(
            intervals, 0,
            "no proportional fallback when series unavailable"
        );
        assert_eq!(checkpoints, 0, "no checkpoint without exact buckets");
        let stored_status: String =
            sqlx::query_scalar("SELECT status FROM fdd_run WHERE site_id = $1 LIMIT 1")
                .bind(&site)
                .fetch_one(&pool)
                .await
                .expect("status");
        assert_eq!(stored_status, "FAULT", "whole-window status preserved");
        let reason_code: String = sqlx::query_scalar(
            "SELECT detail->'interval_persist'->>'reason_code' FROM fdd_run WHERE site_id = $1 LIMIT 1",
        )
        .bind(&site)
        .fetch_one(&pool)
        .await
        .expect("reason_code");
        assert_eq!(
            reason_code,
            IntervalPersistReasonCode::RuleNotInRegistry.as_str()
        );
        let api = results_from_timescale(&tsdb, Some(&site), &std::collections::BTreeMap::new())
            .await
            .expect("api");
        let first = &api["results"][0];
        assert_eq!(
            first["status"].as_str(),
            Some("FAULT"),
            "API keeps rule status"
        );
        assert_eq!(
            first["interval_status"].as_str(),
            Some(INTERVAL_EVIDENCE_UNKNOWN)
        );
        assert_eq!(
            api["results"].as_array().map(|a| a.len()).unwrap_or(0),
            summary["results"].as_array().map(|a| a.len()).unwrap_or(0)
        );
        let (runs2, intervals2, checkpoints2) = fdd_persist_counts(&tsdb, &site).await;
        let _ = commit_and_persist_registry_run(&tsdb, fixture_commit(&site))
            .await
            .expect("re-run");
        assert_eq!(runs, runs2);
        assert_eq!(intervals, intervals2);
        assert_eq!(
            checkpoints, checkpoints2,
            "idempotent — no checkpoint retry loop"
        );
        let _ = sqlx::query("DELETE FROM fdd_run WHERE site_id = $1")
            .bind(&site)
            .execute(&pool)
            .await;
    }
}

#[cfg(test)]
mod up03_postgres_exact_buckets {
    use chrono::{Duration, TimeZone, Utc};
    use fdd_tsdb::{SampleRow, Tsdb, UpsertBatch};
    use serde_json::json;
    use sqlx::PgPool;

    use crate::fdd_registry_persist::{commit_and_persist_registry_run, INTERVAL_EVIDENCE_EXACT};
    use open_fdd_edge_prototype::fdd::registry_api::{
        RunGenerationCommit, RunModelEquipment, RunRuleFile,
    };

    const HELPERS: &str = include_str!("../../../sql/fdd/postgres/postgres_helpers.sql");
    const PACK_RUNTIME: &str = include_str!("../../../sql/schema/06_fdd_pack_runtime.sql");

    async fn pool() -> Option<PgPool> {
        let url = std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .filter(|v| !v.trim().is_empty())?;
        sqlx::postgres::PgPoolOptions::new()
            .max_connections(3)
            .connect(&url)
            .await
            .ok()
    }

    async fn apply_schema(pool: &PgPool) {
        crate::portal_inventory_fixtures::apply_schema(pool).await;
        crate::series_binding::ensure_authorized_series(pool).await;
        let mut conn = pool.acquire().await.expect("conn");
        for statement in crate::db_lifecycle::statements(HELPERS) {
            sqlx::raw_sql(&statement)
                .execute(&mut *conn)
                .await
                .expect("helpers");
        }
        for statement in crate::db_lifecycle::statements(PACK_RUNTIME) {
            sqlx::raw_sql(&statement)
                .execute(&mut *conn)
                .await
                .expect("pack runtime");
        }
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

    async fn seed_site(pool: &PgPool, site: &str, equipment_id: &str) {
        sqlx::query("INSERT INTO site (site_id, dis) VALUES ($1, $1) ON CONFLICT DO NOTHING")
            .bind(site)
            .execute(pool)
            .await
            .expect("site");
        sqlx::query(
            "INSERT INTO building (building_id, site_id, dis) VALUES ($1, $1, $1) ON CONFLICT DO NOTHING",
        )
        .bind(site)
        .execute(pool)
        .await
        .expect("building");
        sqlx::query(
            "INSERT INTO equipment (building_id, equipment_id, equip_type) VALUES ($1, $2, 'ahu') ON CONFLICT DO NOTHING",
        )
        .bind(site)
        .bind(equipment_id)
        .execute(pool)
        .await
        .expect("equip");
    }

    async fn bind_role(pool: &PgPool, site: &str, equipment_id: &str, role: &str, key: &str) {
        sqlx::query(
            "INSERT INTO point_map (site_id, openfdd_key, haystack_id, role, equipment_id, referenced)
             VALUES ($1, $2, $2, $3, $4, true)
             ON CONFLICT (site_id, openfdd_key) DO UPDATE SET role = EXCLUDED.role",
        )
        .bind(site)
        .bind(key)
        .bind(role)
        .bind(equipment_id)
        .execute(pool)
        .await
        .expect("point_map");
        sqlx::query(
            "INSERT INTO role_map (building_id, equipment_id, openfdd_key, role)
             VALUES ($1, $2, $3, $4)
             ON CONFLICT (building_id, equipment_id, openfdd_key) DO UPDATE SET role = EXCLUDED.role",
        )
        .bind(site)
        .bind(equipment_id)
        .bind(key)
        .bind(role)
        .execute(pool)
        .await
        .expect("role_map");
    }

    fn push_cmd_status(
        batch: &mut UpsertBatch,
        site: &str,
        equipment_id: &str,
        ts: chrono::DateTime<Utc>,
        cmd: f64,
        status: f64,
    ) {
        let mut cmd_row = SampleRow::new(ts, site, format!("{equipment_id}.fan_cmd"), Some(cmd));
        cmd_row.equipment_id = Some(equipment_id.to_string());
        cmd_row.role = Some("fan_cmd".into());
        cmd_row.source_unit = Some("fraction".into());
        cmd_row.quantity = Some("fraction".into());
        batch.push(cmd_row);
        let mut st_row =
            SampleRow::new(ts, site, format!("{equipment_id}.fan_status"), Some(status));
        st_row.equipment_id = Some(equipment_id.to_string());
        st_row.role = Some("fan_status".into());
        st_row.source_unit = Some("fraction".into());
        st_row.quantity = Some("fraction".into());
        batch.push(st_row);
    }

    #[tokio::test]
    async fn up03_postgres_exact_daily_buckets_from_confirmed_series() {
        let Some(pool) = pool().await else {
            eprintln!("skip: OPENFDD_TEST_DATABASE_URL unset");
            return;
        };
        let site = format!("up03{}", uuid::Uuid::new_v4().simple());
        apply_schema(&pool).await;
        let tsdb = Tsdb::from_pool(pool.clone());
        tsdb.ensure_site_building(&site)
            .await
            .expect("site building");
        let eq_day2 = "AHU_DAY2";
        seed_site(&pool, &site, eq_day2).await;
        bind_role(
            &pool,
            &site,
            eq_day2,
            "fan_cmd",
            &format!("{eq_day2}.fan_cmd"),
        )
        .await;
        bind_role(
            &pool,
            &site,
            eq_day2,
            "fan_status",
            &format!("{eq_day2}.fan_status"),
        )
        .await;

        let window_start = "2026-10-10T00:00:00Z";
        let window_end = "2026-10-12T00:00:00Z";
        let mut batch = UpsertBatch::default();
        let base = Utc.with_ymd_and_hms(2026, 10, 10, 0, 0, 0).unwrap();
        for minute in (0..2 * 24 * 60).step_by(5) {
            let ts = base + Duration::minutes(minute);
            let day_index = minute / (24 * 60);
            let minute_of_day = minute % (24 * 60);
            let aligned = day_index == 0 || minute_of_day < 12 * 60;
            let status = if aligned { 1.0 } else { 0.0 };
            push_cmd_status(&mut batch, &site, eq_day2, ts, 1.0, status);
        }
        tsdb.upsert_samples(&batch).await.expect("samples");

        let reg = crate::timescale_product::load_reg().expect("registry");
        let rule = reg
            .rules
            .iter()
            .find(|r| r.rule_id == "CMD-1")
            .expect("CMD-1");
        let ctx = crate::effective_run_context::EffectiveRunContext {
            poll_seconds: 300.0,
            confirm_seconds: 600,
            session_override: None,
        };
        let query = crate::effective_run_context::LiveConfirmedFaultQuery {
            reg: &reg,
            rule,
            building_id: &site,
            equipment_id: eq_day2,
            window_start: Some(window_start),
            window_end: Some(window_end),
            ctx: &ctx,
        };
        let confirmed = crate::timescale_product::load_live_confirmed_fault(&tsdb, &query)
            .await
            .expect("confirmed series");
        assert!(
            !confirmed.is_empty(),
            "load_live_confirmed_fault must return data"
        );

        let commit = RunGenerationCommit {
            building_id: site.clone(),
            full_cohort: true,
            equipment: vec![RunModelEquipment {
                equipment_id: eq_day2.into(),
                equip_type: Some("ahu".into()),
            }],
            rules: vec![RunRuleFile {
                rule_id: "CMD-1".into(),
                body: json!({
                    "rule_id": "CMD-1",
                    "rows": [
                        {
                            "equipment_id": eq_day2,
                            "status": "FAULT",
                            "output_kind": "diagnostic",
                            "fault_hours": 2.0,
                            "covered_hours": 48.0,
                            "sample_rows": 100,
                            "confirm_seconds": 600.0,
                        }
                    ],
                }),
            }],
            config_fingerprint: "up03".into(),
            window_start: Some(window_start.into()),
            window_end: Some(window_end.into()),
            watermark: None,
            poll_seconds: 300.0,
            pack: json!({ "pack_version": "test-pack" }),
        };
        commit_and_persist_registry_run(&tsdb, commit)
            .await
            .expect("persist");

        let evidence: String = sqlx::query_scalar(
            "SELECT detail->'interval_persist'->>'status' FROM fdd_run WHERE site_id = $1 AND equipment_id = $2 LIMIT 1",
        )
        .bind(&site)
        .bind(eq_day2)
        .fetch_one(&pool)
        .await
        .expect("evidence");
        assert_eq!(evidence, INTERVAL_EVIDENCE_EXACT);

        let checkpoints: i64 = sqlx::query_scalar(
            "SELECT COUNT(*)::bigint FROM fdd_incremental_checkpoint WHERE site_id = $1",
        )
        .bind(&site)
        .fetch_one(&pool)
        .await
        .expect("checkpoints");
        assert!(checkpoints >= 1, "exact buckets advance checkpoint");

        let day1_fault: f64 = sqlx::query_scalar(
            r#"
            SELECT COALESCE(SUM(fault_seconds), 0)
            FROM fdd_interval_result
            WHERE site_id = $1 AND rule_id = 'CMD-1' AND equipment_id = $2
              AND bucket_start >= '2026-10-10T00:00:00Z'::timestamptz
              AND bucket_start < '2026-10-11T00:00:00Z'::timestamptz
            "#,
        )
        .bind(&site)
        .bind(eq_day2)
        .fetch_one(&pool)
        .await
        .expect("day1");
        let day2_fault: f64 = sqlx::query_scalar(
            r#"
            SELECT COALESCE(SUM(fault_seconds), 0)
            FROM fdd_interval_result
            WHERE site_id = $1 AND rule_id = 'CMD-1' AND equipment_id = $2
              AND bucket_start >= '2026-10-11T00:00:00Z'::timestamptz
              AND bucket_start < '2026-10-12T00:00:00Z'::timestamptz
            "#,
        )
        .bind(&site)
        .bind(eq_day2)
        .fetch_one(&pool)
        .await
        .expect("day2");
        assert_eq!(day1_fault, 0.0, "no fault on day 1");
        assert!(day2_fault > 0.0, "fault on day 2");

        cleanup_up03_site(&pool, &site).await;
    }

    async fn cleanup_up03_site(pool: &PgPool, site: &str) {
        let _ = sqlx::query("DELETE FROM fdd_interval_result WHERE site_id = $1")
            .bind(site)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM fdd_incremental_checkpoint WHERE site_id = $1")
            .bind(site)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM fdd_run WHERE site_id = $1")
            .bind(site)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM sample WHERE site_id = $1")
            .bind(site)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM point_map WHERE site_id = $1")
            .bind(site)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM role_map WHERE building_id = $1")
            .bind(site)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM equipment WHERE building_id = $1")
            .bind(site)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM building WHERE building_id = $1")
            .bind(site)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM site WHERE site_id = $1")
            .bind(site)
            .execute(pool)
            .await;
    }
}

#[cfg(test)]
mod up03_effective_run_context_unit {
    use serde_json::json;

    use crate::effective_run_context::EffectiveRunContext;

    #[test]
    fn row_poll_and_confirm_override_commit_defaults() {
        let row = json!({"confirm_seconds": 0.0, "poll_seconds": 60.0});
        let ctx = EffectiveRunContext::from_run_row(&row, 300.0);
        assert_eq!(ctx.confirm_seconds, 0);
        assert!((ctx.poll_seconds - 60.0).abs() < f64::EPSILON);
    }
}
