//! T1439-1: OAT-METEO interval as-of join preserves assessable/raw masks (Postgres).

use chrono::{Duration, TimeZone, Utc};
use fdd_tsdb::{SampleRow, UpsertBatch};
use sqlx::Row;

use super::oat_meteo_t1404_test::{
    apply_schema, bind_point, pool, purge, seed_site, upsert_samples,
};
use super::*;

const LEGACY_JOINED: &str = r"joined AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    h.oa_t,
    (
      SELECT d.timestamp_utc
      FROM web_dedup d
      WHERE d.timestamp_utc <= h.timestamp_utc
      ORDER BY d.timestamp_utc DESC
      LIMIT 1
    ) AS ref_ts,
    (
      SELECT d.ref_val
      FROM web_dedup d
      WHERE d.timestamp_utc <= h.timestamp_utc
      ORDER BY d.timestamp_utc DESC
      LIMIT 1
    ) AS ref_oa_t,
    CASE
      WHEN h.oa_t IS NULL THEN false
      WHEN (
        SELECT d.ref_val
        FROM web_dedup d
        WHERE d.timestamp_utc <= h.timestamp_utc
        ORDER BY d.timestamp_utc DESC
        LIMIT 1
      ) IS NULL THEN false
      WHEN EXTRACT(EPOCH FROM (
        h.timestamp_utc - (
          SELECT d.timestamp_utc
          FROM web_dedup d
          WHERE d.timestamp_utc <= h.timestamp_utc
          ORDER BY d.timestamp_utc DESC
          LIMIT 1
        )
      )) > {{WEB_ASOF_BOUND_SECONDS}}
      THEN false
      ELSE true
    END AS assessable
  FROM history h
),";

fn render_mask_query(web_asof_bound_seconds: f64, legacy_joined: bool) -> String {
    let product =
        include_str!("../../../sql/fdd/postgres/rules/oat_meteo_fault.sql").replace("\r\n", "\n");
    let web_intervals = product
        .find("web_intervals AS (")
        .expect("web_intervals CTE");
    let base_boundary = product.find("),\nbase AS (").expect("base boundary");
    let elapsed = product
        .find("),\nelapsed_hold AS (")
        .expect("elapsed_hold CTE");
    let head = &product[0..web_intervals];
    let joined = if legacy_joined {
        LEGACY_JOINED.to_string()
    } else {
        product[web_intervals..base_boundary + 2].to_string()
    };
    let base_body = &product[base_boundary + "),\nbase AS (".len()..elapsed];
    let mut body = format!("{head}{joined}\nbase AS ({base_body})");
    body = body.replace(
        "{{WEB_ASOF_BOUND_SECONDS}}",
        &format!("{web_asof_bound_seconds}"),
    );
    body = body.replace("{{OAT_ERR}}", "2.777778");
    body = body.replace("{{CONFIRM_SECONDS}}", "900");
    body = body.replace("{{MAX_GAP_HOURS}}", "1.0");
    format!(
        "{body} \
         SELECT md5(string_agg(row_sig, E'\\n' ORDER BY equipment_id, timestamp_utc)) AS digest \
         FROM ( \
           SELECT equipment_id, timestamp_utc, \
             equipment_id || '|' || timestamp_utc::text || '|' || assessable::text \
             || '|' || COALESCE(raw_fault::text, 'null') AS row_sig \
           FROM base \
         ) s"
    )
}

async fn seed_mask_fixture(pool: &sqlx::PgPool, site: &str) {
    purge(pool, site).await;
    seed_site(pool, site).await;
    bind_point(pool, site, "WX", "web_oa_t", "WX.web_oa_t", "pt-web").await;
    bind_point(pool, site, "AHU_1", "oa_t", "AHU_1.oa_t", "pt-oa").await;
    let mut batch = UpsertBatch::default();
    let t0 = Utc.with_ymd_and_hms(2026, 6, 1, 0, 0, 0).unwrap();
    for m in (0..240).step_by(5) {
        let ts = t0 + Duration::minutes(m);
        let mut row = SampleRow::new(
            ts,
            site,
            String::from("AHU_1.oa_t"),
            Some(12.0 + (m % 3) as f64),
        );
        row.equipment_id = Some(String::from("AHU_1"));
        row.role = Some(String::from("oa_t"));
        row.source_unit = Some(String::from("degC"));
        row.quantity = Some(String::from("absolute_temperature"));
        batch.push(row);
    }
    for m in [0, 20, 25, 40, 55, 80, 120, 121, 122, 200] {
        let ts = t0 + Duration::minutes(m);
        let mut row = SampleRow::new(ts, site, String::from("WX.web_oa_t"), Some(10.0));
        row.equipment_id = Some(String::from("WX"));
        row.role = Some(String::from("web_oa_t"));
        row.source_unit = Some(String::from("degC"));
        row.quantity = Some(String::from("absolute_temperature"));
        batch.push(row);
    }
    upsert_samples(pool, batch).await;
}

async fn mask_digest(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    legacy: bool,
    bound: f64,
) -> String {
    let sql = render_mask_query(bound, legacy);
    let row = sqlx::query(&sql)
        .fetch_one(&mut **tx)
        .await
        .expect("mask digest");
    row.try_get::<String, _>("digest").expect("digest")
}

#[tokio::test]
async fn t1439_oat_meteo_asof_masks_match_legacy_reference() {
    let Some(pool) = pool().await else {
        panic!("OPENFDD_TEST_DATABASE_URL required for T1439-1");
    };
    apply_schema(&pool).await;
    let site = format!("t1439{}", uuid::Uuid::new_v4().simple());
    seed_mask_fixture(&pool, &site).await;

    let reg = load_reg().expect("registry");
    let rule = reg
        .rules
        .iter()
        .find(|r| r.rule_id == "OAT-METEO")
        .expect("rule");
    let roles = rule_history_roles(rule);
    let mut tx = pool.begin().await.expect("tx");
    ensure_history_table(&mut tx, &roles)
        .await
        .expect("history");
    fill_history_for_equipment(&mut tx, site.as_str(), "AHU_1", &roles, None, None, None)
        .await
        .expect("fill");

    for bound in [1499.0, 1500.0, 1501.0] {
        let legacy = mask_digest(&mut tx, true, bound).await;
        let product = mask_digest(&mut tx, false, bound).await;
        assert_eq!(
            legacy, product,
            "assessable/raw mask mismatch at WEB_ASOF_BOUND_SECONDS={bound}"
        );
    }
    let _ = tx.rollback().await;
    purge(&pool, &site).await;
}
