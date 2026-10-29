//! The one Timescale sample writer.
//!
//! Every product telemetry write reaches `sample` through this module: NF
//! portal polls and CSV append / remap (`Tsdb::upsert_samples_stats`), full CSV
//! package promotion (`promote_stage`), and the starter seed. One conflict rule
//! applies to all of them, so a replayed sample is left unchanged and a changed
//! value is overwritten in place. No other product code inserts into `sample`.
//!
//! A real insert, same-timestamp correction, or delete records its changed
//! ranges and advances the site data revision in the same transaction.
//! An identical replay does neither. Change detection is the row returned by
//! the write, not a count, a sum, or `max(ts)`.

use std::collections::HashMap;

use chrono::{DateTime, Utc};
use sqlx::{Postgres, Row, Transaction};

use crate::client::SampleUpsertStats;
use crate::revision::{fold_bound, record_bounds, ChangeBounds, ChangeKind};

macro_rules! sample_insert_columns {
    () => {
        "INSERT INTO sample (ts, site_id, openfdd_key, haystack_id, val, unit, quality) "
    };
}

macro_rules! sample_on_conflict {
    () => {
        r#"
        ON CONFLICT (site_id, openfdd_key, ts) DO UPDATE SET
          val = EXCLUDED.val,
          unit = COALESCE(EXCLUDED.unit, sample.unit),
          quality = COALESCE(EXCLUDED.quality, sample.quality),
          haystack_id = COALESCE(EXCLUDED.haystack_id, sample.haystack_id)
        WHERE (sample.val, sample.unit, sample.quality, sample.haystack_id)
          IS DISTINCT FROM (
            EXCLUDED.val,
            COALESCE(EXCLUDED.unit, sample.unit),
            COALESCE(EXCLUDED.quality, sample.quality),
            COALESCE(EXCLUDED.haystack_id, sample.haystack_id)
          )
        "#
    };
}

/// Batch upsert for resolved rows. One-writer fixtures match `current_query()`
/// on `sample` against this text, so it is part of the writer contract.
pub const WRITE_ROWS_SQL: &str = concat!(
    sample_insert_columns!(),
    "SELECT * FROM UNNEST($1::timestamptz[], $2::text[], $3::text[], $4::text[], \
     $5::float8[], $6::text[], $7::text[])",
    sample_on_conflict!(),
    "RETURNING site_id, openfdd_key, ts, (xmax = 0) AS inserted"
);

/// Staged CSV package promote. Same contract as [`WRITE_ROWS_SQL`].
pub const PROMOTE_STAGE_SQL: &str = concat!(
    sample_insert_columns!(),
    "SELECT ts, site_id, openfdd_key, haystack_id, val, unit, quality \
     FROM sample_import_stage WHERE import_id = $1 AND site_id = $2",
    sample_on_conflict!(),
    "RETURNING site_id, openfdd_key, ts"
);

/// Remove every sample at one site. The returned rows advance the data revision.
pub const DELETE_SITE_SQL: &str =
    "DELETE FROM sample WHERE site_id = $1 RETURNING site_id, openfdd_key, ts";

/// Remove exact series keys at one site.
pub const DELETE_KEYS_SQL: &str = "\
DELETE FROM sample
WHERE site_id = $1 AND openfdd_key = ANY($2)
RETURNING site_id, openfdd_key, ts";

/// Remove exact samples. Each triple is one `(site_id, openfdd_key, ts)`.
pub const DELETE_SAMPLES_SQL: &str = "\
DELETE FROM sample AS s
USING (
  SELECT * FROM UNNEST($1::text[], $2::text[], $3::timestamptz[])
    AS d(site_id, openfdd_key, ts)
) AS d
WHERE s.site_id = d.site_id
  AND s.openfdd_key = d.openfdd_key
  AND s.ts = d.ts
RETURNING s.site_id, s.openfdd_key, s.ts";

/// Remove site samples that this staged import does not replace.
pub const DELETE_OUTSIDE_STAGE_SQL: &str = "\
DELETE FROM sample AS s
WHERE s.site_id = $2
  AND NOT EXISTS (
    SELECT 1 FROM sample_import_stage AS st
    WHERE st.import_id = $1
      AND st.site_id = s.site_id
      AND st.openfdd_key = s.openfdd_key
      AND st.ts = s.ts
  )
RETURNING s.site_id, s.openfdd_key, s.ts";

/// Rows per statement. Bounds the bind arrays sent in one round trip.
const CHUNK_ROWS: usize = 5_000;

/// One resolved sample. `openfdd_key` is final: portal keys are resolved first.
#[derive(Debug, Clone, Copy)]
pub struct SampleWrite<'a> {
    pub ts: DateTime<Utc>,
    pub site_id: &'a str,
    pub openfdd_key: &'a str,
    pub haystack_id: Option<&'a str>,
    pub val: Option<f64>,
    pub unit: Option<&'a str>,
    pub quality: Option<&'a str>,
}

/// Write resolved samples inside the caller's transaction.
///
/// Rows that repeat a `(site_id, openfdd_key, ts)` key in the same call keep
/// the last value; the earlier copies count as unchanged.
pub async fn write_samples(
    tx: &mut Transaction<'_, Postgres>,
    rows: &[SampleWrite<'_>],
) -> Result<SampleUpsertStats, sqlx::Error> {
    let mut stats = SampleUpsertStats::default();
    let mut last_index: HashMap<(&str, &str, DateTime<Utc>), usize> =
        HashMap::with_capacity(rows.len());
    for (idx, row) in rows.iter().enumerate() {
        if last_index
            .insert((row.site_id, row.openfdd_key, row.ts), idx)
            .is_some()
        {
            stats.unchanged += 1;
        }
    }
    let mut unique: Vec<usize> = last_index.into_values().collect();
    unique.sort_unstable();

    let mut bounds = ChangeBounds::new();
    for chunk in unique.chunks(CHUNK_ROWS) {
        let mut ts = Vec::with_capacity(chunk.len());
        let mut sites = Vec::with_capacity(chunk.len());
        let mut keys = Vec::with_capacity(chunk.len());
        let mut haystack = Vec::with_capacity(chunk.len());
        let mut vals = Vec::with_capacity(chunk.len());
        let mut units = Vec::with_capacity(chunk.len());
        let mut qualities = Vec::with_capacity(chunk.len());
        for &idx in chunk {
            let row = &rows[idx];
            ts.push(row.ts);
            sites.push(row.site_id);
            keys.push(row.openfdd_key);
            haystack.push(row.haystack_id);
            vals.push(row.val);
            units.push(row.unit);
            qualities.push(row.quality);
        }
        let written = sqlx::query(WRITE_ROWS_SQL)
            .bind(&ts)
            .bind(&sites)
            .bind(&keys)
            .bind(&haystack)
            .bind(&vals)
            .bind(&units)
            .bind(&qualities)
            .fetch_all(&mut **tx)
            .await?;
        let mut inserted = 0u64;
        for row in &written {
            let is_insert: bool = row.try_get("inserted")?;
            if is_insert {
                inserted += 1;
            }
            let site_id: String = row.try_get("site_id")?;
            let openfdd_key: String = row.try_get("openfdd_key")?;
            let changed_at: DateTime<Utc> = row.try_get("ts")?;
            fold_bound(&mut bounds, &site_id, &openfdd_key, changed_at);
        }
        let returned = written.len() as u64;
        stats.inserted += inserted;
        stats.updated += returned - inserted;
        stats.unchanged += chunk.len() as u64 - returned;
    }
    record_bounds(tx, ChangeKind::Upsert, &bounds).await?;
    Ok(stats)
}

/// Promote one staged CSV package import into `sample` with the shared rule.
///
/// The count is rows inserted or corrected. An identical staged row is not counted.
pub async fn promote_stage(
    tx: &mut Transaction<'_, Postgres>,
    import_id: uuid::Uuid,
    site_id: &str,
) -> Result<u64, sqlx::Error> {
    let written = sqlx::query(PROMOTE_STAGE_SQL)
        .bind(import_id)
        .bind(site_id)
        .fetch_all(&mut **tx)
        .await?;
    record_returned(tx, ChangeKind::Upsert, &written).await?;
    Ok(written.len() as u64)
}

/// One sample to remove. The key and timestamp are exact.
#[derive(Debug, Clone, Copy)]
pub struct SampleDelete<'a> {
    pub site_id: &'a str,
    pub openfdd_key: &'a str,
    pub ts: DateTime<Utc>,
}

/// Which samples to remove. An empty key list or sample list removes nothing.
#[derive(Debug, Clone, Copy)]
pub enum DeleteScope<'a> {
    Site(&'a str),
    Keys {
        site_id: &'a str,
        openfdd_keys: &'a [&'a str],
    },
    Samples(&'a [SampleDelete<'a>]),
}

/// Remove samples and, when a row was stored, record that span in this transaction.
pub async fn delete_samples(
    tx: &mut Transaction<'_, Postgres>,
    scope: DeleteScope<'_>,
) -> Result<u64, sqlx::Error> {
    let written = match scope {
        DeleteScope::Site(site_id) => {
            sqlx::query(DELETE_SITE_SQL)
                .bind(site_id)
                .fetch_all(&mut **tx)
                .await?
        }
        DeleteScope::Keys {
            site_id,
            openfdd_keys,
        } => {
            if openfdd_keys.is_empty() {
                return Ok(0);
            }
            sqlx::query(DELETE_KEYS_SQL)
                .bind(site_id)
                .bind(openfdd_keys)
                .fetch_all(&mut **tx)
                .await?
        }
        DeleteScope::Samples(samples) => {
            if samples.is_empty() {
                return Ok(0);
            }
            let mut sites = Vec::with_capacity(samples.len());
            let mut keys = Vec::with_capacity(samples.len());
            let mut stamps = Vec::with_capacity(samples.len());
            for sample in samples {
                sites.push(sample.site_id);
                keys.push(sample.openfdd_key);
                stamps.push(sample.ts);
            }
            sqlx::query(DELETE_SAMPLES_SQL)
                .bind(&sites)
                .bind(&keys)
                .bind(&stamps)
                .fetch_all(&mut **tx)
                .await?
        }
    };
    record_returned(tx, ChangeKind::Delete, &written).await?;
    Ok(written.len() as u64)
}

/// Drop stored samples this staged import does not contain, and record those spans.
pub async fn delete_samples_outside_stage(
    tx: &mut Transaction<'_, Postgres>,
    import_id: uuid::Uuid,
    site_id: &str,
) -> Result<u64, sqlx::Error> {
    let written = sqlx::query(DELETE_OUTSIDE_STAGE_SQL)
        .bind(import_id)
        .bind(site_id)
        .fetch_all(&mut **tx)
        .await?;
    record_returned(tx, ChangeKind::Delete, &written).await?;
    Ok(written.len() as u64)
}

async fn record_returned(
    tx: &mut Transaction<'_, Postgres>,
    kind: ChangeKind,
    written: &[sqlx::postgres::PgRow],
) -> Result<(), sqlx::Error> {
    let mut bounds = ChangeBounds::new();
    for row in written {
        let site_id: String = row.try_get("site_id")?;
        let openfdd_key: String = row.try_get("openfdd_key")?;
        let changed_at: DateTime<Utc> = row.try_get("ts")?;
        fold_bound(&mut bounds, &site_id, &openfdd_key, changed_at);
    }
    record_bounds(tx, kind, &bounds).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn both_statements_share_one_conflict_rule() {
        let rule = sample_on_conflict!();
        assert!(WRITE_ROWS_SQL.contains(rule));
        assert!(PROMOTE_STAGE_SQL.contains(rule));
        assert!(WRITE_ROWS_SQL.starts_with(sample_insert_columns!()));
        assert!(PROMOTE_STAGE_SQL.starts_with(sample_insert_columns!()));
        assert!(rule.contains("IS DISTINCT FROM"));
        assert!(WRITE_ROWS_SQL.contains("RETURNING site_id, openfdd_key, ts"));
        assert!(PROMOTE_STAGE_SQL.contains("RETURNING site_id, openfdd_key, ts"));
    }

    /// Runs when `OPENFDD_TEST_DATABASE_URL` is set; otherwise returns early.
    #[tokio::test]
    async fn replay_is_unchanged_and_promote_follows_the_same_rule() {
        let Some(url) = std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
        else {
            return;
        };
        let pool = sqlx::postgres::PgPoolOptions::new()
            .max_connections(1)
            .connect(&url)
            .await
            .unwrap();
        for ddl in [
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
            "ALTER TABLE sample ADD COLUMN IF NOT EXISTS haystack_id text",
            "ALTER TABLE sample ADD COLUMN IF NOT EXISTS unit text",
            "ALTER TABLE sample ADD COLUMN IF NOT EXISTS quality text",
            "CREATE TABLE IF NOT EXISTS sample_import_stage (
                import_id uuid NOT NULL,
                ts timestamptz NOT NULL,
                site_id text NOT NULL,
                openfdd_key text NOT NULL,
                haystack_id text,
                val double precision,
                PRIMARY KEY (import_id, site_id, openfdd_key, ts)
            )",
            "ALTER TABLE sample_import_stage ADD COLUMN IF NOT EXISTS unit text",
            "ALTER TABLE sample_import_stage ADD COLUMN IF NOT EXISTS quality text",
        ] {
            // Concurrent fixtures may race on the catalog; the table exists either way.
            if let Err(err) = sqlx::query(ddl).execute(&pool).await {
                assert!(
                    err.as_database_error()
                        .and_then(|db| db.code())
                        .is_some_and(|code| code == "23505" || code == "42P07"),
                    "{ddl}: {err}"
                );
            }
        }
        let site = format!("wp2c-writer-{}", uuid::Uuid::new_v4().simple());
        let ts = chrono::DateTime::parse_from_rfc3339("2024-03-01T00:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let rows = [
            SampleWrite {
                ts,
                site_id: &site,
                openfdd_key: "AHU_1.sat",
                haystack_id: Some("p-sat"),
                val: Some(55.0),
                unit: Some("degF"),
                quality: None,
            },
            SampleWrite {
                ts,
                site_id: &site,
                openfdd_key: "AHU_1.rat",
                haystack_id: None,
                val: Some(72.0),
                unit: None,
                quality: None,
            },
        ];

        let mut tx = pool.begin().await.unwrap();
        let first = write_samples(&mut tx, &rows).await.unwrap();
        tx.commit().await.unwrap();
        assert_eq!((first.inserted, first.updated, first.unchanged), (2, 0, 0));

        let mut tx = pool.begin().await.unwrap();
        let replay = write_samples(&mut tx, &rows).await.unwrap();
        tx.commit().await.unwrap();
        assert_eq!(
            (replay.inserted, replay.updated, replay.unchanged),
            (0, 0, 2)
        );

        // A staged import of the same value without unit keeps the stored unit.
        let import_id = uuid::Uuid::new_v4();
        sqlx::query(
            "INSERT INTO sample_import_stage (import_id, ts, site_id, openfdd_key, val)
             VALUES ($1, $2, $3, 'AHU_1.sat', 55.0), ($1, $2, $3, 'AHU_1.rat', 73.0)",
        )
        .bind(import_id)
        .bind(ts)
        .bind(&site)
        .execute(&pool)
        .await
        .unwrap();
        let mut tx = pool.begin().await.unwrap();
        let promoted = promote_stage(&mut tx, import_id, &site).await.unwrap();
        tx.commit().await.unwrap();
        assert_eq!(promoted, 1, "only the changed value is rewritten");

        let stored: Vec<(String, Option<f64>, Option<String>)> = sqlx::query_as(
            "SELECT openfdd_key, val, unit FROM sample WHERE site_id = $1 ORDER BY openfdd_key",
        )
        .bind(&site)
        .fetch_all(&pool)
        .await
        .unwrap();
        assert_eq!(
            stored,
            vec![
                ("AHU_1.rat".to_string(), Some(73.0), None),
                (
                    "AHU_1.sat".to_string(),
                    Some(55.0),
                    Some("degF".to_string())
                ),
            ]
        );

        sqlx::query("DELETE FROM sample_import_stage WHERE import_id = $1")
            .bind(import_id)
            .execute(&pool)
            .await
            .unwrap();
        sqlx::query("DELETE FROM sample WHERE site_id = $1")
            .bind(&site)
            .execute(&pool)
            .await
            .unwrap();
    }
}
