//! Portal inventory identity, orphaned historian points, and scoped purge.
//!
//! One `point_map` row per `(site_id, portal_point_id)`. A re-poll reuses that
//! row's `openfdd_key`; it never mints a second series for the same source
//! point. Sync never deletes samples or `point_map` rows: a point that leaves
//! the inventory is marked `referenced = false` and its samples become
//! orphaned data until an operator purges that equipment or point.

use std::collections::BTreeMap;

use serde::Serialize;
use sqlx::{Postgres, Row, Transaction};

use crate::client::{Tsdb, TsdbError};

pub(crate) struct PortalPointUpsert<'a> {
    pub site_id: &'a str,
    pub portal_point_id: &'a str,
    pub provider_instance_id: Option<&'a str>,
    pub equipment_id: &'a str,
    pub role: &'a str,
    pub unit: Option<&'a str>,
    /// Key used only when this portal point has no row yet.
    pub candidate_key: &'a str,
    /// Inventory sync marks the point referenced. Sample ingest leaves the flag.
    pub mark_referenced: bool,
}

/// Resolve or create the series key for one portal point and update its
/// role, unit, and equipment link in place.
pub(crate) async fn upsert_portal_point(
    tx: &mut Transaction<'_, Postgres>,
    point: &PortalPointUpsert<'_>,
) -> Result<String, TsdbError> {
    let existing: Option<String> = sqlx::query_scalar(
        "SELECT openfdd_key FROM point_map WHERE site_id = $1 AND portal_point_id = $2",
    )
    .bind(point.site_id)
    .bind(point.portal_point_id)
    .fetch_optional(&mut **tx)
    .await?;
    let key = match existing {
        Some(key) => key,
        None => {
            // A row written before portal identity existed carries the portal id
            // as haystack_id. Adopt it instead of starting a second series.
            let legacy: Option<String> = sqlx::query_scalar(
                "SELECT openfdd_key FROM point_map \
                 WHERE site_id = $1 AND portal_point_id IS NULL AND haystack_id = $2 \
                 ORDER BY openfdd_key LIMIT 1",
            )
            .bind(point.site_id)
            .bind(point.portal_point_id)
            .fetch_optional(&mut **tx)
            .await?;
            match legacy {
                Some(key) => key,
                None => free_key(tx, point).await?,
            }
        }
    };
    let row = sqlx::query(
        r#"
        INSERT INTO point_map(
          site_id, openfdd_key, haystack_id, role, unit, equipment_id,
          portal_point_id, provider_instance_id, referenced
        )
        VALUES ($1, $2, $3, $4, $5, $6, $3, $7, true)
        ON CONFLICT (site_id, openfdd_key) DO UPDATE
          SET haystack_id = EXCLUDED.haystack_id,
              role = EXCLUDED.role,
              unit = COALESCE(EXCLUDED.unit, point_map.unit),
              equipment_id = EXCLUDED.equipment_id,
              portal_point_id = EXCLUDED.portal_point_id,
              provider_instance_id = COALESCE(
                EXCLUDED.provider_instance_id, point_map.provider_instance_id
              ),
              referenced = CASE WHEN $8 THEN true ELSE point_map.referenced END
        RETURNING referenced
        "#,
    )
    .bind(point.site_id)
    .bind(&key)
    .bind(point.portal_point_id)
    .bind(point.role)
    .bind(point.unit)
    .bind(point.equipment_id)
    .bind(point.provider_instance_id)
    .bind(point.mark_referenced)
    .fetch_one(&mut **tx)
    .await?;
    let referenced: bool = row.try_get("referenced")?;
    sqlx::query(
        "DELETE FROM role_map WHERE building_id = $1 AND openfdd_key = $2 AND equipment_id <> $3",
    )
    .bind(point.site_id)
    .bind(&key)
    .bind(point.equipment_id)
    .execute(&mut **tx)
    .await?;
    if referenced {
        sqlx::query(
            r#"
            INSERT INTO role_map(building_id, equipment_id, openfdd_key, role, unit)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (building_id, equipment_id, openfdd_key) DO UPDATE
              SET role = EXCLUDED.role,
                  unit = COALESCE(EXCLUDED.unit, role_map.unit)
            "#,
        )
        .bind(point.site_id)
        .bind(point.equipment_id)
        .bind(&key)
        .bind(point.role)
        .bind(point.unit)
        .execute(&mut **tx)
        .await?;
    }
    Ok(key)
}

/// The candidate key unless another portal point already owns it.
async fn free_key(
    tx: &mut Transaction<'_, Postgres>,
    point: &PortalPointUpsert<'_>,
) -> Result<String, TsdbError> {
    let owner: Option<Option<String>> = sqlx::query_scalar(
        "SELECT portal_point_id FROM point_map WHERE site_id = $1 AND openfdd_key = $2",
    )
    .bind(point.site_id)
    .bind(point.candidate_key)
    .fetch_optional(&mut **tx)
    .await?;
    match owner {
        Some(Some(other)) if other != point.portal_point_id => {
            Ok(format!("{}#{}", point.candidate_key, point.portal_point_id))
        }
        _ => Ok(point.candidate_key.to_string()),
    }
}

/// One point from the latest successful portal inventory.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PortalInventoryPoint {
    pub portal_point_id: String,
    pub equipment_id: String,
    pub equip_type: Option<String>,
    pub role: String,
    pub unit: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct PortalInventoryReport {
    /// portal point id → series key.
    pub keys: BTreeMap<String, String>,
    pub referenced: u64,
    pub newly_unreferenced: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct HistorianPoint {
    pub equipment_id: Option<String>,
    pub equip_type: Option<String>,
    pub openfdd_key: String,
    pub role: Option<String>,
    pub unit: Option<String>,
    pub portal_point_id: Option<String>,
    pub referenced: bool,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct PurgeReport {
    pub keys: Vec<String>,
    pub samples_deleted: u64,
    pub point_map_deleted: u64,
    pub role_map_deleted: u64,
}

/// What a purge removes: every key of one equipment, or one key.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PurgeTarget<'a> {
    Equipment(&'a str),
    Point(&'a str),
}

impl Tsdb {
    /// Apply one successful portal inventory to `point_map`.
    ///
    /// Every listed point is referenced. With `allow_removals`, points from
    /// this provider that are missing become unreferenced. No sample and no
    /// `point_map` row is deleted.
    pub async fn sync_portal_inventory(
        &self,
        site_id: &str,
        provider_instance_id: &str,
        points: &[PortalInventoryPoint],
        allow_removals: bool,
    ) -> Result<PortalInventoryReport, TsdbError> {
        let mut tx = self.pool().begin().await?;
        sqlx::query(
            "INSERT INTO site(site_id, dis, timezone, enabled) VALUES ($1, $1, 'UTC', true) \
             ON CONFLICT (site_id) DO NOTHING",
        )
        .bind(site_id)
        .execute(&mut *tx)
        .await?;
        sqlx::query(
            "INSERT INTO building(building_id, site_id, dis, timezone) VALUES ($1, $1, $1, 'UTC') \
             ON CONFLICT (building_id) DO NOTHING",
        )
        .bind(site_id)
        .execute(&mut *tx)
        .await?;
        let mut report = PortalInventoryReport::default();
        for point in points {
            sqlx::query(
                r#"
                INSERT INTO equipment(building_id, equipment_id, equip_type)
                VALUES ($1, $2, $3)
                ON CONFLICT (building_id, equipment_id) DO UPDATE
                  SET equip_type = COALESCE(EXCLUDED.equip_type, equipment.equip_type)
                "#,
            )
            .bind(site_id)
            .bind(&point.equipment_id)
            .bind(point.equip_type.as_deref())
            .execute(&mut *tx)
            .await?;
            let candidate = format!("{}.{}", point.equipment_id, point.role);
            let key = upsert_portal_point(
                &mut tx,
                &PortalPointUpsert {
                    site_id,
                    portal_point_id: &point.portal_point_id,
                    provider_instance_id: Some(provider_instance_id),
                    equipment_id: &point.equipment_id,
                    role: &point.role,
                    unit: point.unit.as_deref(),
                    candidate_key: &candidate,
                    mark_referenced: true,
                },
            )
            .await?;
            report.keys.insert(point.portal_point_id.clone(), key);
            report.referenced += 1;
        }
        if !allow_removals {
            tx.commit().await?;
            return Ok(report);
        }
        let listed: Vec<String> = points.iter().map(|p| p.portal_point_id.clone()).collect();
        let dropped: Vec<String> = sqlx::query_scalar(
            r#"
            UPDATE point_map SET referenced = false
            WHERE site_id = $1
              AND provider_instance_id = $2
              AND referenced
              AND portal_point_id IS NOT NULL
              AND NOT (portal_point_id = ANY($3))
            RETURNING openfdd_key
            "#,
        )
        .bind(site_id)
        .bind(provider_instance_id)
        .bind(&listed)
        .fetch_all(&mut *tx)
        .await?;
        if !dropped.is_empty() {
            sqlx::query("DELETE FROM role_map WHERE building_id = $1 AND openfdd_key = ANY($2)")
                .bind(site_id)
                .bind(&dropped)
                .execute(&mut *tx)
                .await?;
        }
        report.newly_unreferenced = dropped.len() as u64;
        tx.commit().await?;
        Ok(report)
    }

    /// Unreferenced points that still hold samples (orphaned historian data).
    pub async fn orphaned_points(&self, site_id: &str) -> Result<Vec<HistorianPoint>, TsdbError> {
        let rows = sqlx::query(
            r#"
            SELECT pm.equipment_id, e.equip_type, pm.openfdd_key, pm.role, pm.unit,
                   pm.portal_point_id, pm.referenced
            FROM point_map pm
            LEFT JOIN equipment e
              ON e.building_id = pm.site_id AND e.equipment_id = pm.equipment_id
            WHERE pm.site_id = $1
              AND pm.referenced = false
              AND EXISTS (
                SELECT 1 FROM sample s
                WHERE s.site_id = pm.site_id AND s.openfdd_key = pm.openfdd_key
              )
            ORDER BY pm.equipment_id NULLS LAST, pm.openfdd_key
            "#,
        )
        .bind(site_id)
        .fetch_all(self.pool())
        .await?;
        rows.iter().map(historian_point).collect()
    }

    /// Every series the historian maps for a site, referenced or not.
    pub async fn historian_points(&self, site_id: &str) -> Result<Vec<HistorianPoint>, TsdbError> {
        let rows = sqlx::query(
            r#"
            SELECT pm.equipment_id, e.equip_type, pm.openfdd_key, pm.role, pm.unit,
                   pm.portal_point_id, pm.referenced
            FROM point_map pm
            LEFT JOIN equipment e
              ON e.building_id = pm.site_id AND e.equipment_id = pm.equipment_id
            WHERE pm.site_id = $1
            ORDER BY pm.equipment_id NULLS LAST, pm.openfdd_key
            "#,
        )
        .bind(site_id)
        .fetch_all(self.pool())
        .await?;
        rows.iter().map(historian_point).collect()
    }

    /// Delete `sample`, `point_map`, and `role_map` rows for one equipment's
    /// keys or for one key. Equipment keys come from `point_map` by exact id.
    pub async fn purge_historian(
        &self,
        site_id: &str,
        target: PurgeTarget<'_>,
    ) -> Result<PurgeReport, TsdbError> {
        let mut tx = self.pool().begin().await?;
        let keys: Vec<String> = match target {
            PurgeTarget::Equipment(equipment_id) => {
                sqlx::query_scalar(
                    "SELECT openfdd_key FROM point_map \
                     WHERE site_id = $1 AND equipment_id = $2 ORDER BY openfdd_key",
                )
                .bind(site_id)
                .bind(equipment_id)
                .fetch_all(&mut *tx)
                .await?
            }
            PurgeTarget::Point(key) => vec![key.to_string()],
        };
        let mut report = PurgeReport {
            keys: keys.clone(),
            ..PurgeReport::default()
        };
        if keys.is_empty() {
            tx.commit().await?;
            return Ok(report);
        }
        report.samples_deleted =
            sqlx::query("DELETE FROM sample WHERE site_id = $1 AND openfdd_key = ANY($2)")
                .bind(site_id)
                .bind(&keys)
                .execute(&mut *tx)
                .await?
                .rows_affected();
        report.point_map_deleted =
            sqlx::query("DELETE FROM point_map WHERE site_id = $1 AND openfdd_key = ANY($2)")
                .bind(site_id)
                .bind(&keys)
                .execute(&mut *tx)
                .await?
                .rows_affected();
        report.role_map_deleted =
            sqlx::query("DELETE FROM role_map WHERE building_id = $1 AND openfdd_key = ANY($2)")
                .bind(site_id)
                .bind(&keys)
                .execute(&mut *tx)
                .await?
                .rows_affected();
        tx.commit().await?;
        Ok(report)
    }
}

fn historian_point(row: &sqlx::postgres::PgRow) -> Result<HistorianPoint, TsdbError> {
    Ok(HistorianPoint {
        equipment_id: row.try_get("equipment_id")?,
        equip_type: row.try_get("equip_type")?,
        openfdd_key: row.try_get("openfdd_key")?,
        role: row.try_get("role")?,
        unit: row.try_get("unit")?,
        portal_point_id: row.try_get("portal_point_id")?,
        referenced: row.try_get("referenced")?,
    })
}
