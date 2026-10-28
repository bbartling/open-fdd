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

fn cadence_u64_to_i64(secs: u64) -> Result<i64, TsdbError> {
    i64::try_from(secs).map_err(|_| TsdbError::CadenceOutOfRange(secs))
}

pub(crate) struct PortalPointUpsert<'a> {
    pub site_id: &'a str,
    pub portal_point_id: &'a str,
    pub provider_instance_id: Option<&'a str>,
    pub equipment_id: &'a str,
    pub role: &'a str,
    /// Resolved binding unit (overlay > NF tag > empty).
    pub unit: Option<&'a str>,
    /// NF portal tag unit only; updated on inventory sync.
    pub source_unit: Option<&'a str>,
    /// NF portal history mode (`cov` / `interval`) from inventory sync.
    pub source_history_mode: Option<&'a str>,
    pub quantity: Option<&'a str>,
    pub cadence_secs: Option<i64>,
    pub history_mode: Option<&'a str>,
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
    let role = null_if_empty(point.role);
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
          site_id, openfdd_key, haystack_id, role, unit, source_unit, source_history_mode,
          quantity, cadence_secs, history_mode, equipment_id,
          portal_point_id, provider_instance_id, referenced
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $3, $12, true)
        ON CONFLICT (site_id, openfdd_key) DO UPDATE
          SET haystack_id = EXCLUDED.haystack_id,
              role = EXCLUDED.role,
              unit = CASE WHEN $13 THEN EXCLUDED.unit ELSE point_map.unit END,
              source_unit = CASE
                WHEN $13 THEN EXCLUDED.source_unit ELSE point_map.source_unit
              END,
              source_history_mode = CASE
                WHEN $13 THEN EXCLUDED.source_history_mode ELSE point_map.source_history_mode
              END,
              quantity = CASE WHEN $13 THEN EXCLUDED.quantity ELSE point_map.quantity END,
              cadence_secs = CASE
                WHEN $13 THEN EXCLUDED.cadence_secs ELSE point_map.cadence_secs
              END,
              history_mode = CASE
                WHEN $13 THEN EXCLUDED.history_mode ELSE point_map.history_mode
              END,
              equipment_id = EXCLUDED.equipment_id,
              portal_point_id = EXCLUDED.portal_point_id,
              provider_instance_id = COALESCE(
                EXCLUDED.provider_instance_id, point_map.provider_instance_id
              ),
              referenced = CASE WHEN $13 THEN true ELSE point_map.referenced END
        RETURNING referenced
        "#,
    )
    .bind(point.site_id)
    .bind(&key)
    .bind(point.portal_point_id)
    .bind(role)
    .bind(point.unit)
    .bind(point.source_unit)
    .bind(point.source_history_mode)
    .bind(point.quantity)
    .bind(point.cadence_secs)
    .bind(point.history_mode)
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
        if let Some(role) = role {
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
            .bind(role)
            .bind(point.unit)
            .execute(&mut **tx)
            .await?;
        } else {
            sqlx::query("DELETE FROM role_map WHERE building_id = $1 AND openfdd_key = $2")
                .bind(point.site_id)
                .bind(&key)
                .execute(&mut **tx)
                .await?;
        }
    }
    Ok(key)
}

fn null_if_empty(role: &str) -> Option<&str> {
    let role = role.trim();
    if role.is_empty() {
        None
    } else {
        Some(role)
    }
}

/// Series key used only when this portal point has no `point_map` row yet.
/// A point with no custom role keeps the portal id. It does not become
/// `{equipment}.` and it is not chosen by sorting other keys.
pub(crate) fn inventory_candidate_key(
    equipment_id: &str,
    role: &str,
    portal_point_id: &str,
) -> String {
    if role.trim().is_empty() {
        portal_point_id.to_string()
    } else {
        format!("{}.{}", equipment_id.trim(), role.trim())
    }
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
    /// NF portal tag unit (may be empty).
    pub source_unit: Option<String>,
    /// NF portal history mode from inventory sync.
    pub source_history_mode: Option<String>,
    /// Resolved binding unit for authorized_series and role_map.
    pub unit: Option<String>,
    pub quantity: Option<String>,
    pub cadence_secs: Option<u64>,
    pub history_mode: Option<String>,
}

/// Re-resolve overlay metadata onto existing point_map rows (overlay write path).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PointMapBindingPatch {
    pub portal_point_id: String,
    pub source_unit: Option<String>,
    pub unit: Option<String>,
    pub quantity: Option<String>,
    pub cadence_secs: Option<u64>,
    pub history_mode: Option<String>,
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
            let candidate =
                inventory_candidate_key(&point.equipment_id, &point.role, &point.portal_point_id);
            let cadence_i64 = match point.cadence_secs {
                Some(secs) => Some(cadence_u64_to_i64(secs)?),
                None => None,
            };
            let key = upsert_portal_point(
                &mut tx,
                &PortalPointUpsert {
                    site_id,
                    portal_point_id: &point.portal_point_id,
                    provider_instance_id: Some(provider_instance_id),
                    equipment_id: &point.equipment_id,
                    role: &point.role,
                    unit: point.unit.as_deref(),
                    source_unit: point.source_unit.as_deref(),
                    source_history_mode: point.source_history_mode.as_deref(),
                    quantity: point.quantity.as_deref(),
                    cadence_secs: cadence_i64,
                    history_mode: point.history_mode.as_deref(),
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

    /// Apply engineer-resolved binding fields to existing portal points.
    pub async fn patch_point_map_bindings(
        &self,
        site_id: &str,
        patches: &[PointMapBindingPatch],
    ) -> Result<(), TsdbError> {
        if patches.is_empty() {
            return Ok(());
        }
        let mut tx = self.pool().begin().await?;
        for patch in patches {
            let cadence_i64 = match patch.cadence_secs {
                Some(secs) => Some(cadence_u64_to_i64(secs)?),
                None => None,
            };
            let updated = sqlx::query(
                r#"
                UPDATE point_map
                SET unit = $3,
                    quantity = $4,
                    cadence_secs = $5,
                    history_mode = $6
                WHERE site_id = $1 AND portal_point_id = $2
                "#,
            )
            .bind(site_id)
            .bind(&patch.portal_point_id)
            .bind(patch.unit.as_deref())
            .bind(patch.quantity.as_deref())
            .bind(cadence_i64)
            .bind(patch.history_mode.as_deref())
            .execute(&mut *tx)
            .await?
            .rows_affected();
            if updated == 0 {
                continue;
            }
            if let Some(unit) = patch.unit.as_deref() {
                sqlx::query(
                    r#"
                    UPDATE role_map
                    SET unit = $3
                    WHERE building_id = $1
                      AND openfdd_key IN (
                        SELECT openfdd_key FROM point_map
                        WHERE site_id = $1 AND portal_point_id = $2
                      )
                    "#,
                )
                .bind(site_id)
                .bind(&patch.portal_point_id)
                .bind(unit)
                .execute(&mut *tx)
                .await?;
            }
        }
        tx.commit().await?;
        Ok(())
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
        let key_refs: Vec<&str> = keys.iter().map(String::as_str).collect();
        report.samples_deleted = crate::writer::delete_samples(
            &mut tx,
            crate::writer::DeleteScope::Keys {
                site_id,
                openfdd_keys: &key_refs,
            },
        )
        .await?;
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

#[cfg(test)]
mod tests {
    use super::inventory_candidate_key;

    #[test]
    fn unmapped_inventory_keeps_the_portal_id_as_its_series_key() {
        assert_eq!(
            inventory_candidate_key("AHU_1", "", "portal-point-1"),
            "portal-point-1"
        );
        assert_eq!(
            inventory_candidate_key("AHU_1", "sat", "portal-point-1"),
            "AHU_1.sat"
        );
        assert_ne!(
            inventory_candidate_key("AHU_1", "", "portal-point-1"),
            "AHU_1."
        );
    }
}
