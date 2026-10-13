use std::env;

use sqlx::postgres::PgPoolOptions;
use sqlx::{PgPool, Row};
use thiserror::Error;

use crate::sample::{SampleRow, UpsertBatch};

#[derive(Debug, Error)]
pub enum TsdbError {
    #[error("OPENFDD_DATABASE_URL is required for Timescale historian")]
    MissingDatabaseUrl,
    #[error(transparent)]
    Sqlx(#[from] sqlx::Error),
}

#[derive(Clone)]
pub struct Tsdb {
    pool: PgPool,
}

pub fn database_url_from_env() -> Result<String, TsdbError> {
    env::var("OPENFDD_DATABASE_URL").map_err(|_| TsdbError::MissingDatabaseUrl)
}

impl Tsdb {
    pub async fn connect_from_env() -> Result<Self, TsdbError> {
        Self::connect(&database_url_from_env()?).await
    }

    pub async fn connect(url: &str) -> Result<Self, TsdbError> {
        let pool = PgPoolOptions::new()
            .max_connections(
                env::var("OPENFDD_TIMESCALE_POOL")
                    .ok()
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(8),
            )
            .connect(url)
            .await?;
        Ok(Self { pool })
    }

    pub fn pool(&self) -> &PgPool {
        &self.pool
    }

    pub async fn ensure_site_building(&self, building_id: &str) -> Result<(), TsdbError> {
        sqlx::query(
            r#"
            INSERT INTO site(site_id, dis, timezone, enabled)
            VALUES ($1, $1, 'UTC', true)
            ON CONFLICT (site_id) DO NOTHING
            "#,
        )
        .bind(building_id)
        .execute(&self.pool)
        .await?;
        sqlx::query(
            r#"
            INSERT INTO building(building_id, site_id, dis, timezone)
            VALUES ($1, $1, $1, 'UTC')
            ON CONFLICT (building_id) DO NOTHING
            "#,
        )
        .bind(building_id)
        .execute(&self.pool)
        .await?;
        Ok(())
    }

    pub async fn upsert_equipment(
        &self,
        building_id: &str,
        equipment_id: &str,
        equip_type: Option<&str>,
    ) -> Result<(), TsdbError> {
        sqlx::query(
            r#"
            INSERT INTO equipment(building_id, equipment_id, equip_type)
            VALUES ($1, $2, $3)
            ON CONFLICT (building_id, equipment_id) DO UPDATE
              SET equip_type = COALESCE(EXCLUDED.equip_type, equipment.equip_type)
            "#,
        )
        .bind(building_id)
        .bind(equipment_id)
        .bind(equip_type)
        .execute(&self.pool)
        .await?;
        Ok(())
    }

    pub async fn upsert_samples(&self, batch: &UpsertBatch) -> Result<u64, TsdbError> {
        if batch.rows.is_empty() {
            return Ok(0);
        }
        let mut tx = self.pool.begin().await?;
        let mut n = 0u64;
        for row in &batch.rows {
            let r = sqlx::query(
                r#"
                INSERT INTO sample(ts, site_id, openfdd_key, haystack_id, val, unit, quality)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (site_id, openfdd_key, ts) DO UPDATE SET
                  val = EXCLUDED.val,
                  haystack_id = COALESCE(EXCLUDED.haystack_id, sample.haystack_id)
                "#,
            )
            .bind(row.ts)
            .bind(&row.site_id)
            .bind(&row.openfdd_key)
            .bind(&row.haystack_id)
            .bind(row.val)
            .bind(&row.unit)
            .bind(&row.quality)
            .execute(&mut *tx)
            .await?;
            n += r.rows_affected();
            if let (Some(equip), Some(role)) = (&row.equipment_id, &row.role) {
                sqlx::query(
                    r#"
                    INSERT INTO role_map(building_id, equipment_id, openfdd_key, role, unit)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT DO NOTHING
                    "#,
                )
                .bind(&row.site_id)
                .bind(equip)
                .bind(&row.openfdd_key)
                .bind(role)
                .bind(&row.unit)
                .execute(&mut *tx)
                .await?;
                sqlx::query(
                    r#"
                    INSERT INTO point_map(site_id, openfdd_key, haystack_id, role, unit, equipment_id)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT DO NOTHING
                    "#,
                )
                .bind(&row.site_id)
                .bind(&row.openfdd_key)
                .bind(row.haystack_id.as_deref().unwrap_or(&row.openfdd_key))
                .bind(role)
                .bind(&row.unit)
                .bind(equip)
                .execute(&mut *tx)
                .await?;
            }
        }
        tx.commit().await?;
        Ok(n)
    }

    pub async fn sample_count(&self, site_id: &str) -> Result<i64, TsdbError> {
        let row = sqlx::query("SELECT count(*)::bigint AS n FROM sample WHERE site_id = $1")
            .bind(site_id)
            .fetch_one(&self.pool)
            .await?;
        Ok(row.get::<i64, _>("n"))
    }

    pub async fn rule_registry_count(&self) -> Result<i64, TsdbError> {
        let row = sqlx::query("SELECT count(*)::bigint AS n FROM fdd_rule_registry")
            .fetch_one(&self.pool)
            .await?;
        Ok(row.get::<i64, _>("n"))
    }

    pub async fn health_ping(&self) -> Result<(), TsdbError> {
        sqlx::query("SELECT 1").execute(&self.pool).await?;
        Ok(())
    }
}

impl SampleRow {
    pub fn new(
        ts: chrono::DateTime<chrono::Utc>,
        site_id: impl Into<String>,
        openfdd_key: impl Into<String>,
        val: Option<f64>,
    ) -> Self {
        Self {
            ts,
            site_id: site_id.into(),
            openfdd_key: openfdd_key.into(),
            haystack_id: None,
            val,
            unit: None,
            quality: None,
            equipment_id: None,
            role: None,
        }
    }
}
