//! NF portal inventory sync against PostgreSQL with a repo portal fixture.
//!
//! Runs when `OPENFDD_TEST_DATABASE_URL` is set. A local listener plays the
//! portal: token, then `POST /api/v1/point/query` with the v1 or v2 inventory.
//! Schema changes are additive and purge is limited to this fixture's site.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use chrono::{TimeZone, Utc};
use fdd_tsdb::{PurgeTarget, Tsdb, UpsertBatch};
use open_fdd_edge_prototype::csv_ingest::{haystack_sparql_bindings, model_overlay};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;
use tokio::sync::Mutex;

use crate::providers::http_policy::HttpLimits;
use crate::providers::inventory_sync::{apply_to_stores, InventorySnapshot};
use crate::providers::nf::NfPortalDriver;
use crate::providers::types::NormalizedSample;
use crate::providers::writer::project_historian_rows;

const SITE: &str = "w7n-portal-inv";
const SOURCE: &str = "nf:w7n-portal-inv";
const V1: &str = include_str!("providers/fixtures/nf_inventory_v1.json");
const V2: &str = include_str!("providers/fixtures/nf_inventory_v2.json");
const TOKEN: &str = r#"{"accessToken":"tok-w7n","expiresIn":3600}"#;
const PORTAL_SCHEMA: &str = include_str!("../../../sql/schema/05_portal_inventory.sql");

fn test_database_url() -> Option<String> {
    std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

pub(crate) async fn apply_schema(pool: &PgPool) {
    for statement in [
        "CREATE TABLE IF NOT EXISTS site (
            site_id text PRIMARY KEY,
            dis text,
            timezone text NOT NULL DEFAULT 'UTC',
            enabled boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now()
        )",
        "CREATE TABLE IF NOT EXISTS building (
            building_id text PRIMARY KEY,
            site_id text REFERENCES site(site_id),
            dis text,
            timezone text NOT NULL DEFAULT 'UTC',
            created_at timestamptz NOT NULL DEFAULT now()
        )",
        "CREATE TABLE IF NOT EXISTS equipment (
            building_id text NOT NULL REFERENCES building(building_id),
            equipment_id text NOT NULL,
            equip_type text,
            parent_equipment_id text,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (building_id, equipment_id)
        )",
        "CREATE TABLE IF NOT EXISTS sample (
            ts timestamptz NOT NULL,
            site_id text NOT NULL,
            openfdd_key text NOT NULL,
            haystack_id text,
            val double precision,
            unit text,
            quality text,
            PRIMARY KEY (site_id, openfdd_key, ts)
        )",
        "CREATE TABLE IF NOT EXISTS role_map (
            building_id text NOT NULL,
            equipment_id text NOT NULL,
            openfdd_key text NOT NULL,
            role text NOT NULL,
            unit text,
            PRIMARY KEY (building_id, equipment_id, openfdd_key)
        )",
        "CREATE TABLE IF NOT EXISTS point_map (
            site_id text NOT NULL REFERENCES site(site_id),
            openfdd_key text NOT NULL,
            haystack_id text NOT NULL,
            role text,
            unit text,
            equipment_id text,
            PRIMARY KEY (site_id, openfdd_key)
        )",
        "ALTER TABLE sample ADD COLUMN IF NOT EXISTS haystack_id text",
        "ALTER TABLE sample ADD COLUMN IF NOT EXISTS unit text",
        "ALTER TABLE sample ADD COLUMN IF NOT EXISTS quality text",
    ] {
        crate::test_ddl::execute_idempotent_ddl(pool, statement).await;
    }
    for statement in PORTAL_SCHEMA
        .split(';')
        .map(|s| {
            s.lines()
                .filter(|l| !l.trim_start().starts_with("--"))
                .collect::<Vec<_>>()
                .join("\n")
        })
        .filter(|s| !s.trim().is_empty())
    {
        crate::test_ddl::execute_idempotent_ddl(pool, &statement).await;
    }
}

async fn purge_site(pool: &PgPool) {
    for sql in [
        "DELETE FROM sample WHERE site_id = $1",
        "DELETE FROM role_map WHERE building_id = $1",
        "DELETE FROM point_map WHERE site_id = $1",
        "DELETE FROM equipment WHERE building_id = $1",
    ] {
        sqlx::query(sql)
            .bind(SITE)
            .execute(pool)
            .await
            .expect("purge fixture site");
    }
}

async fn read_request(sock: &mut tokio::net::TcpStream) -> String {
    let mut buf = vec![0u8; 8192];
    let mut got = Vec::new();
    loop {
        let n = tokio::time::timeout(Duration::from_secs(2), sock.read(&mut buf))
            .await
            .expect("read timeout")
            .expect("read");
        if n == 0 {
            break;
        }
        got.extend_from_slice(&buf[..n]);
        if got.windows(4).any(|w| w == b"\r\n\r\n") {
            break;
        }
    }
    String::from_utf8_lossy(&got).to_string()
}

/// Local portal. `inventory` selects the body served to the point query.
struct FixturePortal {
    port: u16,
    inventory: Arc<Mutex<&'static str>>,
    requests: Arc<Mutex<Vec<String>>>,
    served: Arc<AtomicUsize>,
}

impl FixturePortal {
    async fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
        let port = listener.local_addr().expect("addr").port();
        let inventory = Arc::new(Mutex::new(V1));
        let requests = Arc::new(Mutex::new(Vec::new()));
        let served = Arc::new(AtomicUsize::new(0));
        let inv = Arc::clone(&inventory);
        let rec = Arc::clone(&requests);
        let count = Arc::clone(&served);
        tokio::spawn(async move {
            while let Ok((mut sock, _)) = listener.accept().await {
                let req = read_request(&mut sock).await;
                let line = req.lines().next().unwrap_or_default().to_string();
                rec.lock().await.push(line.clone());
                let body = if line.starts_with("POST /api/v1/auth/token") {
                    TOKEN.to_string()
                } else if line.starts_with("POST /api/v1/point/query") {
                    count.fetch_add(1, Ordering::SeqCst);
                    inv.lock().await.to_string()
                } else {
                    r#"{"error":"not_found"}"#.to_string()
                };
                let payload = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                let _ = sock.write_all(payload.as_bytes()).await;
            }
        });
        Self {
            port,
            inventory,
            requests,
            served,
        }
    }

    async fn serve(&self, body: &'static str) {
        *self.inventory.lock().await = body;
    }

    async fn poll(&self) -> InventorySnapshot {
        let mut driver = NfPortalDriver::new(
            SOURCE,
            format!("http://127.0.0.1:{}", self.port),
            Some("fixture-id".into()),
            Some("fixture-secret".into()),
            false,
            HttpLimits::default(),
        )
        .expect("driver");
        driver.authenticate().await.expect("token");
        driver.query_inventory(500).await.expect("inventory")
    }
}

/// One hour of 15-minute samples for every tagged inventory point.
fn history(snapshot: &InventorySnapshot, offset: f64) -> UpsertBatch {
    let start = Utc
        .with_ymd_and_hms(2026, 10, 1, 0, 0, 0)
        .single()
        .expect("start");
    let mut samples = Vec::new();
    for (i, pt) in snapshot.points.iter().enumerate() {
        for step in 0..4 {
            samples.push(NormalizedSample {
                building_id: SITE.into(),
                provider_instance_id: SOURCE.into(),
                equipment_id: pt.equipment_id.clone(),
                provider_point_id: pt.portal_point_id.clone(),
                role: pt.role.clone(),
                equip_type: pt.equip_type.clone(),
                ts: start + chrono::Duration::minutes(15 * step),
                val: offset + (i as f64) * 10.0 + step as f64,
                unit: pt.unit.clone(),
                source_quality: Some("good".into()),
                attrs: serde_json::Map::new(),
            });
        }
    }
    let mut batch = UpsertBatch::default();
    for row in project_historian_rows(SITE, &samples).expect("projection") {
        batch.push(row);
    }
    batch
}

async fn count(pool: &PgPool, sql: &str) -> i64 {
    sqlx::query_scalar(sql)
        .bind(SITE)
        .fetch_one(pool)
        .await
        .expect(sql)
}

fn ask(root: &std::path::Path, query: &str) -> bool {
    let overlay = model_overlay::load_ttl(root).expect("overlay");
    let out = haystack_sparql_bindings::execute_readonly_on_overlay(SITE, query, &overlay)
        .expect("sparql");
    out["boolean"].as_bool().expect("ask")
}

#[tokio::test]
async fn portal_repoll_is_idempotent_and_removed_equipment_keeps_samples_until_purge() {
    let Some(url) = test_database_url() else {
        return;
    };
    let pool = PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .expect("portal inventory postgres");
    apply_schema(&pool).await;
    purge_site(&pool).await;
    let tsdb = Tsdb::from_pool(pool.clone());
    let dir = tempfile::tempdir().expect("tempdir");
    let root = dir.path().join(SITE);
    let portal = FixturePortal::start().await;

    // First poll: inventory then one hour of history.
    let v1 = portal.poll().await;
    let first = apply_to_stores(Some(&tsdb), &root, SITE, SOURCE, &v1).await;
    assert!(first.errors.is_empty(), "{:?}", first.errors);
    let first_hist = first.historian.expect("historian");
    assert_eq!(first_hist.referenced, 5);
    let batch = history(&v1, 50.0);
    let stats = tsdb
        .upsert_samples_stats(&batch)
        .await
        .expect("first window");
    assert_eq!(stats.inserted, 20);
    let points_after_first =
        count(&pool, "SELECT count(*) FROM point_map WHERE site_id = $1").await;
    assert_eq!(points_after_first, 5);
    let ttl_after_first = model_overlay::load_ttl(&root).expect("ttl");

    // Re-poll: same inventory, same window (a retry after a crash past commit).
    let again = portal.poll().await;
    let second = apply_to_stores(Some(&tsdb), &root, SITE, SOURCE, &again).await;
    assert!(second.errors.is_empty(), "{:?}", second.errors);
    assert_eq!(second.historian.expect("historian").keys, first_hist.keys);
    assert!(!second.rdf.expect("rdf").changed);
    assert_eq!(
        model_overlay::load_ttl(&root).expect("ttl"),
        ttl_after_first
    );
    let retry = tsdb
        .upsert_samples_stats(&batch)
        .await
        .expect("retry window");
    assert_eq!(
        (retry.inserted, retry.updated, retry.unchanged),
        (0, 0, 20),
        "retried window must be a duplicate, not new data"
    );
    assert_eq!(
        count(&pool, "SELECT count(*) FROM sample WHERE site_id = $1").await,
        20
    );
    assert_eq!(
        count(&pool, "SELECT count(*) FROM point_map WHERE site_id = $1").await,
        points_after_first
    );
    assert_eq!(
        count(
            &pool,
            "SELECT count(*) FROM (SELECT portal_point_id FROM point_map WHERE site_id = $1 \
             GROUP BY portal_point_id HAVING count(*) > 1) d"
        )
        .await,
        0
    );

    // A corrected value at the same timestamp updates in place.
    let mut corrected = UpsertBatch::default();
    let mut row = batch.rows[0].clone();
    row.val = row.val.map(|v| v + 0.5);
    corrected.push(row.clone());
    corrected.push(row);
    let fixed = tsdb
        .upsert_samples_stats(&corrected)
        .await
        .expect("correction");
    assert_eq!((fixed.inserted, fixed.updated, fixed.unchanged), (0, 1, 1));
    assert_eq!(
        count(&pool, "SELECT count(*) FROM sample WHERE site_id = $1").await,
        20
    );

    assert!(tsdb
        .orphaned_points(SITE)
        .await
        .expect("orphans")
        .is_empty());

    // VAV_1 leaves the portal inventory.
    portal.serve(V2).await;
    let v2 = portal.poll().await;
    let third = apply_to_stores(Some(&tsdb), &root, SITE, SOURCE, &v2).await;
    assert!(third.errors.is_empty(), "{:?}", third.errors);
    assert_eq!(third.historian.expect("historian").newly_unreferenced, 2);
    assert_eq!(
        third.rdf.expect("rdf").equipment_deleted,
        vec!["VAV_1".to_string()]
    );
    assert!(!ask(&root, r#"ASK { ?s ofdd:equipmentId "VAV_1" }"#));
    assert!(ask(&root, r#"ASK { ?s ofdd:equipmentId "AHU_1" }"#));
    assert_eq!(
        count(&pool, "SELECT count(*) FROM sample WHERE site_id = $1").await,
        20,
        "inventory sync deleted samples"
    );
    assert_eq!(
        count(&pool, "SELECT count(*) FROM point_map WHERE site_id = $1").await,
        5,
        "inventory sync deleted point_map rows"
    );
    let orphans = tsdb.orphaned_points(SITE).await.expect("orphans");
    assert_eq!(orphans.len(), 2);
    assert!(orphans
        .iter()
        .all(|p| p.equipment_id.as_deref() == Some("VAV_1") && !p.referenced));

    // Purge removes only VAV_1's keys.
    let report = tsdb
        .purge_historian(SITE, PurgeTarget::Equipment("VAV_1"))
        .await
        .expect("purge");
    assert_eq!(report.keys.len(), 2);
    assert_eq!(report.samples_deleted, 8);
    assert_eq!(report.point_map_deleted, 2);
    assert_eq!(
        count(&pool, "SELECT count(*) FROM sample WHERE site_id = $1").await,
        12
    );
    assert_eq!(
        count(
            &pool,
            "SELECT count(*) FROM point_map WHERE site_id = $1 AND equipment_id = 'AHU_1'"
        )
        .await,
        3
    );
    assert!(tsdb
        .orphaned_points(SITE)
        .await
        .expect("orphans")
        .is_empty());

    let static_key = first_hist
        .keys
        .get("6a1f0c2a-0001-4000-8000-00000000a002")
        .expect("duct static key")
        .clone();
    let one = tsdb
        .purge_historian(SITE, PurgeTarget::Point(&static_key))
        .await
        .expect("purge point");
    assert_eq!((one.samples_deleted, one.point_map_deleted), (4, 1));
    assert_eq!(
        count(&pool, "SELECT count(*) FROM sample WHERE site_id = $1").await,
        8
    );

    let requests = portal.requests.lock().await.clone();
    assert_eq!(portal.served.load(Ordering::SeqCst), 3);
    assert!(
        requests
            .iter()
            .all(|r| !r.starts_with("POST /api/v1/point/data")),
        "POST on the history path is a portal write: {requests:?}"
    );
    purge_site(&pool).await;
}
