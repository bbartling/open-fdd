//! The one Timescale sample writer.
//!
//! Every product telemetry write reaches `sample` through this module: NF
//! portal polls and CSV append / remap (`Tsdb::upsert_samples_stats`), full CSV
//! package promotion (`promote_stage`), and the starter seed. One conflict rule
//! applies to all of them, so a replayed sample is left unchanged and a changed
//! value is overwritten in place. No other product code inserts into `sample`.

use std::collections::HashMap;

use chrono::{DateTime, Utc};
use sqlx::{Postgres, Transaction};

use crate::client::SampleUpsertStats;

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

const WRITE_ROWS_SQL: &str = concat!(
    sample_insert_columns!(),
    "SELECT * FROM UNNEST($1::timestamptz[], $2::text[], $3::text[], $4::text[], \
     $5::float8[], $6::text[], $7::text[])",
    sample_on_conflict!(),
    "RETURNING (xmax = 0) AS inserted"
);

const PROMOTE_STAGE_SQL: &str = concat!(
    sample_insert_columns!(),
    "SELECT ts, site_id, openfdd_key, haystack_id, val, NULL::text, NULL::text \
     FROM sample_import_stage WHERE import_id = $1 AND site_id = $2",
    sample_on_conflict!()
);

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
        let written: Vec<bool> = sqlx::query_scalar(WRITE_ROWS_SQL)
            .bind(&ts)
            .bind(&sites)
            .bind(&keys)
            .bind(&haystack)
            .bind(&vals)
            .bind(&units)
            .bind(&qualities)
            .fetch_all(&mut **tx)
            .await?;
        let inserted = written.iter().filter(|new| **new).count() as u64;
        let returned = written.len() as u64;
        stats.inserted += inserted;
        stats.updated += returned - inserted;
        stats.unchanged += chunk.len() as u64 - returned;
    }
    Ok(stats)
}

/// Promote one staged CSV package import into `sample` with the shared rule.
pub async fn promote_stage(
    tx: &mut Transaction<'_, Postgres>,
    import_id: uuid::Uuid,
    site_id: &str,
) -> Result<u64, sqlx::Error> {
    let done = sqlx::query(PROMOTE_STAGE_SQL)
        .bind(import_id)
        .bind(site_id)
        .execute(&mut **tx)
        .await?;
    Ok(done.rows_affected())
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
    }
}
