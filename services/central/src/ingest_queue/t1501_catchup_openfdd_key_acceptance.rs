//! Catch-up and gap planning read committed `point_map.openfdd_key`, not semantic ids (#1501).

use chrono::{DateTime, Duration, Utc};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use uuid::Uuid;

use super::binding_state::{device_point_coverage_for_group, last_stored_ts_for_device};
use super::gap_backfill::{plan_device_gap_backfill, DeviceGapBackfillRequest};
use crate::providers::committed_model::{IngestDeviceGroup, PlannedPoint};
use crate::providers::types::NormalizedSample;
use crate::providers::writer::project_historian_rows;

fn h(n: i64) -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-06-01T00:00:00Z")
        .unwrap()
        .with_timezone(&Utc)
        + Duration::hours(n)
}

struct KeyCase {
    site: String,
    device: String,
    provider: String,
    tenant: String,
    rev: String,
    pool: PgPool,
}

impl KeyCase {
    async fn open(tag: &str) -> Option<Self> {
        let url = std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .filter(|value| !value.trim().is_empty())?;
        let pool = PgPoolOptions::new()
            .max_connections(3)
            .connect(url.trim())
            .await
            .expect("database");
        crate::ingest_queue::test_schema::apply_ingest_queue_schema(&pool)
            .await
            .expect("schema");
        let suffix = &Uuid::new_v4().simple().to_string()[..10];
        let tenant = format!("t1501-{tag}-{suffix}");
        let site = format!("{tenant}-site");
        let provider = format!("nf:{tenant}");
        let device = format!("AHU_{suffix}");
        let rev = format!("rev-{suffix}");
        sqlx::query("INSERT INTO site (site_id) VALUES ($1) ON CONFLICT DO NOTHING")
            .bind(&site)
            .execute(&pool)
            .await
            .expect("site");
        Some(Self {
            site,
            device,
            provider,
            tenant,
            rev,
            pool,
        })
    }

    fn binding_key(&self) -> super::binding_state::DeviceBindingKey {
        super::binding_state::DeviceBindingKey {
            tenant_id: self.tenant.clone(),
            canonical_site: self.site.clone(),
            provider_instance_id: self.provider.clone(),
            device_id: self.device.clone(),
            model_revision: self.rev.clone(),
        }
    }

    async fn cleanup(&self) {
        let _ = sqlx::query("DELETE FROM sample WHERE site_id = $1")
            .bind(&self.site)
            .execute(&self.pool)
            .await;
        let _ = sqlx::query("DELETE FROM point_map WHERE site_id = $1")
            .bind(&self.site)
            .execute(&self.pool)
            .await;
    }

    fn planned_group(&self) -> IngestDeviceGroup {
        IngestDeviceGroup {
            provider_instance_id: self.provider.clone(),
            equipment_id: self.device.clone(),
            equip_type: "ahu".into(),
            points: vec![
                PlannedPoint {
                    semantic_point_id: format!("urn:openfdd:semantic:{}:sat", self.site),
                    source_point_id: "portal-sat".into(),
                    canonical_role: "sat".into(),
                    kind: None,
                    source_unit: Some("degF".into()),
                    canonical_unit: None,
                    quantity: None,
                    history_mode: None,
                    cadence_secs: None,
                    heartbeat_secs: None,
                },
                PlannedPoint {
                    semantic_point_id: format!("urn:openfdd:semantic:{}:rat", self.site),
                    source_point_id: "portal-rat".into(),
                    canonical_role: "rat".into(),
                    kind: None,
                    source_unit: Some("degF".into()),
                    canonical_unit: None,
                    quantity: None,
                    history_mode: None,
                    cadence_secs: None,
                    heartbeat_secs: None,
                },
            ],
        }
    }
}

#[tokio::test]
async fn t1501_catchup_reads_opaque_point_map_keys_not_semantic_ids() {
    let Some(case) = KeyCase::open("opaque-keys").await else {
        eprintln!("OPENFDD_TEST_DATABASE_URL unset; skipping T1501");
        return;
    };
    case.cleanup().await;
    let opaque_sat = format!("series-sat-{}", &case.site);
    let opaque_rat = format!("series-rat-{}", &case.site);
    for (portal, key, role) in [
        ("portal-sat", opaque_sat.as_str(), "sat"),
        ("portal-rat", opaque_rat.as_str(), "rat"),
    ] {
        sqlx::query(
            "INSERT INTO point_map (site_id, openfdd_key, haystack_id, role, equipment_id, portal_point_id, referenced)
             VALUES ($1, $2, $3, $4, $5, $3, true)",
        )
        .bind(&case.site)
        .bind(key)
        .bind(portal)
        .bind(role)
        .bind(&case.device)
        .execute(&case.pool)
        .await
        .expect("point_map");
    }
    let sample = NormalizedSample {
        building_id: case.site.clone(),
        provider_instance_id: case.provider.clone(),
        equipment_id: case.device.clone(),
        provider_point_id: "portal-sat".into(),
        role: "sat".into(),
        equip_type: Some("ahu".into()),
        ts: h(2) + Duration::minutes(8),
        val: 72.0,
        unit: Some("degF".into()),
        source_quality: None,
        attrs: serde_json::Map::new(),
    };
    let rows = project_historian_rows(&case.site, &[sample]).expect("project");
    assert_eq!(rows.len(), 1);
    sqlx::query(
        "INSERT INTO sample (ts, site_id, openfdd_key, val, unit, quality)
         VALUES ($1, $2, $3, $4, 'degF', 'good')",
    )
    .bind(rows[0].ts)
    .bind(&case.site)
    .bind(&opaque_sat)
    .bind(rows[0].val)
    .execute(&case.pool)
    .await
    .expect("sample");
    let group = case.planned_group();
    let coverage = device_point_coverage_for_group(&case.pool, &case.site, &group)
        .await
        .expect("coverage");
    assert_eq!(coverage[0].openfdd_key, opaque_sat);
    let keys: Vec<String> = coverage.iter().map(|row| row.openfdd_key.clone()).collect();
    let last = last_stored_ts_for_device(&case.pool, &case.site, &keys)
        .await
        .expect("last");
    assert!(last.is_some(), "semantic ids must not hide stored samples");
    let (plan, jobs) = plan_device_gap_backfill(
        &case.pool,
        DeviceGapBackfillRequest {
            key: case.binding_key(),
            group: &group,
            range_start: h(0),
            range_end: h(4),
            force: false,
            now: Utc::now(),
        },
    )
    .await
    .expect("plan");
    assert!(
        plan.counts.planned > 0,
        "missing second point should plan backfill: {plan:?}"
    );
    assert!(
        jobs.iter()
            .any(|job| job.logical_window_start <= h(2) && job.logical_window_end > h(2)),
        "{jobs:?}"
    );
    case.cleanup().await;
}
