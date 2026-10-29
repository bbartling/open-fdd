//! Wave-X Soft-OPEN product paths on Timescale (Inspect / RCx / FDD series / FDD run).
//! No DataFusion / Parquet. Soft-OPEN ≠ FQ.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::path::{Path, PathBuf};

use anyhow::{anyhow, Context, Result};
use chrono::{DateTime, SecondsFormat, Utc};
use fdd_rules::{
    effective_param_strings, load_registry, load_tuning_profiles, rule_params, substitute_sql,
    RuleRegistry, RuleSpec,
};
use fdd_tsdb::Tsdb;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use sqlx::{Column, PgConnection, Row};

use crate::analytics::{envelope_with_engine, AnalyticsEnvelope, AnalyticsQuery, AnalyticsRequest};

const TS_ENGINE: &str = "timescale-sql";

fn sql_root() -> PathBuf {
    sql_root_for_registry()
}

/// Shared SQL pack root for registry.yaml (catalog aliases + plot/run).
pub(crate) fn sql_root_for_registry() -> PathBuf {
    if let Some(p) = std::env::var_os("OPENFDD_SQL_ROOT") {
        return PathBuf::from(p);
    }
    if let Some(p) = std::env::var_os("OPENFDD_SQL_RULES_DIR") {
        return PathBuf::from(p);
    }
    // Workspace root (services/central/../..) then sql/fdd — works in unit tests.
    let from_manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../sql/fdd")
        .canonicalize()
        .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../sql/fdd"));
    if from_manifest.is_dir() {
        return from_manifest;
    }
    PathBuf::from("sql/fdd")
}

fn load_reg() -> Result<RuleRegistry> {
    let root = sql_root();
    load_registry(&root).with_context(|| format!("load registry {}", root.display()))
}

fn rule_sql_path(reg: &RuleRegistry, sql_file: &str) -> PathBuf {
    let root = PathBuf::from(&reg.rules_dir);
    for c in [
        root.join("postgres/rules").join(sql_file),
        root.join("warehouse/rules").join(sql_file),
        root.join("rules").join(sql_file),
        root.join(sql_file),
    ] {
        if c.is_file() {
            return c;
        }
    }
    root.join("postgres/rules").join(sql_file)
}

fn safe_ident(name: &str) -> bool {
    !name.is_empty() && name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
}

/// Quantity and canonical SI unit for an RCx role. Unknown roles stay unlabeled.
/// Historian values are metric-c-v2; the SPA converts to the user display preference.
fn role_measure(role: &str) -> (&'static str, &'static str) {
    match role {
        "duct_static" | "duct_static_sp" | "duct_sp" | "static_sp" => ("air_pressure", "Pa"),
        "sat" | "mat" | "rat" | "oa_t" | "web_oa_t" | "web_wb_t" | "zone_t" | "chw_supply_t"
        | "chw_return_t" | "cw_supply_t" | "cw_return_t" | "hw_supply_t" | "hw_return_t" => {
            ("absolute_temperature", "degC")
        }
        _ => ("other", ""),
    }
}

/// Nearest-sample age cap for a portal channel that does not share the Y clock.
///
/// A Y sample pairs with the nearest sample of one model-bound X series when
/// the absolute timestamp difference is at most this age. The measured X value
/// is copied unchanged. Nothing is interpolated, and an older sample stays unpaired.
pub const RCX_X_ALIGN_MAX_AGE_SECS: i64 = 15 * 60;

/// Window and point cap for one RCx historian read.
pub(crate) struct RcxQuery {
    pub max_points: usize,
    pub scope: crate::timescale_analytics::AnalyticsSqlScope,
}

fn ts_rfc3339(ts: Option<DateTime<Utc>>) -> Value {
    json!(ts.map(|t| t.to_rfc3339_opts(chrono::SecondsFormat::Secs, true)))
}

fn insert_scope(
    obj: &mut serde_json::Map<String, Value>,
    scope: &crate::timescale_analytics::AnalyticsSqlScope,
    effective: &[String],
) {
    obj.insert("window_start".to_string(), ts_rfc3339(scope.start));
    obj.insert("window_end".to_string(), ts_rfc3339(scope.end));
    obj.insert("equipment_ids".to_string(), json!(scope.equipment_ids));
    obj.insert("effective_equipment_ids".to_string(), json!(effective));
}

/// Type filter first, then an exact equipment-id subset. No id substring.
fn cohort_ids(
    equipment: Vec<(String, Option<String>)>,
    kinds: &[&str],
    requested: &[String],
) -> Vec<String> {
    let mut ids: Vec<String> = equipment
        .into_iter()
        .filter(|(_, typ)| equip_matches_kinds(typ.as_deref(), kinds))
        .map(|(id, _)| id)
        .collect();
    if !requested.is_empty() {
        let wanted: BTreeSet<&str> = requested.iter().map(String::as_str).collect();
        ids.retain(|id| wanted.contains(id.as_str()));
    }
    ids.sort();
    ids.dedup();
    ids
}

fn delta_measure(primary: &str, companion: &str) -> Option<(&'static str, &'static str)> {
    let temperature = |role: &str| {
        matches!(
            role,
            "chw_supply_t"
                | "chw_return_t"
                | "cw_supply_t"
                | "cw_return_t"
                | "hw_supply_t"
                | "hw_return_t"
        )
    };
    if temperature(primary) && temperature(companion) {
        Some(("temperature_difference", "delta_degC"))
    } else {
        None
    }
}

fn kind_aliases(kind: &str) -> Vec<&'static str> {
    match kind.to_ascii_lowercase().as_str() {
        "ahu" | "rtu" | "mau" | "doas" => vec!["ahu", "rtu", "mau", "doas"],
        "vav" => vec!["vav"],
        "chiller" | "chw" | "chwplant" | "chw_plant" => {
            vec!["chiller", "chw", "chwplant", "chw_plant", "chwPlant"]
        }
        "boiler" => vec!["boiler"],
        "heatpump" | "hp" | "heat_pump" => vec!["heatpump", "hp", "heat_pump", "heatPump"],
        "weather" => vec!["weather"],
        "zone" | "zone_other" | "fcu" | "baseboard" => {
            vec!["zone", "zone_other", "fcu", "baseboard", "zone_other"]
        }
        "zone_family" => {
            vec![
                "vav",
                "fcu",
                "zone",
                "zone_other",
                "heatpump",
                "baseboard",
                "hp",
            ]
        }
        _ => vec![],
    }
}

fn equip_matches_kinds(equip_type: Option<&str>, kinds: &[&str]) -> bool {
    if kinds.is_empty() {
        return true;
    }
    let Some(raw) = equip_type.map(str::trim).filter(|s| !s.is_empty()) else {
        return false;
    };
    let raw_l = raw.to_ascii_lowercase();
    for k in kinds {
        if k.eq_ignore_ascii_case("ZONE_FAMILY") {
            if kind_aliases("zone_family").iter().any(|a| raw_l == *a) {
                return true;
            }
            continue;
        }
        if kind_aliases(k).iter().any(|a| raw_l == *a) || raw_l == k.to_ascii_lowercase() {
            return true;
        }
    }
    false
}

async fn list_equipment(tsdb: &Tsdb, building_id: &str) -> Result<Vec<(String, Option<String>)>> {
    let rows = sqlx::query(
        r#"
        SELECT equipment_id, equip_type
        FROM equipment
        WHERE building_id = $1
        ORDER BY equipment_id
        "#,
    )
    .bind(building_id)
    .fetch_all(tsdb.pool())
    .await
    .context("list_equipment")?;
    Ok(rows
        .into_iter()
        .map(|r| {
            (
                r.get::<String, _>("equipment_id"),
                r.try_get::<Option<String>, _>("equip_type").ok().flatten(),
            )
        })
        .collect())
}

/// Soft-OPEN P0-2: equipment_id → equip_type for `/api/fdd/results` kind filters.
pub async fn type_map_for_building(building_id: Option<&str>) -> Result<BTreeMap<String, String>> {
    let Some(bid) = building_id.map(str::trim).filter(|s| !s.is_empty()) else {
        return Ok(BTreeMap::new());
    };
    let tsdb = Tsdb::connect_from_env().await?;
    let rows = list_equipment(&tsdb, bid).await?;
    Ok(rows
        .into_iter()
        .filter_map(|(id, typ)| typ.map(|t| (id, t)))
        .collect())
}

/// Current binding: role → opaque keys. More than one key is ambiguous.
async fn binding_keys(
    tsdb: &Tsdb,
    building_id: &str,
    equipment_id: &str,
) -> Result<BTreeMap<String, Vec<String>>> {
    let rows = sqlx::query(
        r#"
        SELECT role, openfdd_key
        FROM authorized_series
        WHERE site_id = $1 AND equipment_id = $2
        ORDER BY role, openfdd_key
        "#,
    )
    .bind(building_id)
    .bind(equipment_id)
    .fetch_all(tsdb.pool())
    .await
    .context("binding_keys")?;
    let mut out: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for row in rows {
        let role: String = row.try_get("role").context("binding role")?;
        let key: String = row.try_get("openfdd_key").context("binding key")?;
        if role.is_empty() || role.contains('\0') || key.is_empty() {
            continue;
        }
        out.entry(role).or_default().push(key);
    }
    Ok(out)
}

fn ambiguous_bindings(keys: &BTreeMap<String, Vec<String>>) -> BTreeMap<String, Vec<String>> {
    keys.iter()
        .filter(|(_, bound)| bound.len() > 1)
        .map(|(role, bound)| (role.clone(), bound.clone()))
        .collect()
}

async fn roles_for_equipment(
    tsdb: &Tsdb,
    building_id: &str,
    equipment_id: &str,
) -> Result<Vec<String>> {
    Ok(binding_keys(tsdb, building_id, equipment_id)
        .await?
        .into_keys()
        .collect())
}

/// Wide inspect points for one equipment (SPA equipmentInspectionChart).
pub async fn inspect_equipment(
    building_id: &str,
    equipment_id: &str,
    columns: Option<&[String]>,
    max_points: usize,
    scope: &crate::timescale_analytics::AnalyticsSqlScope,
) -> Result<Option<AnalyticsEnvelope>> {
    let eq = equipment_id.trim();
    if eq.is_empty() || building_id.trim().is_empty() {
        return Ok(None);
    }
    if !scope.equipment_ids.is_empty() && !scope.equipment_ids.iter().any(|id| id == eq) {
        return Ok(None);
    }
    let tsdb = Tsdb::connect_from_env().await?;
    let plottable = roles_for_equipment(&tsdb, building_id, eq).await?;
    if plottable.is_empty() {
        return Ok(None);
    }
    const PREFERRED: &[&str] = &[
        "sat",
        "mat",
        "rat",
        "oa_t",
        "web_oa_t",
        "oa_damper_pct",
        "fan_status",
        "fan_cmd",
        "duct_static",
        "duct_static_sp",
        "sat_sp",
        "clg_valve_pct",
        "htg_valve_pct",
        "zone_t",
        "zone_flow",
        "chw_supply_t",
        "chw_return_t",
        "hw_supply_t",
        "hw_return_t",
        "occ_mode",
    ];
    let selected: Vec<String> = match columns {
        Some(want) if !want.is_empty() => want
            .iter()
            .filter(|c| plottable.iter().any(|p| p == *c))
            .cloned()
            .collect(),
        _ => {
            let mut picked: Vec<String> = PREFERRED
                .iter()
                .filter(|c| plottable.iter().any(|p| p == *c))
                .map(|c| (*c).to_string())
                .collect();
            if picked.is_empty() {
                picked = plottable.iter().take(8).cloned().collect();
            } else if picked.len() < 6 {
                for c in &plottable {
                    if picked.len() >= 8 {
                        break;
                    }
                    if !picked.iter().any(|p| p == c) {
                        picked.push(c.clone());
                    }
                }
            }
            picked
        }
    };
    if selected.is_empty() {
        return Ok(None);
    }
    let limit = max_points.clamp(50, 8000) as i64;
    let bound = binding_keys(&tsdb, building_id, eq).await?;
    let ambiguous = ambiguous_bindings(&bound);
    let unique: Vec<String> = selected
        .iter()
        .filter(|role| bound.get(*role).is_some_and(|keys| keys.len() == 1))
        .cloned()
        .collect();
    // One key per role. A second key stays out of the pivot instead of being maxed.
    let mut max_cols = String::new();
    for role in &unique {
        let alias = crate::series_binding::quote_ident(role);
        max_cols.push_str(&format!(
            ", MAX(s.val) FILTER (WHERE a.role = '{role_lit}') AS {alias}",
            role_lit = role.replace('\'', "''"),
        ));
    }
    let sql = format!(
        r#"
SELECT timestamp_utc {max_cols_outer}
FROM (
  SELECT
    s.ts AS timestamp_utc
    {max_cols},
    ROW_NUMBER() OVER (ORDER BY s.ts) AS _rn,
    COUNT(*) OVER () AS _cnt
  FROM sample s
  JOIN authorized_series a
    ON a.site_id = s.site_id AND a.openfdd_key = s.openfdd_key
  WHERE s.site_id = $1
    AND a.equipment_id = $2
    AND a.role = ANY($3)
    AND ($5::timestamptz IS NULL OR s.ts >= $5)
    AND ($6::timestamptz IS NULL OR s.ts < $6)
  GROUP BY s.ts
) s
WHERE _rn = 1 OR _rn = _cnt
   OR (_rn % (CASE WHEN ((_cnt + $4 - 1) / $4) > 1 THEN ((_cnt + $4 - 1) / $4) ELSE 1 END)) = 0
ORDER BY timestamp_utc
LIMIT $4
"#,
        max_cols_outer = unique
            .iter()
            .map(|r| format!(", {}", crate::series_binding::quote_ident(r)))
            .collect::<String>(),
        max_cols = max_cols,
    );
    let rows = if unique.is_empty() {
        Vec::new()
    } else {
        sqlx::query(&sql)
            .bind(building_id)
            .bind(eq)
            .bind(&unique)
            .bind(limit)
            .bind(scope.start)
            .bind(scope.end)
            .fetch_all(tsdb.pool())
            .await
            .context("inspect pivot")?
    };
    let mut points = Vec::with_capacity(rows.len());
    for r in &rows {
        let ts = r
            .try_get::<DateTime<Utc>, _>("timestamp_utc")
            .ok()
            .map(|t| t.to_rfc3339())
            .unwrap_or_default();
        let mut row = json!({
            "timestamp_utc": ts,
            "equipment_id": eq,
        });
        if let Some(obj) = row.as_object_mut() {
            for c in &unique {
                let v = r.try_get::<Option<f64>, _>(c.as_str()).ok().flatten();
                obj.insert(c.clone(), json!(v));
            }
        }
        points.push(row);
    }
    let first = points
        .first()
        .and_then(|p| p.get("timestamp_utc").and_then(|v| v.as_str()))
        .map(str::to_string);
    let last = points
        .last()
        .and_then(|p| p.get("timestamp_utc").and_then(|v| v.as_str()))
        .map(str::to_string);
    let mut env = envelope_with_engine(
        "equipment-inspect-v1",
        &AnalyticsQuery {
            building_id: Some(building_id.to_string()),
            ..Default::default()
        },
        vec!["equipment inspection points from Timescale sample (Wave-X Soft-OPEN)".into()],
        TS_ENGINE,
    );
    env.points = points;
    env.rows = unique.iter().map(|c| json!({ "column": c })).collect();
    let mut selected_keys = serde_json::Map::new();
    for role in &unique {
        if let Some(keys) = bound.get(role).and_then(|keys| keys.first()) {
            selected_keys.insert(role.clone(), json!(keys));
        }
    }
    env.coverage = Some(json!({
        "equipment_id": eq,
        "row_count": env.points.len(),
        "point_count": env.points.len(),
        "plottable_columns": plottable,
        "columns_plotted": unique,
        "selected_openfdd_keys": selected_keys,
        "ambiguous_roles": ambiguous,
        "role_binding_policy": crate::series_binding::ROLE_BINDING_POLICY,
        "first_timestamp": first,
        "last_timestamp": last,
        "source": "timescale_sample",
        "building_id": building_id,
        "engine": TS_ENGINE,
    }));
    if let Some(obj) = env.coverage.as_mut().and_then(Value::as_object_mut) {
        insert_scope(obj, scope, &[eq.to_string()]);
    }
    Ok(Some(env))
}

/// RCx multi-equipment role timeseries (`value_f` / optional motor).
pub async fn rcx_timeseries(
    building_id: &str,
    role_col: &str,
    overlay_col: Option<&str>,
    pair_return_col: Option<&str>,
    eq_kinds: &[&str],
    filter_fan_on: bool,
    read: &RcxQuery,
) -> Result<Option<AnalyticsEnvelope>> {
    if !safe_ident(role_col) {
        return Ok(None);
    }
    let tsdb = Tsdb::connect_from_env().await?;
    let equipment = list_equipment(&tsdb, building_id).await?;
    let ids = cohort_ids(equipment, eq_kinds, &read.scope.equipment_ids);
    if ids.is_empty() {
        return Ok(None);
    }
    let limit = read.max_points.clamp(200, 20000) as i64;
    let mut warnings =
        vec!["RCx role timeseries from Timescale sample (Wave-X Soft-OPEN)".to_string()];
    let overlay_role = match overlay_col {
        Some(role) if safe_ident(role) => role,
        Some(role) => {
            warnings.push(format!(
                "companion role '{role}' is not a safe identifier and was not queried"
            ));
            ""
        }
        None => "",
    };
    let return_role = match pair_return_col {
        Some(role) if safe_ident(role) => role,
        Some(role) => {
            warnings.push(format!(
                "return role '{role}' is not a safe identifier and was not queried"
            ));
            ""
        }
        None => "",
    };
    let fan_join = if filter_fan_on {
        "AND EXISTS (
            SELECT 1 FROM sample f
            JOIN authorized_series fa
              ON fa.site_id = f.site_id AND fa.openfdd_key = f.openfdd_key
            WHERE f.site_id = s.site_id AND f.ts = s.ts
              AND fa.equipment_id = a.equipment_id
              AND fa.role = 'fan_status'
              AND COALESCE(f.val, 0) > 0.05
              AND (
                SELECT count(*) FROM authorized_series fac
                WHERE fac.site_id = fa.site_id
                  AND fac.equipment_id = fa.equipment_id
                  AND fac.role = fa.role
              ) = 1
          )"
    } else {
        ""
    };
    // Bound equipment via ANY($3). Companion roles ($5, $6) join the same
    // authorized binding. A role with two keys is omitted, not averaged.
    let sql = format!(
        r#"
SELECT timestamp_utc, equipment_id, value_f, motor_f, overlay_f, return_f
FROM (
  SELECT
    s.ts AS timestamp_utc,
    a.equipment_id,
    s.val AS value_f,
    (
      SELECT CASE WHEN COALESCE(m.val, 0) > 0.05 THEN 1.0 ELSE 0.0 END
      FROM sample m
      JOIN authorized_series ma
        ON ma.site_id = m.site_id AND ma.openfdd_key = m.openfdd_key
      WHERE m.site_id = s.site_id AND m.ts = s.ts
        AND ma.equipment_id = a.equipment_id
        AND ma.role = 'fan_status'
        AND (
          SELECT count(*) FROM authorized_series mac
          WHERE mac.site_id = ma.site_id
            AND mac.equipment_id = ma.equipment_id
            AND mac.role = ma.role
        ) = 1
      LIMIT 1
    ) AS motor_f,
    (
      SELECT o.val
      FROM sample o
      JOIN authorized_series oa
        ON oa.site_id = o.site_id AND oa.openfdd_key = o.openfdd_key
      WHERE $5::text <> ''
        AND o.site_id = s.site_id
        AND o.ts = s.ts
        AND oa.equipment_id = a.equipment_id
        AND oa.role = $5::text
        AND (
          SELECT count(*) FROM authorized_series oac
          WHERE oac.site_id = oa.site_id
            AND oac.equipment_id = oa.equipment_id
            AND oac.role = oa.role
        ) = 1
      LIMIT 1
    ) AS overlay_f,
    (
      SELECT ret.val
      FROM sample ret
      JOIN authorized_series ra
        ON ra.site_id = ret.site_id AND ra.openfdd_key = ret.openfdd_key
      WHERE $6::text <> ''
        AND ret.site_id = s.site_id
        AND ret.ts = s.ts
        AND ra.equipment_id = a.equipment_id
        AND ra.role = $6::text
        AND (
          SELECT count(*) FROM authorized_series rac
          WHERE rac.site_id = ra.site_id
            AND rac.equipment_id = ra.equipment_id
            AND rac.role = ra.role
        ) = 1
      LIMIT 1
    ) AS return_f,
    ROW_NUMBER() OVER (ORDER BY s.ts, s.openfdd_key) AS _rn,
    COUNT(*) OVER () AS _cnt
  FROM sample s
  JOIN authorized_series a
    ON a.site_id = s.site_id AND a.openfdd_key = s.openfdd_key
  WHERE s.site_id = $1
    AND a.role = $2
    AND a.equipment_id = ANY($3)
    AND s.val IS NOT NULL
    AND (
      SELECT count(*) FROM authorized_series ac
      WHERE ac.site_id = a.site_id
        AND ac.equipment_id = a.equipment_id
        AND ac.role = a.role
    ) = 1
    AND ($7::timestamptz IS NULL OR s.ts >= $7)
    AND ($8::timestamptz IS NULL OR s.ts < $8)
    {fan_join}
) q
WHERE _rn = 1 OR _rn = _cnt
   OR (_rn % (CASE WHEN ((_cnt + $4 - 1) / $4) > 1 THEN ((_cnt + $4 - 1) / $4) ELSE 1 END)) = 0
ORDER BY timestamp_utc, equipment_id
LIMIT $4
"#
    );
    let rows = sqlx::query(&sql)
        .bind(building_id)
        .bind(role_col)
        .bind(&ids)
        .bind(limit)
        .bind(overlay_role)
        .bind(return_role)
        .bind(read.scope.start)
        .bind(read.scope.end)
        .fetch_all(tsdb.pool())
        .await
        .context("rcx_timeseries")?;
    if rows.is_empty() {
        return Ok(None);
    }
    let (primary_quantity, primary_unit) = role_measure(role_col);
    let mut points = Vec::new();
    let mut overlay_n = 0usize;
    let mut return_n = 0usize;
    let mut delta_n = 0usize;
    for r in &rows {
        let ts = r
            .try_get::<DateTime<Utc>, _>("timestamp_utc")
            .ok()
            .map(|t| t.to_rfc3339())
            .unwrap_or_default();
        let eq = r.try_get::<String, _>("equipment_id").unwrap_or_default();
        let value_f = r.try_get::<Option<f64>, _>("value_f").ok().flatten();
        let motor_f = r.try_get::<Option<f64>, _>("motor_f").ok().flatten();
        let overlay_f = r.try_get::<Option<f64>, _>("overlay_f").ok().flatten();
        let return_f = r.try_get::<Option<f64>, _>("return_f").ok().flatten();
        points.push(json!({
            "timestamp_utc": &ts,
            "equipment_id": &eq,
            "value_f": value_f,
            "series": "primary",
            "role": role_col,
            "quantity": primary_quantity,
            "unit": primary_unit,
        }));
        if let Some(m) = motor_f {
            points.push(json!({
                "timestamp_utc": &ts,
                "equipment_id": &eq,
                "value_f": if m > 0.05 { 1.0 } else { 0.0 },
                "series": "motor",
                "role": "fan_status",
            }));
        }
        if !overlay_role.is_empty() {
            if let Some(value) = overlay_f {
                let (quantity, unit) = role_measure(overlay_role);
                overlay_n += 1;
                points.push(json!({
                    "timestamp_utc": &ts,
                    "equipment_id": &eq,
                    "value_f": value,
                    "series": "overlay",
                    "role": overlay_role,
                    "quantity": quantity,
                    "unit": unit,
                }));
            }
        }
        if !return_role.is_empty() {
            if let Some(value) = return_f {
                let (quantity, unit) = role_measure(return_role);
                return_n += 1;
                points.push(json!({
                    "timestamp_utc": &ts,
                    "equipment_id": &eq,
                    "value_f": value,
                    "series": "return",
                    "role": return_role,
                    "quantity": quantity,
                    "unit": unit,
                }));
                if let (Some(primary), Some((delta_quantity, delta_unit))) =
                    (value_f, delta_measure(role_col, return_role))
                {
                    delta_n += 1;
                    points.push(json!({
                        "timestamp_utc": &ts,
                        "equipment_id": &eq,
                        "value_f": value - primary,
                        "series": "delta_t",
                        "role": return_role,
                        "quantity": delta_quantity,
                        "unit": delta_unit,
                    }));
                }
            }
        }
    }
    if !overlay_role.is_empty() && overlay_n == 0 {
        warnings.push(format!(
            "{overlay_role} was queried but no samples aligned to {role_col} timestamps"
        ));
    }
    if !return_role.is_empty() && return_n == 0 {
        warnings.push(format!(
            "{return_role} was queried but no samples aligned to {role_col} timestamps"
        ));
    }
    let mut traces = vec![json!({
        "series": "primary",
        "role": role_col,
        "quantity": primary_quantity,
        "unit": primary_unit,
    })];
    if !overlay_role.is_empty() {
        let (quantity, unit) = role_measure(overlay_role);
        traces.push(json!({
            "series": "overlay",
            "role": overlay_role,
            "quantity": quantity,
            "unit": unit,
            "aligned_points": overlay_n,
        }));
    }
    if !return_role.is_empty() {
        let (quantity, unit) = role_measure(return_role);
        traces.push(json!({
            "series": "return",
            "role": return_role,
            "quantity": quantity,
            "unit": unit,
            "aligned_points": return_n,
        }));
        if let Some((quantity, unit)) = delta_measure(role_col, return_role) {
            traces.push(json!({
                "series": "delta_t",
                "role": return_role,
                "quantity": quantity,
                "unit": unit,
                "aligned_points": delta_n,
            }));
        }
    }
    let mut env = envelope_with_engine(
        "rcx-timeseries-v1",
        &AnalyticsQuery {
            building_id: Some(building_id.to_string()),
            ..Default::default()
        },
        warnings,
        TS_ENGINE,
    );
    let n = points.len();
    env.points = points;
    env.coverage = Some(json!({
        "point_count": n,
        "role_col": role_col,
        "overlay_col": overlay_col,
        "pair_return_col": pair_return_col,
        "traces": traces,
        "chart_kind": "timeseries",
        "source": "timescale_sample",
        "building_id": building_id,
        "equipment_n": ids.len(),
        "engine": TS_ENGINE,
    }));
    if let Some(obj) = env.coverage.as_mut().and_then(Value::as_object_mut) {
        insert_scope(obj, &read.scope, &ids);
    }
    Ok(Some(env))
}

fn scatter_x_role(prefer_wetbulb: bool) -> (&'static str, &'static str) {
    if prefer_wetbulb {
        ("web_wb_t", "wet_bulb_temperature")
    } else {
        ("web_oa_t", "dry_bulb_temperature")
    }
}

fn scatter_unavailable(
    building_id: &str,
    y_col: &str,
    prefer_wetbulb: bool,
    ids: &[String],
    scope: &crate::timescale_analytics::AnalyticsSqlScope,
    reason: &str,
) -> AnalyticsEnvelope {
    let (role, quantity) = scatter_x_role(prefer_wetbulb);
    let mut env = envelope_with_engine(
        "rcx-scatter-v1",
        &AnalyticsQuery {
            building_id: Some(building_id.to_string()),
            start: scope.start,
            end: scope.end,
            equipment_ids: Some(scope.equipment_ids.clone()),
            ..Default::default()
        },
        vec![reason.to_string()],
        TS_ENGINE,
    );
    env.coverage = Some(json!({
        "point_count": 0,
        "role_col": y_col,
        "chart_kind": "scatter_oat",
        "source": "timescale_sample",
        "building_id": building_id,
        "engine": TS_ENGINE,
        "x_available": false,
        "x_point": {
            "role": role,
            "quantity": quantity,
            "unit": "°F",
            "available": false,
        },
    }));
    if let Some(obj) = env.coverage.as_mut().and_then(Value::as_object_mut) {
        insert_scope(obj, scope, ids);
    }
    env
}

/// One weather-typed equipment carrying `role`, nearest id first.
///
/// The stamp is `equip_type = weather`. BAS `oa_t` and a second weather series
/// are different points and are not candidates.
async fn bound_weather_equipment(
    tsdb: &Tsdb,
    building_id: &str,
    role: &str,
    scope: &crate::timescale_analytics::AnalyticsSqlScope,
) -> Result<Option<(String, String)>> {
    let row = sqlx::query(
        r#"
        SELECT e.equipment_id, a.openfdd_key
        FROM equipment e
        JOIN authorized_series a
          ON a.site_id = e.building_id
         AND a.equipment_id = e.equipment_id
         AND a.role = $2
        WHERE e.building_id = $1
          AND lower(btrim(e.equip_type)) = 'weather'
          AND (
            SELECT count(*)
            FROM authorized_series c
            WHERE c.site_id = a.site_id
              AND c.equipment_id = a.equipment_id
              AND c.role = a.role
          ) = 1
          AND EXISTS (
            SELECT 1
            FROM sample s
            WHERE s.site_id = $1
              AND s.openfdd_key = a.openfdd_key
              AND s.val IS NOT NULL
              AND (
                $3::timestamptz IS NULL
                OR s.ts >= $3 - ($5::int * interval '1 second')
              )
              AND (
                $4::timestamptz IS NULL
                OR s.ts < $4 + ($5::int * interval '1 second')
              )
          )
        ORDER BY e.equipment_id
        LIMIT 1
        "#,
    )
    .bind(building_id)
    .bind(role)
    .bind(scope.start)
    .bind(scope.end)
    .bind(RCX_X_ALIGN_MAX_AGE_SECS as i32)
    .fetch_optional(tsdb.pool())
    .await
    .context("bound weather x")?;
    Ok(match row {
        Some(r) => {
            let equipment_id: String = r.try_get("equipment_id").context("weather equipment")?;
            let openfdd_key: String = r.try_get("openfdd_key").context("weather key")?;
            Some((equipment_id, openfdd_key))
        }
        None => None,
    })
}

pub async fn rcx_oat_scatter(
    building_id: &str,
    y_col: &str,
    eq_kinds: &[&str],
    prefer_wetbulb: bool,
    read: &RcxQuery,
) -> Result<Option<AnalyticsEnvelope>> {
    if !safe_ident(y_col) {
        return Ok(None);
    }
    let tsdb = Tsdb::connect_from_env().await?;
    let equipment = list_equipment(&tsdb, building_id).await?;
    let ids = cohort_ids(equipment, eq_kinds, &read.scope.equipment_ids);
    if ids.is_empty() {
        return Ok(None);
    }
    let (x_role, x_quantity) = scatter_x_role(prefer_wetbulb);
    let Some((x_equipment, x_key)) =
        bound_weather_equipment(&tsdb, building_id, x_role, &read.scope).await?
    else {
        let reason = if prefer_wetbulb {
            "requested wet-bulb is unavailable: no weather equipment has web_wb_t in the aligned window; dry-bulb was not substituted"
        } else {
            "requested web dry-bulb is unavailable: no weather equipment has web_oa_t in the aligned window; other outdoor-air series were not substituted"
        };
        return Ok(Some(scatter_unavailable(
            building_id,
            y_col,
            prefer_wetbulb,
            &ids,
            &read.scope,
            reason,
        )));
    };
    // Wet-bulb keeps a dry-bulb reference only when that same weather equipment
    // has one current web_oa_t binding. The reference is never a copy of wet-bulb.
    let dry_key = if prefer_wetbulb {
        binding_keys(&tsdb, building_id, &x_equipment)
            .await?
            .get("web_oa_t")
            .filter(|keys| keys.len() == 1)
            .and_then(|keys| keys.first().cloned())
            .unwrap_or_default()
    } else {
        String::new()
    };
    let limit = read.max_points.clamp(200, 20000) as i64;
    let age = RCX_X_ALIGN_MAX_AGE_SECS as i32;
    let (y_quantity, y_unit) = role_measure(y_col);
    let rows = sqlx::query(
        r#"
        WITH y AS (
          SELECT s.ts, a.equipment_id, s.val AS y_f
          FROM sample s
          JOIN authorized_series a
            ON a.site_id = s.site_id AND a.openfdd_key = s.openfdd_key
          WHERE s.site_id = $1
            AND a.role = $2
            AND a.equipment_id = ANY($3)
            AND (
              SELECT count(*) FROM authorized_series c
              WHERE c.site_id = a.site_id
                AND c.equipment_id = a.equipment_id
                AND c.role = a.role
            ) = 1
            AND s.val IS NOT NULL
            AND ($4::timestamptz IS NULL OR s.ts >= $4)
            AND ($5::timestamptz IS NULL OR s.ts < $5)
        )
        SELECT
          y.ts AS timestamp_utc,
          y.equipment_id,
          y.y_f,
          x.ts AS x_ts,
          x.val AS x_f,
          x.quality AS x_quality,
          abs(EXTRACT(EPOCH FROM (y.ts - x.ts)))::float8 AS x_age_seconds,
          dry.val AS dry_f
        FROM y
        JOIN LATERAL (
          SELECT s.ts, s.val, s.quality
          FROM sample s
          WHERE s.site_id = $1
            AND s.openfdd_key = $6
            AND s.val IS NOT NULL
            AND s.ts >= y.ts - ($8::int * interval '1 second')
            AND s.ts <= y.ts + ($8::int * interval '1 second')
          ORDER BY abs(EXTRACT(EPOCH FROM (s.ts - y.ts))), s.ts
          LIMIT 1
        ) x ON true
        LEFT JOIN LATERAL (
          SELECT s.val
          FROM sample s
          WHERE $9::text <> ''
            AND s.site_id = $1
            AND s.openfdd_key = $9
            AND s.val IS NOT NULL
            AND s.ts >= y.ts - ($8::int * interval '1 second')
            AND s.ts <= y.ts + ($8::int * interval '1 second')
          ORDER BY abs(EXTRACT(EPOCH FROM (s.ts - y.ts))), s.ts
          LIMIT 1
        ) dry ON true
        ORDER BY y.ts DESC
        LIMIT $7
        "#,
    )
    .bind(building_id)
    .bind(y_col)
    .bind(&ids)
    .bind(read.scope.start)
    .bind(read.scope.end)
    .bind(&x_key)
    .bind(limit)
    .bind(age)
    .bind(&dry_key)
    .fetch_all(tsdb.pool())
    .await
    .context("rcx_oat_scatter")?;
    let mut points = Vec::with_capacity(rows.len());
    for r in &rows {
        let y_f = r.try_get::<Option<f64>, _>("y_f").ok().flatten();
        let x_f = r.try_get::<Option<f64>, _>("x_f").ok().flatten();
        let dry_f = r.try_get::<Option<f64>, _>("dry_f").ok().flatten();
        let mut point = json!({
            "timestamp_utc": r.try_get::<DateTime<Utc>, _>("timestamp_utc").ok().map(|t| t.to_rfc3339()),
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "y_f": y_f,
            "y_role": y_col,
            "y_quantity": y_quantity,
            "y_unit": y_unit,
            "oat_f": x_f,
            "x_f": x_f,
            "x_timestamp_utc": r.try_get::<DateTime<Utc>, _>("x_ts").ok().map(|t| t.to_rfc3339()),
            "x_equipment_id": &x_equipment,
            "x_role": x_role,
            "x_openfdd_key": &x_key,
            "x_quantity": x_quantity,
            "x_unit": "°F",
            "x_quality": r.try_get::<Option<String>, _>("x_quality").ok().flatten(),
            "x_age_seconds": r.try_get::<f64, _>("x_age_seconds").ok(),
        });
        if prefer_wetbulb {
            if let (Some(value), Some(obj)) = (dry_f, point.as_object_mut()) {
                obj.insert("dry_bulb_f".to_string(), json!(value));
                obj.insert("dry_bulb_role".to_string(), json!("web_oa_t"));
                obj.insert(
                    "dry_bulb_quantity".to_string(),
                    json!("dry_bulb_temperature"),
                );
                obj.insert("dry_bulb_unit".to_string(), json!("°F"));
            }
        }
        points.push(point);
    }
    let mut warnings = vec![
        "RCx scatter uses one weather-typed X series and nearest-sample alignment".to_string(),
    ];
    if points.is_empty() {
        warnings.push(format!(
            "no {y_col} samples paired with {x_key} within {RCX_X_ALIGN_MAX_AGE_SECS} seconds"
        ));
    }
    let mut env = envelope_with_engine(
        "rcx-scatter-v1",
        &AnalyticsQuery {
            building_id: Some(building_id.to_string()),
            start: read.scope.start,
            end: read.scope.end,
            equipment_ids: Some(read.scope.equipment_ids.clone()),
            ..Default::default()
        },
        warnings,
        TS_ENGINE,
    );
    let n = points.len();
    env.points = points;
    env.coverage = Some(json!({
        "point_count": n,
        "role_col": y_col,
        "y_quantity": y_quantity,
        "y_unit": y_unit,
        "chart_kind": "scatter_oat",
        "source": "timescale_sample",
        "building_id": building_id,
        "engine": TS_ENGINE,
        "x_available": true,
        "x_point": {
            "equipment_id": x_equipment,
            "role": x_role,
            "openfdd_key": x_key,
            "quantity": x_quantity,
            "unit": "°F",
            "available": true,
            "selection": "lexicographically first weather equipment with this role near the window",
        },
        "alignment": {
            "method": "nearest_sample",
            "max_age_seconds": RCX_X_ALIGN_MAX_AGE_SECS,
            "tie_break": "earlier_timestamp",
            "interpolation": false,
        },
    }));
    if let Some(obj) = env.coverage.as_mut().and_then(Value::as_object_mut) {
        insert_scope(obj, &read.scope, &ids);
    }
    Ok(Some(env))
}

pub async fn rcx_box(
    building_id: &str,
    role_col: &str,
    eq_kinds: &[&str],
    filter_fan_on: bool,
    read: &RcxQuery,
) -> Result<Option<AnalyticsEnvelope>> {
    rcx_timeseries(
        building_id,
        role_col,
        None,
        None,
        eq_kinds,
        filter_fan_on,
        read,
    )
    .await
}

#[derive(Debug)]
pub enum ComfortRankError {
    InvalidBand {
        low_f: f64,
        high_f: f64,
    },
    Decode {
        column: &'static str,
        source: sqlx::Error,
    },
    NonFinite {
        equipment_id: String,
        value: f64,
    },
}

impl std::fmt::Display for ComfortRankError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidBand { low_f, high_f } => write!(
                f,
                "comfort band must be finite with low <= high (low={low_f}, high={high_f})"
            ),
            Self::Decode { column, source } => {
                write!(
                    f,
                    "comfort rank column '{column}' failed to decode: {source}"
                )
            }
            Self::NonFinite {
                equipment_id,
                value,
            } => write!(
                f,
                "comfort_pct for '{equipment_id}' is not a finite percent: {value}"
            ),
        }
    }
}

impl std::error::Error for ComfortRankError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Decode { source, .. } => Some(source),
            Self::InvalidBand { .. } | Self::NonFinite { .. } => None,
        }
    }
}

/// One ranking row. Every row has at least one sample, so a null or
/// undecodable `comfort_pct` is an error rather than a missing value.
fn comfort_rank_point(row: &sqlx::postgres::PgRow) -> Result<Value, ComfortRankError> {
    fn get<'r, T>(
        row: &'r sqlx::postgres::PgRow,
        column: &'static str,
    ) -> Result<T, ComfortRankError>
    where
        T: sqlx::Decode<'r, sqlx::Postgres> + sqlx::Type<sqlx::Postgres>,
    {
        row.try_get::<T, _>(column)
            .map_err(|source| ComfortRankError::Decode { column, source })
    }
    let equipment_id: String = get(row, "equipment_id")?;
    let comfort_pct: f64 = get(row, "comfort_pct")?;
    let n: i64 = get(row, "n")?;
    if !comfort_pct.is_finite() {
        return Err(ComfortRankError::NonFinite {
            equipment_id,
            value: comfort_pct,
        });
    }
    Ok(json!({
        "equipment_id": equipment_id,
        "comfort_pct": comfort_pct,
        "n": n,
        "value_f": comfort_pct,
    }))
}

pub async fn rcx_zone_comfort_rank(
    building_id: &str,
    eq_kinds: &[&str],
    comfort_low_f: f64,
    comfort_high_f: f64,
    scope: &crate::timescale_analytics::AnalyticsSqlScope,
) -> Result<Option<AnalyticsEnvelope>> {
    if !comfort_low_f.is_finite() || !comfort_high_f.is_finite() || comfort_low_f > comfort_high_f {
        return Err(ComfortRankError::InvalidBand {
            low_f: comfort_low_f,
            high_f: comfort_high_f,
        }
        .into());
    }
    let tsdb = Tsdb::connect_from_env().await?;
    let equipment = list_equipment(&tsdb, building_id).await?;
    let ids = cohort_ids(equipment, eq_kinds, &scope.equipment_ids);
    if ids.is_empty() {
        return Ok(None);
    }
    let overlay = open_fdd_edge_prototype::csv_ingest::model_overlay::load_engineer_point_overlay(
        csv_building_root(building_id).as_path(),
    )
    .ok();
    let binding_rows = sqlx::query(
        r#"
        SELECT a.equipment_id, a.openfdd_key, pm.portal_point_id,
               (
                 SELECT s.unit
                 FROM sample s
                 WHERE s.site_id = a.site_id
                   AND s.openfdd_key = a.openfdd_key
                   AND s.unit IS NOT NULL
                   AND btrim(s.unit) <> ''
                 ORDER BY s.ts DESC
                 LIMIT 1
               ) AS sample_unit
        FROM authorized_series a
        JOIN point_map pm
          ON pm.site_id = a.site_id AND pm.openfdd_key = a.openfdd_key
        WHERE a.site_id = $1
          AND a.role = 'zone_t'
          AND a.equipment_id = ANY($2)
          AND (
            SELECT count(*) FROM authorized_series c
            WHERE c.site_id = a.site_id
              AND c.equipment_id = a.equipment_id
              AND c.role = a.role
          ) = 1
        "#,
    )
    .bind(building_id)
    .bind(&ids)
    .fetch_all(tsdb.pool())
    .await
    .context("rcx zone bindings")?;
    let mut assessable: Vec<String> = Vec::new();
    for row in &binding_rows {
        let equipment_id: String = row.try_get("equipment_id")?;
        let portal_point_id: Option<String> = row.try_get("portal_point_id")?;
        let sample_unit: Option<String> = row.try_get("sample_unit")?;
        let engineer = overlay.as_ref().and_then(|store| {
            portal_point_id
                .as_ref()
                .and_then(|pid| store.points.get(pid))
                .and_then(|entry| entry.unit.clone())
        });
        let effective = engineer.as_deref().or(sample_unit.as_deref());
        if crate::zone_comfort_units::comfort_band_in_unit(comfort_low_f, comfort_high_f, effective)
            .is_some()
        {
            assessable.push(equipment_id);
        }
    }
    assessable.sort();
    assessable.dedup();
    if assessable.is_empty() {
        return Ok(None);
    }
    let rows = sqlx::query(
        r#"
        WITH band AS (
          SELECT $2::float8 AS lo_f, $3::float8 AS hi_f
        )
        SELECT
          a.equipment_id,
          (100.0 * AVG(
            CASE
              WHEN btrim(coalesce(s.unit, '')) = '' THEN NULL
              WHEN lower(regexp_replace(coalesce(s.unit, ''), '[^a-zA-Z0-9]', '', 'g'))
                   IN ('c', 'degc', 'celsius')
                THEN CASE
                  WHEN s.val BETWEEN ((band.lo_f - 32.0) * 5.0 / 9.0)
                                 AND ((band.hi_f - 32.0) * 5.0 / 9.0)
                  THEN 1.0 ELSE 0.0 END
              ELSE CASE
                WHEN s.val BETWEEN band.lo_f AND band.hi_f THEN 1.0 ELSE 0.0 END
            END
          ))::float8 AS comfort_pct,
          COUNT(*) FILTER (
            WHERE btrim(coalesce(s.unit, '')) <> ''
          )::bigint AS n
        FROM sample s
        JOIN authorized_series a
          ON a.site_id = s.site_id AND a.openfdd_key = s.openfdd_key
        CROSS JOIN band
        WHERE s.site_id = $1
          AND a.role = 'zone_t'
          AND a.equipment_id = ANY($4)
          AND s.val IS NOT NULL
          AND ($5::timestamptz IS NULL OR s.ts >= $5)
          AND ($6::timestamptz IS NULL OR s.ts < $6)
        GROUP BY a.equipment_id
        HAVING COUNT(*) FILTER (WHERE btrim(coalesce(s.unit, '')) <> '') > 0
        ORDER BY comfort_pct ASC, a.equipment_id ASC
        LIMIT 200
        "#,
    )
    .bind(building_id)
    .bind(comfort_low_f)
    .bind(comfort_high_f)
    .bind(&assessable)
    .bind(scope.start)
    .bind(scope.end)
    .fetch_all(tsdb.pool())
    .await
    .context("rcx_zone_comfort_rank")?;
    if rows.is_empty() {
        return Ok(None);
    }
    let points = rows
        .iter()
        .map(comfort_rank_point)
        .collect::<Result<Vec<_>, _>>()?;
    let mut env = envelope_with_engine(
        "rcx-ranking-v1",
        &AnalyticsQuery {
            building_id: Some(building_id.to_string()),
            ..Default::default()
        },
        vec!["RCx zone comfort rank from Timescale sample (Wave-X Soft-OPEN)".into()],
        TS_ENGINE,
    );
    let n = points.len();
    env.points = points.clone();
    env.rows = points;
    env.coverage = Some(json!({
        "point_count": n,
        "chart_kind": "ranking",
        "source": "timescale_sample",
        "building_id": building_id,
        "engine": TS_ENGINE,
    }));
    if let Some(obj) = env.coverage.as_mut().and_then(Value::as_object_mut) {
        insert_scope(obj, scope, &ids);
    }
    Ok(Some(env))
}

/// Dispatch for respond_query("equipment-inspect").
pub async fn inspect_json(req: &AnalyticsRequest) -> Result<Value> {
    let Some(building) = req
        .query
        .building_id
        .clone()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
    else {
        return Ok(json!({
            "ok": false,
            "error": "building_id required for Timescale inspect",
            "engine": TS_ENGINE,
            "points": [],
            "warnings": ["building_id required"],
        }));
    };
    let eq = req
        .query
        .equipment_ids
        .as_ref()
        .and_then(|ids| ids.first())
        .map(|s| s.as_str())
        .unwrap_or("");
    let columns: Option<Vec<String>> = req.series.as_ref().and_then(|s| {
        s.get("columns").and_then(|c| c.as_array()).map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
    });
    let max_points = req.query.max_points.unwrap_or(2000);
    let scope = crate::timescale_analytics::AnalyticsSqlScope::from_request(req);
    match inspect_equipment(&building, eq, columns.as_deref(), max_points, &scope).await? {
        Some(env) => Ok(env.to_json()),
        None => {
            let mut env = envelope_with_engine(
                "equipment-inspect-v1",
                &req.query,
                vec!["no Timescale samples for equipment".into()],
                TS_ENGINE,
            );
            env.coverage = Some(json!({
                "equipment_id": eq,
                "plottable_columns": [],
                "columns_plotted": [],
                "point_count": 0,
                "source": "timescale_sample",
                "building_id": building,
            }));
            if let Some(obj) = env.coverage.as_mut().and_then(Value::as_object_mut) {
                insert_scope(obj, &scope, &[]);
            }
            Ok(env.to_json())
        }
    }
}

/// Cap series count for lean Plotly (C12): required ∪ limited optional, ≤6.
const LEAN_PLOT_MAX_ROLES: usize = 6;
const LEAN_PLOT_DEFAULT_POINTS: usize = 1500;
const LEAN_PLOT_HARD_CAP: usize = 5000;

/// Resolve catalog roles for a rule — never alphabetically dump point_map.
pub fn catalog_plot_roles(rule: &RuleSpec) -> Vec<String> {
    let mut roles: Vec<String> = rule.required_roles.clone();
    for r in &rule.optional_roles {
        if !roles.iter().any(|x| x == r) {
            roles.push(r.clone());
        }
    }
    roles.retain(|r| safe_ident(r));
    if roles.len() > LEAN_PLOT_MAX_ROLES {
        roles.truncate(LEAN_PLOT_MAX_ROLES);
    }
    roles
}

fn clamp_max_points(max_points: Option<usize>) -> usize {
    max_points
        .unwrap_or(LEAN_PLOT_DEFAULT_POINTS)
        .clamp(50, LEAN_PLOT_HARD_CAP)
}

/// FDD plot series: wide role columns for one equipment + rule roles.
#[allow(dead_code)]
pub async fn fdd_series(
    building_id: Option<&str>,
    equipment_id: &str,
    rule_id: &str,
) -> Result<Value> {
    fdd_plot(building_id, equipment_id, rule_id, None, None, None).await
}

/// Lean Plotly data plane (C12): catalog roles only, downsampled, optional window.
pub async fn fdd_plot(
    building_id: Option<&str>,
    equipment_id: &str,
    rule_id: &str,
    max_points: Option<usize>,
    window_start: Option<&str>,
    window_end: Option<&str>,
) -> Result<Value> {
    let bid = building_id.map(str::trim).filter(|s| !s.is_empty());
    let Some(building_id) = bid else {
        return Ok(json!({
            "ok": false,
            "error": "building_id required for Timescale FDD plot",
            "engine": TS_ENGINE,
            "rows": [],
            "series": {},
        }));
    };
    let reg = load_reg()?;
    let Some(rule) = reg
        .rules
        .iter()
        .find(|r| r.rule_id == rule_id || r.aliases.iter().any(|a| a == rule_id))
    else {
        return Ok(json!({
            "ok": false,
            "error": format!("unknown rule_id {rule_id}"),
            "rows": [],
            "series": {},
            "note": "Unknown catalog rule — no point_map LIMIT-N fallback.",
        }));
    };
    let mut roles = catalog_plot_roles(rule);
    let max_pts = clamp_max_points(max_points);
    if roles.is_empty() {
        return Ok(json!({
            "ok": true,
            "equipment_id": equipment_id,
            "rule_id": rule.rule_id,
            "site_id": building_id,
            "building_id": building_id,
            "rows": [],
            "roles": [],
            "series": {},
            "confirmed_fault": {"ts": [], "y": []},
            "point_count": 0,
            "max_points": max_pts,
            "note": "Catalog rule has no plottable roles for this equipment.",
            "engine": TS_ENGINE,
        }));
    }
    let tsdb = Tsdb::connect_from_env().await?;
    let bound = binding_keys(&tsdb, building_id, equipment_id).await?;
    let ambiguous = ambiguous_bindings(&bound);
    let present_set: BTreeSet<_> = bound
        .iter()
        .filter(|(_, keys)| keys.len() == 1)
        .map(|(role, _)| role.clone())
        .collect();
    let required_ambiguous: Vec<String> = rule
        .required_roles
        .iter()
        .filter(|r| ambiguous.contains_key(r.as_str()))
        .cloned()
        .collect();
    if !required_ambiguous.is_empty() {
        return Ok(json!({
            "ok": false,
            "error": format!(
                "ambiguous roles for rule {}: {}",
                rule.rule_id,
                required_ambiguous.join(", ")
            ),
            "ambiguous_roles": required_ambiguous,
            "role_binding_policy": crate::series_binding::ROLE_BINDING_POLICY,
            "equipment_id": equipment_id,
            "rule_id": rule.rule_id,
            "site_id": building_id,
            "building_id": building_id,
            "rows": [],
            "series": {},
            "engine": TS_ENGINE,
        }));
    }
    let missing: Vec<String> = rule
        .required_roles
        .iter()
        .filter(|r| safe_ident(r) && !present_set.contains(r.as_str()))
        .cloned()
        .collect();
    // Soft note when optional roles missing; hard fail only if required missing.
    let mut note_parts: Vec<String> = Vec::new();
    if !missing.is_empty() {
        return Ok(json!({
            "ok": false,
            "error": format!("missing roles for rule {}: {}", rule.rule_id, missing.join(", ")),
            "missing_roles": missing,
            "equipment_id": equipment_id,
            "rule_id": rule.rule_id,
            "site_id": building_id,
            "building_id": building_id,
            "rows": [],
            "series": {},
            "engine": TS_ENGINE,
        }));
    }
    roles.retain(|r| present_set.contains(r));
    if roles.is_empty() {
        note_parts.push("No mapped roles present on this equipment.".into());
        return Ok(json!({
            "ok": true,
            "equipment_id": equipment_id,
            "rule_id": rule.rule_id,
            "site_id": building_id,
            "building_id": building_id,
            "rows": [],
            "roles": [],
            "series": {},
            "confirmed_fault": {"ts": [], "y": []},
            "point_count": 0,
            "max_points": max_pts,
            "note": note_parts.join(" "),
            "engine": TS_ENGINE,
        }));
    }
    let mut max_cols = String::new();
    for role in &roles {
        max_cols.push_str(&format!(
            ", MAX(s.val) FILTER (WHERE a.role = '{role}') AS \"{role}\""
        ));
    }
    let mut window_sql = String::new();
    if let Some(start) = window_start.map(str::trim).filter(|s| !s.is_empty()) {
        if DateTime::parse_from_rfc3339(start).is_ok() {
            window_sql.push_str(&format!(" AND s.ts >= '{start}'::timestamptz"));
        }
    }
    if let Some(end) = window_end.map(str::trim).filter(|s| !s.is_empty()) {
        if DateTime::parse_from_rfc3339(end).is_ok() {
            window_sql.push_str(&format!(" AND s.ts <= '{end}'::timestamptz"));
        }
    }
    let sql = format!(
        r#"
SELECT timestamp_utc {sel}
FROM (
  SELECT
    s.ts AS timestamp_utc
    {max_cols},
    ROW_NUMBER() OVER (ORDER BY s.ts) AS _rn,
    COUNT(*) OVER () AS _cnt
  FROM sample s
  JOIN authorized_series a
    ON a.site_id = s.site_id AND a.openfdd_key = s.openfdd_key
  WHERE s.site_id = $1
    AND a.equipment_id = $2
    AND a.role = ANY($3){window_sql}
  GROUP BY s.ts
) s
WHERE _rn = 1 OR _rn = _cnt
   OR (_rn % (CASE WHEN ((_cnt + $4 - 1) / $4) > 1 THEN ((_cnt + $4 - 1) / $4) ELSE 1 END)) = 0
ORDER BY timestamp_utc
LIMIT $4
"#,
        sel = roles
            .iter()
            .map(|r| format!(", \"{r}\""))
            .collect::<String>(),
        max_cols = max_cols,
        window_sql = window_sql,
    );
    let rows = sqlx::query(&sql)
        .bind(building_id)
        .bind(equipment_id)
        .bind(&roles)
        .bind(max_pts as i64)
        .fetch_all(tsdb.pool())
        .await
        .context("fdd_plot pivot")?;
    let mut out_rows = Vec::with_capacity(rows.len());
    let mut lean: serde_json::Map<String, Value> = serde_json::Map::new();
    for role in &roles {
        lean.insert(role.clone(), json!({"ts": [], "y": []}));
    }
    let mut fault_ts = Vec::new();
    let mut fault_y = Vec::new();
    for r in &rows {
        let ts = r
            .try_get::<DateTime<Utc>, _>("timestamp_utc")
            .ok()
            .map(ts_key);
        let mut row = json!({
            "timestamp_utc": ts,
            "equipment_id": equipment_id,
        });
        if let Some(obj) = row.as_object_mut() {
            for c in &roles {
                let v = r.try_get::<Option<f64>, _>(c.as_str()).ok().flatten();
                obj.insert(c.clone(), json!(v));
                if let Some(series) = lean.get_mut(c).and_then(|s| s.as_object_mut()) {
                    if let Some(ts_arr) = series.get_mut("ts").and_then(|x| x.as_array_mut()) {
                        ts_arr.push(json!(ts));
                    }
                    if let Some(y_arr) = series.get_mut("y").and_then(|x| x.as_array_mut()) {
                        y_arr.push(json!(v));
                    }
                }
            }
            obj.insert("confirmed_fault".into(), Value::Null);
        }
        out_rows.push(row);
    }
    let mut fault_map = match load_live_confirmed_fault(
        &tsdb,
        &reg,
        rule,
        building_id,
        equipment_id,
        window_start,
        window_end,
    )
    .await
    {
        Ok(map) => map,
        Err(err) => {
            tracing::warn!(
                rule = %rule.rule_id,
                equipment_id,
                error = %err,
                "confirmed_fault series query failed"
            );
            HashMap::new()
        }
    };
    if fault_map.is_empty() {
        if let Ok(hint) = load_confirmed_fault_hint(building_id, equipment_id, &rule.rule_id) {
            fault_map = hint;
        }
    }
    for row in &mut out_rows {
        let ts_owned = row
            .get("timestamp_utc")
            .and_then(|v| v.as_str())
            .map(str::to_string);
        if let Some(ts) = ts_owned {
            if let Some(flag) = fault_map.get(ts.as_str()) {
                if let Some(obj) = row.as_object_mut() {
                    obj.insert("confirmed_fault".into(), json!(*flag));
                }
                fault_ts.push(json!(ts));
                fault_y.push(json!(if *flag { 1 } else { 0 }));
            }
        }
    }
    let point_count = out_rows.len();
    if point_count >= max_pts {
        note_parts.push(format!("Downsampled to ≤{max_pts} pts/series for UI."));
    }
    // OAT-METEO must never fall back to duct-static via point_map dump (roles from catalog only).
    if rule.rule_id.eq_ignore_ascii_case("OAT-METEO")
        && roles
            .iter()
            .any(|r| r.contains("duct") || r.contains("static"))
    {
        note_parts.push("OAT-METEO catalog roles exclude duct-static fallback.".into());
    }
    let note = if note_parts.is_empty() {
        Value::Null
    } else {
        json!(note_parts.join(" "))
    };
    // Soft-OPEN R4: surface lean plot budgets for SPA (roles ≤6, pts hard-cap).
    let approx_bytes =
        point_count.saturating_mul(roles.len().saturating_mul(24).saturating_add(32));
    let mut selected_keys = serde_json::Map::new();
    for role in &roles {
        if let Some(key) = bound.get(role).and_then(|keys| keys.first()) {
            selected_keys.insert(role.clone(), json!(key));
        }
    }
    Ok(json!({
        "ok": true,
        "equipment_id": equipment_id,
        "rule_id": rule.rule_id,
        "site_id": building_id,
        "building_id": building_id,
        "roles": roles,
        "selected_openfdd_keys": selected_keys,
        "role_binding_policy": crate::series_binding::ROLE_BINDING_POLICY,
        "rows": out_rows,
        "series": lean,
        "confirmed_fault": {"ts": fault_ts, "y": fault_y},
        "fault_hours": load_result_fault_hours(building_id, equipment_id, &rule.rule_id)
            .map(|h| json!(h))
            .unwrap_or(Value::Null),
        "point_count": point_count,
        "downsampled": point_count >= max_pts,
        "max_points": max_pts,
        "lean_budget": {
            "max_roles": LEAN_PLOT_MAX_ROLES,
            "default_points": LEAN_PLOT_DEFAULT_POINTS,
            "hard_cap_points": LEAN_PLOT_HARD_CAP,
            "approx_payload_bytes": approx_bytes,
        },
        "note": note,
        "has_confirmed_fault": out_rows.iter().any(|r| r.get("confirmed_fault").and_then(|v| v.as_bool()).is_some()),
        "engine": TS_ENGINE,
        "source": "timescale_sample",
        "soft_open_neq_fq": true,
    }))
}

/// Soft-OPEN R4: catalog plot roles per rule (no historian read) for SPA menus.
pub fn plots_by_rule_catalog() -> Result<Value> {
    let reg = load_reg()?;
    let mut rules = Vec::with_capacity(reg.rules.len());
    for rule in &reg.rules {
        let roles = catalog_plot_roles(rule);
        rules.push(json!({
            "rule_id": rule.rule_id,
            "aliases": rule.aliases,
            "roles": roles,
            "role_count": roles.len(),
            "max_roles": LEAN_PLOT_MAX_ROLES,
            "equipment_kinds": rule.equipment_kinds,
        }));
    }
    Ok(json!({
        "ok": true,
        "engine": TS_ENGINE,
        "count": rules.len(),
        "lean_budget": {
            "max_roles": LEAN_PLOT_MAX_ROLES,
            "default_points": LEAN_PLOT_DEFAULT_POINTS,
            "hard_cap_points": LEAN_PLOT_HARD_CAP,
        },
        "rules": rules,
        "soft_open_neq_fq": true,
        "note": "Soft-OPEN catalog plot roles — Soft-OPEN ≠ FQ",
    }))
}

/// Soft-OPEN #1278: package seed writes `equip.role`; SPARQL / opaque IRIs often
/// carry the CSV **column** (`SAT`). Build candidate Timescale keys so history
/// lookup does not return 0 when column ≠ role.
pub fn candidate_openfdd_keys_for_point(
    building_id: &str,
    equipment_id: &str,
    point_key: &str,
) -> Vec<String> {
    let eq = equipment_id.trim();
    let pk = point_key.trim();
    if eq.is_empty() || pk.is_empty() {
        return Vec::new();
    }
    let mut keys = Vec::new();
    let mut push = |suffix: &str| {
        if suffix.is_empty() {
            return;
        }
        let k = format!("{eq}.{suffix}");
        if !keys.iter().any(|x| x == &k) {
            keys.push(k);
        }
    };
    push(pk);
    let lower = pk.to_ascii_lowercase();
    if lower != pk {
        push(&lower);
    }
    let norm = fdd_core::normalize_role(pk);
    push(&norm);
    if let Some(role) = role_from_package_column(building_id, eq, pk) {
        push(&role);
        push(&fdd_core::normalize_role(&role));
        push(&fdd_core::haystack_point_to_role(&role));
    }
    keys
}

/// Invert package mapping `column → role` (and haystack `role → column`) for one equip.
fn role_from_package_column(
    building_id: &str,
    equipment_id: &str,
    point_key: &str,
) -> Option<String> {
    let inv = open_fdd_edge_prototype::csv_ingest::package::get_package_mapping_handler(
        building_id,
        Some(equipment_id),
    );
    let equips = inv.get("equipment")?.as_array()?;
    for eq in equips {
        if eq.get("equipment_id").and_then(Value::as_str) != Some(equipment_id) {
            continue;
        }
        if let Some(cols) = eq.get("columns").and_then(Value::as_array) {
            for row in cols {
                let col = row.get("column").and_then(Value::as_str).unwrap_or("");
                if col.eq_ignore_ascii_case(point_key) {
                    let role = row.get("role").and_then(Value::as_str).unwrap_or("");
                    if !role.is_empty() {
                        return Some(role.to_string());
                    }
                }
            }
        }
        if let Some(roles) = eq.get("roles").and_then(Value::as_object) {
            for (col, role_v) in roles {
                if col.eq_ignore_ascii_case(point_key) {
                    if let Some(role) = role_v.as_str().filter(|s| !s.is_empty()) {
                        return Some(role.to_string());
                    }
                }
            }
            // Haystack-style map: role/tag → CSV column.
            for (hs_or_role, col_v) in roles {
                if col_v
                    .as_str()
                    .is_some_and(|c| c.eq_ignore_ascii_case(point_key))
                {
                    return Some(hs_or_role.clone());
                }
            }
        }
    }
    None
}

/// Soft-OPEN R5: bounded Timescale history for an opaque point.
/// Tries column and role key candidates (#1278) — does not invent keys via `split_part`.
pub async fn opaque_point_history_softopen(
    building_id: &str,
    openfdd_key: &str,
    max_points: usize,
) -> Result<Value> {
    let bid = building_id.trim();
    let key = openfdd_key.trim();
    if bid.is_empty() || key.is_empty() {
        return Ok(json!({
            "ok": false,
            "error": "building_id and openfdd_key required",
            "soft_open_neq_fq": true,
        }));
    }
    let limit = max_points.clamp(1, 2000) as i64;
    let tsdb = Tsdb::connect_from_env().await?;
    // The stored key is opaque. Read it directly before any column/role fallback.
    let exact = sqlx::query(
        r#"
        SELECT ts, openfdd_key, val
        FROM sample
        WHERE site_id = $1 AND openfdd_key = $2
        ORDER BY ts DESC
        LIMIT $3
        "#,
    )
    .bind(bid)
    .bind(key)
    .bind(limit)
    .fetch_all(tsdb.pool())
    .await
    .context("opaque_point_history_softopen")?;
    let (rows, candidates) = if !exact.is_empty() {
        (exact, vec![key.to_string()])
    } else if let Some((equipment_id, point_key)) = key.split_once('.') {
        let candidates = candidate_openfdd_keys_for_point(bid, equipment_id, point_key);
        let rows = sqlx::query(
            r#"
            SELECT s.ts, s.openfdd_key, s.val
            FROM sample s
            JOIN authorized_series a
              ON a.site_id = s.site_id AND a.openfdd_key = s.openfdd_key
            WHERE s.site_id = $1 AND s.openfdd_key = ANY($2)
            ORDER BY s.ts DESC
            LIMIT $3
            "#,
        )
        .bind(bid)
        .bind(&candidates)
        .bind(limit)
        .fetch_all(tsdb.pool())
        .await
        .context("opaque_point_history_softopen")?;
        (rows, candidates)
    } else {
        (exact, vec![key.to_string()])
    };
    let resolved_key = rows
        .first()
        .and_then(|r| r.try_get::<String, _>("openfdd_key").ok())
        .unwrap_or_else(|| key.to_string());
    let mut samples = Vec::with_capacity(rows.len());
    for r in rows.into_iter().rev() {
        let ts: DateTime<Utc> = r.get("ts");
        let val: Option<f64> = r.try_get::<Option<f64>, _>("val").ok().flatten();
        samples.push(json!({
            "ts": ts.to_rfc3339(),
            "val": val,
        }));
    }
    Ok(json!({
        "ok": true,
        "building_id": bid,
        "openfdd_key": resolved_key,
        "requested_openfdd_key": key,
        "candidate_openfdd_keys": candidates,
        "point_count": samples.len(),
        "max_points": limit,
        "samples": samples,
        "engine": TS_ENGINE,
        "source": "timescale_sample",
        "soft_open_neq_fq": true,
        "note": "Soft-OPEN opaque point history; column≠role candidates per #1278 — Soft-OPEN ≠ FQ",
    }))
}

/// Soft-OPEN R8a: tip-safe **read-only** schema/contract probe (no migrator apply, no volume destroy).
/// Reports live `seed_meta.schema_version` when present + pinned `sql/contract/manifest.json`.
pub async fn schema_contract_softopen() -> Result<Value> {
    let contract_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../sql/contract/manifest.json")
        .canonicalize()
        .unwrap_or_else(|_| PathBuf::from("sql/contract/manifest.json"));
    let (pinned_version, pack_sha, soft_open_flag) = match std::fs::read_to_string(&contract_path) {
        Ok(raw) => {
            let v: Value = serde_json::from_str(&raw).unwrap_or(json!({}));
            (
                v.get("contract_version")
                    .and_then(|x| x.as_str())
                    .unwrap_or("unknown")
                    .to_string(),
                v.get("pack_sha256")
                    .and_then(|x| x.as_str())
                    .map(|s| s.to_string()),
                v.get("soft_open_neq_fq")
                    .and_then(|x| x.as_bool())
                    .unwrap_or(true),
            )
        }
        Err(e) => (format!("unreadable:{e}"), None, true),
    };

    let mut seed_schema: Option<String> = None;
    let mut seed_present = false;
    let mut seed_error: Option<String> = None;
    match Tsdb::connect_from_env().await {
        Ok(tsdb) => match sqlx::query(
            r#"
            SELECT value FROM seed_meta WHERE key = 'schema_version' LIMIT 1
            "#,
        )
        .fetch_optional(tsdb.pool())
        .await
        {
            Ok(Some(row)) => {
                seed_present = true;
                seed_schema = row.try_get::<String, _>("value").ok();
            }
            Ok(None) => {
                seed_present = false;
            }
            Err(e) => {
                seed_error = Some(e.to_string());
            }
        },
        Err(e) => {
            seed_error = Some(e.to_string());
        }
    }

    Ok(json!({
        "ok": true,
        "probe": "schema_contract_softopen",
        "engine": TS_ENGINE,
        "seed_meta": {
            "present": seed_present,
            "schema_version": seed_schema,
            "error": seed_error,
        },
        "pinned_contract": {
            "contract_version": pinned_version,
            "pack_sha256": pack_sha,
            "path": contract_path.display().to_string(),
            "soft_open_neq_fq": soft_open_flag,
        },
        "migrator": {
            "applied": false,
            "note": "Soft-OPEN tip-safe read-only probe — migrator ≠ CREATE IF NOT EXISTS; no volume destroy",
        },
        "soft_open_neq_fq": true,
        "note": "Soft-OPEN R8a schema/contract read — Soft-OPEN ≠ FQ bootstrap/migrator proof",
    }))
}

/// Soft-OPEN write-once: reuse a complete active generation. A partial, failed,
/// scoped, dirty, or legacy folder is not a cache hit.
pub async fn cached_run_all_if_present(building_id: &str) -> Option<Value> {
    if crate::timescale_historian::historian_is_timescale() {
        let tsdb = match fdd_tsdb::Tsdb::connect_from_env().await {
            Ok(tsdb) => tsdb,
            Err(_) => return None,
        };
        let manifest = crate::fdd_registry_persist::active_generation_manifest(&tsdb, building_id)
            .await
            .ok()
            .flatten()?;
        if manifest.get("run_status").and_then(Value::as_str) != Some("complete") {
            return None;
        }
        if manifest.get("cohort").and_then(Value::as_str) == Some("scoped") {
            return None;
        }
        if manifest.get("dirty_reason").is_some() {
            return None;
        }
        let stored = manifest
            .get("rule_set_hash")
            .and_then(Value::as_str)
            .unwrap_or("");
        if stored.is_empty()
            || stored != open_fdd_edge_prototype::fdd::registry_api::rule_set_hash_for_readiness()
        {
            return None;
        }
        let rows = crate::fdd_registry_persist::active_generation_rows(&tsdb, building_id)
            .await
            .ok()?;
        let stored_count = manifest
            .get("result_count")
            .and_then(Value::as_u64)
            .unwrap_or(0);
        if stored_count != rows.len() as u64 {
            return None;
        }
        let mut body = manifest;
        if let Some(obj) = body.as_object_mut() {
            obj.insert("results".into(), {
                let mut flat = Vec::new();
                for (rule_id, row) in rows {
                    let mut cloned = row.clone();
                    if let Some(o) = cloned.as_object_mut() {
                        o.insert("rule_id".into(), json!(rule_id));
                    }
                    flat.push(cloned);
                }
                Value::Array(flat)
            });
        }
        if let Some(obj) = body.as_object_mut() {
            obj.insert("engine".into(), json!(TS_ENGINE));
            obj.insert("historian".into(), json!("timescale"));
            obj.insert("skipped_recompute".into(), json!(true));
            obj.insert("ok".into(), json!(true));
            obj.insert(
                "message".into(),
                json!(
                    "FDD results already persisted for this site — UI should read records. \
                     Use force_new_data=true only after new historian samples, \
                     or run a single rule_id from Lab / rule tuning."
                ),
            );
        }
        return Some(body);
    }
    let mut body = open_fdd_edge_prototype::fdd::registry_api::reusable_complete_run(building_id)?;
    if let Some(obj) = body.as_object_mut() {
        obj.insert("engine".into(), json!(TS_ENGINE));
        obj.insert("historian".into(), json!("timescale"));
        obj.insert("skipped_recompute".into(), json!(true));
        obj.insert("ok".into(), json!(true));
        obj.insert(
            "message".into(),
            json!(
                "FDD results already on file for this site — UI should read records. \
                 Use force_new_data=true only after new historian samples, \
                 or run a single rule_id from Lab / rule tuning."
            ),
        );
    }
    Some(body)
}

/// Rewrite aggregated cookbook SQL into a per-timestamp confirmed_fault series.
///
/// Registry runs persist equipment-level fault_hours. Trend charts need the
/// swim-lane bool on each history timestamp.
fn rewrite_rule_sql_to_fault_series(sql: &str, equipment_id: &str) -> Option<String> {
    if !safe_ident(equipment_id) {
        return None;
    }
    let sql = sql.trim().trim_end_matches(';');
    let lower = sql.to_ascii_lowercase();
    if !lower.contains("final as") || !lower.contains("from ranked") {
        return None;
    }
    if !lower.contains("fault_hours") {
        return None;
    }
    let final_at = lower.find("final as")?;
    let select_at = lower.rfind("select")?;
    if select_at <= final_at || !lower[select_at..].contains("fault_hours") {
        return None;
    }
    let mut head = sql[..select_at].to_string();
    let head_lower = head.to_ascii_lowercase();
    if let Some(rel_final) = head_lower[final_at..].find("final as (") {
        let body_start = final_at + rel_final + "final as (".len();
        let body_slice = &head_lower[body_start..];
        let from_ranked = body_slice.find("from ranked")?;
        let final_body = &head_lower[body_start..body_start + from_ranked];
        if !final_body.contains("timestamp_utc") {
            if let Some(eq_rel) = final_body.find("equipment_id") {
                let abs = body_start + eq_rel;
                let after = &head[abs..];
                if let Some(comma_rel) = after.find(',') {
                    let insert_at = abs + comma_rel + 1;
                    head.insert_str(insert_at, "\n    timestamp_utc,");
                }
            }
        }
    }
    Some(format!(
        "{head}SELECT equipment_id, timestamp_utc, confirmed AS confirmed_fault\n\
         FROM final\n\
         WHERE equipment_id = '{equipment_id}'\n\
         ORDER BY timestamp_utc"
    ))
}

fn history_roles_for_rule(rule: &RuleSpec) -> Vec<String> {
    let mut role_set: BTreeSet<String> = rule.required_roles.iter().cloned().collect();
    for role in &rule.optional_roles {
        role_set.insert(role.clone());
    }
    for extra in [
        "fan_status",
        "fan_cmd",
        "occ_mode",
        "oa_t",
        "web_oa_t",
        "chw_supply_t",
        "chw_return_t",
        "chw_flow",
        "chw_dp",
        "chw_pump_cmd",
        "pump_status",
        "chiller_status",
        "chiller_current",
        "chiller_amps",
        "chiller_power",
    ] {
        if rule.required_roles.iter().any(|r| r == extra)
            || rule.optional_roles.iter().any(|r| r == extra)
            || matches!(extra, "fan_status" | "fan_cmd" | "occ_mode")
        {
            role_set.insert(extra.into());
        }
    }
    role_set.into_iter().filter(|r| safe_ident(r)).collect()
}

fn ts_key(ts: DateTime<Utc>) -> String {
    ts.to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

async fn load_live_confirmed_fault(
    tsdb: &Tsdb,
    reg: &RuleRegistry,
    rule: &RuleSpec,
    building_id: &str,
    equipment_id: &str,
    window_start: Option<&str>,
    window_end: Option<&str>,
) -> Result<HashMap<String, bool>> {
    if rule_is_metric(rule) || !safe_ident(equipment_id) {
        return Ok(HashMap::new());
    }
    // Poll sizes row-framed detection windows only. Confirmation is
    // CONFIRM_SECONDS of eligible elapsed time inside the rendered SQL.
    let rendered = render_rule_sql(
        reg,
        rule,
        300.0,
        rule.confirm_seconds,
        building_id,
        Some(equipment_id),
        None,
    )?;
    let Some(series_sql) = rewrite_rule_sql_to_fault_series(&rendered, equipment_id) else {
        return Ok(HashMap::new());
    };
    let roles = history_roles_for_rule(rule);
    let mut tx = tsdb.pool().begin().await?;
    ensure_history_table(&mut tx, &roles).await?;
    let n = fill_history_for_equipment(
        &mut tx,
        building_id,
        equipment_id,
        &roles,
        window_start,
        window_end,
        None,
    )
    .await?;
    if n == 0 {
        let _ = tx.rollback().await;
        return Ok(HashMap::new());
    }
    match crate::sql_pack::prepare_rule_inputs(
        &mut tx,
        building_id,
        window_start,
        window_end,
        &series_sql,
        true,
    )
    .await
    {
        Ok(crate::sql_pack::InputGate::Ready(_)) => {}
        Ok(crate::sql_pack::InputGate::Stop(stop)) => {
            let _ = tx.rollback().await;
            if stop.status == "SCHEMA_INCOMPATIBLE" {
                return Err(anyhow!("{}", stop.notes));
            }
            return Ok(HashMap::new());
        }
        Err(err) => {
            let _ = tx.rollback().await;
            return Err(err);
        }
    }
    let rows = sqlx::query(&series_sql)
        .fetch_all(&mut *tx)
        .await
        .context("confirmed_fault series")?;
    let _ = tx.rollback().await;
    let mut map = HashMap::new();
    for row in rows {
        let Some(ts) = row
            .try_get::<DateTime<Utc>, _>("timestamp_utc")
            .ok()
            .map(ts_key)
        else {
            continue;
        };
        let flag = row
            .try_get::<i32, _>("confirmed_fault")
            .ok()
            .or_else(|| {
                row.try_get::<i64, _>("confirmed_fault")
                    .ok()
                    .map(|v| v as i32)
            })
            .unwrap_or(0)
            != 0;
        map.insert(ts, flag);
    }
    Ok(map)
}

#[cfg(test)]
pub(crate) async fn preview_confirmed_fault_for_rule(
    building_id: &str,
    equipment_id: &str,
    rule_id: &str,
) -> Result<HashMap<String, bool>> {
    let reg = load_reg()?;
    let rule = reg
        .rules
        .iter()
        .find(|rule| rule.rule_id == rule_id)
        .ok_or_else(|| anyhow!("missing rule {rule_id}"))?;
    let tsdb = Tsdb::connect_from_env().await?;
    load_live_confirmed_fault(&tsdb, &reg, rule, building_id, equipment_id, None, None).await
}

fn load_confirmed_fault_hint(
    building_id: &str,
    equipment_id: &str,
    rule_id: &str,
) -> Result<HashMap<String, bool>> {
    let Some(body) =
        open_fdd_edge_prototype::fdd::registry_api::active_rule_result_body(building_id, rule_id)
    else {
        return Ok(HashMap::new());
    };
    let mut map = HashMap::new();
    // Preferred: top-level per-sample series.
    if let Some(series) = body.get("fault_series").and_then(|v| v.as_array()) {
        for row in series {
            let eq = row
                .get("equipment_id")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if eq != equipment_id {
                continue;
            }
            let ts = row
                .get("timestamp_utc")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let flag = row
                .get("confirmed_fault")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            if !ts.is_empty() {
                map.insert(ts.to_string(), flag);
            }
        }
    }
    Ok(map)
}

/// Soft-OPEN P0-3: fill plot `fault_hours` from the on-file rule result row.
fn load_result_fault_hours(building_id: &str, equipment_id: &str, rule_id: &str) -> Option<f64> {
    let body =
        open_fdd_edge_prototype::fdd::registry_api::active_rule_result_body(building_id, rule_id)?;
    body.get("rows")
        .and_then(Value::as_array)?
        .iter()
        .find(|row| row.get("equipment_id").and_then(Value::as_str) == Some(equipment_id))
        .and_then(|row| row.get("fault_hours").and_then(Value::as_f64))
}

fn session_override_for_rule(
    payload: &Value,
    rule_id: &str,
) -> Option<std::collections::HashMap<String, f64>> {
    let params = payload.get("params")?.as_object()?;
    let rule_params = params.get(rule_id)?.as_object()?;
    let mut out = std::collections::HashMap::new();
    for (k, v) in rule_params {
        if let Some(n) = v.as_f64().or_else(|| v.as_u64().map(|u| u as f64)) {
            if !n.is_finite() {
                continue;
            }
            // UI sends confirm_min. The catalog key is confirm_seconds.
            // Leaving confirm_min in the map makes effective_param_strings
            // reject the whole bag, so MODE_DELAY_* placeholders stay in the SQL.
            if k == "confirm_min" {
                out.insert("confirm_seconds".into(), n * 60.0);
                continue;
            }
            out.insert(k.clone(), n);
        }
    }
    if out.is_empty() {
        None
    } else {
        Some(out)
    }
}

fn render_rule_sql(
    reg: &RuleRegistry,
    rule: &RuleSpec,
    poll: f64,
    confirm: u32,
    building_id: &str,
    equipment_id: Option<&str>,
    session_override: Option<&std::collections::HashMap<String, f64>>,
) -> Result<String> {
    let path = rule_sql_path(reg, &rule.sql_file);
    let raw = std::fs::read_to_string(&path)
        .with_context(|| format!("read rule sql {}", path.display()))?;
    let mut params = rule_params(poll, confirm);
    if let Ok(tuning) = load_tuning_profiles(Path::new(&reg.rules_dir)) {
        if let Ok(tuned) = effective_param_strings(
            rule,
            &tuning,
            Some(building_id),
            equipment_id,
            session_override,
        ) {
            for (k, v) in tuned {
                // Catalog confirm_seconds must not wipe the window already
                // applied from confirm_min (including 0).
                if k == "CONFIRM_SECONDS" || k == "CONFIRM_ROWS" {
                    continue;
                }
                params.insert(k, v);
            }
        }
    }
    for (k, v) in rule_params(poll, confirm) {
        params.insert(k, v);
    }
    if rule.rule_id.eq_ignore_ascii_case("OAT-METEO") {
        let bound = web_asof_bound_seconds(&params)?;
        params.insert(
            "WEB_ASOF_BOUND_SECONDS".into(),
            format!("{:.0}", bound.round()),
        );
    }
    Ok(substitute_sql(&raw, &params))
}

fn rule_is_metric(rule: &RuleSpec) -> bool {
    // Diagnostic rules expose fault_hours; metric/utility analytical outputs do not.
    !rule
        .output_columns
        .iter()
        .any(|c| c == "fault_hours" || c == "fault_pct" || c == "fault_samples")
}

/// Rule SQL often yields `fault_hours` as PostgreSQL `numeric` (CASE with `0.0`).
/// sqlx `try_get::<f64>` fails on numeric → Soft-OPEN run-now reported 0h.
/// Cast through a wrapper SELECT so the product path always gets float8.
/// Diagnostic rows also carry covered hours and the elapsed percent so the
/// denominator is eligible time, not a sample count times an assumed poll.
/// Metric rules keep `SELECT *` so fan_runtime_hours / avg_zone_temp survive.
fn wrap_rule_sql(sql_body: &str, rule: &RuleSpec) -> String {
    let inner = sql_body.trim().trim_end_matches(';').trim();
    if rule_is_metric(rule) {
        // CASE expressions with a numeric `0.0` literal come back as PostgreSQL
        // numeric. sqlx `try_get::<f64>` then drops the metric, so cast each
        // declared output the same way diagnostic fault_hours is cast.
        let casts: Vec<String> = rule
            .output_columns
            .iter()
            .filter(|column| safe_ident(column))
            .map(|column| {
                if column == "equipment_id" {
                    "equipment_id::text AS equipment_id".to_string()
                } else {
                    format!("\"{column}\"::double precision AS \"{column}\"")
                }
            })
            .collect();
        if casts.is_empty() {
            format!("SELECT * FROM ({inner}) AS _fdd_rule_q")
        } else {
            let list = casts.join(", ");
            format!("SELECT {list} FROM ({inner}) AS _fdd_rule_q")
        }
    } else {
        format!(
            "SELECT equipment_id::text AS equipment_id, \
             fault_hours::double precision AS fault_hours, \
             covered_hours::double precision AS covered_hours, \
             fault_pct::double precision AS fault_pct \
             FROM ({inner}) AS _fdd_rule_q"
        )
    }
}

/// Columns of the TEMP `history` pivot for one rule.
fn rule_history_roles(rule: &RuleSpec) -> Vec<String> {
    let mut role_set: BTreeSet<String> = rule.required_roles.iter().cloned().collect();
    for r in &rule.optional_roles {
        role_set.insert(r.clone());
    }
    for extra in ["fan_status", "fan_cmd", "occ_mode"] {
        role_set.insert(extra.into());
    }
    for extra in [
        "oa_t",
        "web_oa_t",
        "chw_supply_t",
        "chw_return_t",
        "chw_flow",
        "chw_dp",
    ] {
        if rule.required_roles.iter().any(|r| r == extra)
            || rule.optional_roles.iter().any(|r| r == extra)
        {
            role_set.insert(extra.into());
        }
    }
    role_set.into_iter().filter(|r| safe_ident(r)).collect()
}

fn confirm_seconds_from_payload(payload: &Value, rule: &RuleSpec) -> u32 {
    if let Some(cs) = payload
        .get("confirmation_seconds")
        .and_then(|v| v.as_f64().or_else(|| v.as_u64().map(|u| u as f64)))
        .filter(|v| v.is_finite() && *v >= 0.0)
    {
        return cs.round() as u32;
    }
    if let Some(params) = payload.get("params").and_then(|v| v.as_object()) {
        if let Some(rule_bag) = params.get(&rule.rule_id).and_then(|v| v.as_object()) {
            if let Some(cm) = rule_bag
                .get("confirm_min")
                .and_then(|v| v.as_f64().or_else(|| v.as_u64().map(|u| u as f64)))
                .filter(|v| v.is_finite() && *v >= 0.0)
            {
                return (cm * 60.0).round() as u32;
            }
            if let Some(cs) = rule_bag
                .get("confirm_seconds")
                .or_else(|| rule_bag.get("confirmation_seconds"))
                .and_then(|v| v.as_f64().or_else(|| v.as_u64().map(|u| u as f64)))
                .filter(|v| v.is_finite() && *v >= 0.0)
            {
                return cs.round() as u32;
            }
        }
        if let Some(cs) = params
            .get("confirmation_seconds")
            .or_else(|| params.get("confirm_seconds"))
            .and_then(|v| v.as_f64().or_else(|| v.as_u64().map(|u| u as f64)))
            .filter(|v| v.is_finite() && *v >= 0.0)
        {
            return cs.round() as u32;
        }
        if let Some(cm) = params
            .get("confirm_min")
            .and_then(|v| v.as_f64().or_else(|| v.as_u64().map(|u| u as f64)))
            .filter(|v| v.is_finite() && *v >= 0.0)
        {
            return (cm * 60.0).round() as u32;
        }
    }
    rule.confirm_seconds
}

/// Nominal interval for row-framed detection windows (flatline, mode delay, PID).
/// Fault duration and confirmation integrate eligible timestamp deltas and do
/// not multiply a sample count by this value. An omitted payload stays at 300s.
fn poll_seconds_from_payload(payload: &Value) -> f64 {
    if let Some(ps) = payload
        .get("poll_seconds")
        .and_then(|v| v.as_f64().or_else(|| v.as_u64().map(|u| u as f64)))
        .filter(|v| v.is_finite() && *v > 0.0)
    {
        return ps;
    }
    if let Some(params) = payload.get("params") {
        if let Some(ps) = params
            .get("poll_seconds")
            .and_then(|v| v.as_f64().or_else(|| v.as_u64().map(|u| u as f64)))
            .filter(|v| v.is_finite() && *v > 0.0)
        {
            return ps;
        }
    }
    300.0
}

fn is_chw_plant_role(role: &str) -> bool {
    matches!(
        role,
        "chw_supply_t" | "chw_return_t" | "chw_flow" | "chw_dp" | "chw_supply_sp"
    )
}

fn is_weather_role(role: &str) -> bool {
    matches!(
        role,
        "oa_t"
            | "web_oa_t"
            | "outside_air_temp"
            | "web_outside_air_temp"
            | "web-outside-air-temp"
            | "oat"
            | "oa_rh"
            | "oa_enthalpy"
    )
}

fn row_fault_hours(row: &sqlx::postgres::PgRow) -> f64 {
    if let Ok(v) = row.try_get::<f64, _>("fault_hours") {
        return v;
    }
    if let Ok(Some(v)) = row.try_get::<Option<f64>, _>("fault_hours") {
        return v;
    }
    if let Ok(v) = row.try_get::<i64, _>("fault_hours") {
        return v as f64;
    }
    if let Ok(v) = row.try_get::<i32, _>("fault_hours") {
        return v as f64;
    }
    0.0
}

pub(crate) fn csv_building_root(building_id: &str) -> PathBuf {
    open_fdd_edge_prototype::historian::store::workspace_dir()
        .join("data")
        .join("csv_buildings")
        .join(building_id)
}

/// When OAT-METEO runs, local `oa_t` may come from the site primary reference binding.
#[derive(Clone, Debug)]
pub(crate) struct SiteOatReference {
    pub openfdd_key: String,
    pub equipment_id: String,
    pub selection: String,
}

pub(crate) async fn resolve_site_oa_t_reference(
    pool: &sqlx::PgPool,
    building_id: &str,
) -> Result<Option<SiteOatReference>> {
    let rows = sqlx::query(
        r"SELECT a.openfdd_key, a.equipment_id, pm.portal_point_id
         FROM authorized_series a
         JOIN equipment e
           ON e.building_id = $1 AND e.equipment_id = a.equipment_id
         JOIN point_map pm
           ON pm.site_id = a.site_id AND pm.openfdd_key = a.openfdd_key
         WHERE a.site_id = $1
           AND a.role = 'oa_t'
           AND lower(btrim(coalesce(e.equip_type, ''))) IN ('weather', 'ahu')
         ORDER BY a.openfdd_key",
    )
    .bind(building_id)
    .fetch_all(pool)
    .await
    .context("list site oa_t bindings")?;
    if rows.is_empty() {
        return Ok(None);
    }
    let overlay = open_fdd_edge_prototype::csv_ingest::model_overlay::load_engineer_point_overlay(
        csv_building_root(building_id).as_path(),
    )
    .ok();
    let mut primaries: Vec<(String, String)> = Vec::new();
    let mut all: Vec<(String, String, bool)> = Vec::new();
    for row in rows {
        let key: String = row.try_get("openfdd_key")?;
        let equip: String = row.try_get("equipment_id")?;
        let portal_point_id: Option<String> = row.try_get("portal_point_id")?;
        let is_primary = overlay
            .as_ref()
            .and_then(|store| {
                portal_point_id
                    .as_ref()
                    .and_then(|pid| store.points.get(pid))
                    .map(|entry| entry.primary_reference)
            })
            .unwrap_or(false);
        all.push((key.clone(), equip.clone(), is_primary));
        if is_primary {
            primaries.push((key, equip));
        }
    }
    primaries.sort_by(|a, b| a.0.cmp(&b.0));
    all.sort_by(|a, b| a.0.cmp(&b.0));
    let (openfdd_key, equipment_id, selection) = if let Some((key, eq)) = primaries.first() {
        (key.clone(), eq.clone(), "primary_reference".to_string())
    } else {
        let (key, eq, _) = &all[0];
        (
            key.clone(),
            eq.clone(),
            "default_lowest_binding".to_string(),
        )
    };
    Ok(Some(SiteOatReference {
        openfdd_key,
        equipment_id,
        selection,
    }))
}

pub(crate) fn bas_vs_web_oa_t_config_line(reference: Option<&SiteOatReference>) -> String {
    match reference {
        Some(r) => format!("oa_t_ref={}={}", r.openfdd_key, r.selection),
        None => "oa_t_ref=none".into(),
    }
}

#[derive(Clone)]
pub(crate) struct HistoryFillOptions {
    pub site_oa_t: Option<SiteOatReference>,
}

/// Web weather as-of tolerance shared by OAT-METEO and bas-vs-web-oat analytics.
pub(crate) fn oat_meteo_web_asof_bound_seconds() -> Result<f64> {
    let reg = load_reg()?;
    let rule = reg
        .rules
        .iter()
        .find(|r| r.rule_id == "OAT-METEO")
        .ok_or_else(|| anyhow::anyhow!("OAT-METEO rule missing from FDD registry"))?;
    let confirm = rule.confirm_seconds;
    let mut params = rule_params(300.0, confirm);
    let tuning = load_tuning_profiles(Path::new(&reg.rules_dir))
        .context("load OAT-METEO tuning profiles")?;
    let tuned = effective_param_strings(rule, &tuning, None, None, None)
        .context("resolve OAT-METEO effective param strings")?;
    for (k, v) in tuned {
        if k == "CONFIRM_SECONDS" || k == "CONFIRM_ROWS" {
            continue;
        }
        params.insert(k, v);
    }
    web_asof_bound_seconds(&params)
}

fn web_asof_bound_seconds(params: &std::collections::HashMap<String, String>) -> Result<f64> {
    let cadence = params
        .get("WEB_CADENCE_SECONDS")
        .ok_or_else(|| anyhow::anyhow!("WEB_CADENCE_SECONDS missing from OAT-METEO params"))?
        .parse::<f64>()
        .context("parse WEB_CADENCE_SECONDS")?;
    if !cadence.is_finite() || cadence <= 0.0 {
        return Err(anyhow::anyhow!(
            "WEB_CADENCE_SECONDS must be finite and > 0"
        ));
    }
    let margin = params
        .get("WEB_ASOF_MARGIN_SECONDS")
        .ok_or_else(|| anyhow::anyhow!("WEB_ASOF_MARGIN_SECONDS missing from OAT-METEO params"))?
        .parse::<f64>()
        .context("parse WEB_ASOF_MARGIN_SECONDS")?;
    if !margin.is_finite() || margin < 0.0 {
        return Err(anyhow::anyhow!(
            "WEB_ASOF_MARGIN_SECONDS must be finite and >= 0"
        ));
    }
    Ok(cadence + margin)
}

async fn ensure_history_table(conn: &mut PgConnection, roles: &[String]) -> Result<()> {
    let mut cols = String::from("equipment_id text not null, timestamp_utc timestamptz not null");
    for r in roles {
        cols.push_str(&format!(
            ", {} double precision",
            crate::series_binding::quote_ident(r)
        ));
    }
    sqlx::query(&format!(
        "CREATE TEMP TABLE history ({cols}) ON COMMIT DROP"
    ))
    .execute(&mut *conn)
    .await
    .context("create temp history")?;
    Ok(())
}

async fn fill_history_for_equipment(
    conn: &mut PgConnection,
    building_id: &str,
    equipment_id: &str,
    roles: &[String],
    window_start: Option<&str>,
    window_end: Option<&str>,
    fill: Option<&HistoryFillOptions>,
) -> Result<i64> {
    if roles.is_empty() {
        return Ok(0);
    }
    // Stored samples are metric-c-v2; pivot reads `s.val` without query-time admit.
    // Columns come from the current unique binding. A second key for the same
    // role is left out. Weather and CHW fall back to one stamped equipment,
    // the lexicographically first unique binding, when the target has none.
    // $1..$3 are building, equipment, and roles. Admission binds follow those.
    let mut admit = crate::admitted_sample::AdmitBuilder::after_occupied(3);
    let mut max_cols = String::new();
    let site_oa_key = fill
        .and_then(|opts| opts.site_oa_t.as_ref())
        .map(|r| r.openfdd_key.replace('\'', "''"));
    for role in roles {
        let admitted = admit.admitted_on_sample(role);
        let alias = crate::series_binding::quote_ident(role);
        let role_lit = role.replace('\'', "''");
        let local = if role == "oa_t" {
            if let Some(key_lit) = site_oa_key.as_deref() {
                format!(
                    "MAX({admitted}) FILTER (WHERE a.openfdd_key = '{key_lit}' AND a.role = '{role_lit}')"
                )
            } else {
                format!(
                    "MAX({admitted}) FILTER (WHERE a.equipment_id = $2 AND a.role = '{role_lit}' \
                       AND (SELECT count(*) FROM authorized_series c \
                            WHERE c.site_id = a.site_id AND c.equipment_id = a.equipment_id \
                              AND c.role = a.role) = 1)"
                )
            }
        } else {
            format!(
                "MAX({admitted}) FILTER (WHERE a.equipment_id = $2 AND a.role = '{role_lit}' \
                   AND (SELECT count(*) FROM authorized_series c \
                        WHERE c.site_id = a.site_id AND c.equipment_id = a.equipment_id \
                          AND c.role = a.role) = 1)"
            )
        };
        if is_chw_plant_role(role) {
            max_cols.push_str(&format!(
                ", COALESCE({local}, \
                   MAX({admitted}) FILTER (WHERE a.role = '{role_lit}' \
                     AND a.equipment_id = ( \
                       SELECT e.equipment_id FROM equipment e \
                       JOIN authorized_series w \
                         ON w.site_id = e.building_id AND w.equipment_id = e.equipment_id \
                        AND w.role = '{role_lit}' \
                       WHERE e.building_id = $1 AND e.equipment_id <> $2 \
                         AND lower(coalesce(e.equip_type, '')) IN ( \
                           'chiller', 'chw', 'chwplant', 'chw_plant' \
                         ) \
                         AND (SELECT count(*) FROM authorized_series c \
                              WHERE c.site_id = w.site_id AND c.equipment_id = w.equipment_id \
                                AND c.role = w.role) = 1 \
                       ORDER BY e.equipment_id LIMIT 1 \
                     ))) AS {alias}"
            ));
        } else if is_weather_role(role) {
            max_cols.push_str(&format!(
                ", COALESCE({local}, \
                   MAX({admitted}) FILTER (WHERE a.role = '{role_lit}' \
                     AND a.equipment_id = ( \
                       SELECT e.equipment_id FROM equipment e \
                       JOIN authorized_series w \
                         ON w.site_id = e.building_id AND w.equipment_id = e.equipment_id \
                        AND w.role = '{role_lit}' \
                       WHERE e.building_id = $1 AND e.equipment_id <> $2 \
                         AND lower(coalesce(e.equip_type, '')) = 'weather' \
                         AND (SELECT count(*) FROM authorized_series c \
                              WHERE c.site_id = w.site_id AND c.equipment_id = w.equipment_id \
                                AND c.role = w.role) = 1 \
                       ORDER BY e.equipment_id LIMIT 1 \
                     ))) AS {alias}"
            ));
        } else {
            max_cols.push_str(&format!(", {local} AS {alias}"));
        }
    }
    // Soft-OPEN R6: honor half-open [start, end) when caller supplies window.
    let mut window_sql = String::new();
    if let Some(start) = window_start.map(str::trim).filter(|s| !s.is_empty()) {
        if safe_rfc3339(start) {
            window_sql.push_str(&format!(" AND s.ts >= '{start}'::timestamptz"));
        }
    }
    if let Some(end) = window_end.map(str::trim).filter(|s| !s.is_empty()) {
        if safe_rfc3339(end) {
            window_sql.push_str(&format!(" AND s.ts < '{end}'::timestamptz"));
        }
    }
    // The time spine is this equipment. A site-wide join inserts another
    // unit's timestamps as null holds and shortens forward intervals
    // (a 5-minute fault series becomes the 1-minute cadence of its neighbor).
    // Weather and CHW add only the one fallback equipment already chosen
    // for that role. An ambiguous role adds no timestamps.
    let mut spine = String::from("a.equipment_id = $2");
    if let Some(site_oa) = fill.and_then(|opts| opts.site_oa_t.as_ref()) {
        if roles.iter().any(|r| r == "oa_t") {
            let key_lit = site_oa.openfdd_key.replace('\'', "''");
            let eq_lit = site_oa.equipment_id.replace('\'', "''");
            spine.push_str(&format!(
                " OR (a.role = 'oa_t' AND a.openfdd_key = '{key_lit}' AND a.equipment_id = '{eq_lit}')"
            ));
        }
    }
    for role in roles {
        let role_lit = role.replace('\'', "''");
        let type_filter = if is_weather_role(role) {
            "lower(coalesce(e.equip_type, '')) = 'weather'"
        } else if is_chw_plant_role(role) {
            "lower(coalesce(e.equip_type, '')) IN ( \
               'chiller', 'chw', 'chwplant', 'chw_plant' \
             )"
        } else {
            continue;
        };
        spine.push_str(&format!(
            " OR (a.role = '{role_lit}' AND a.equipment_id = ( \
               SELECT e.equipment_id FROM equipment e \
               JOIN authorized_series w \
                 ON w.site_id = e.building_id AND w.equipment_id = e.equipment_id \
                AND w.role = '{role_lit}' \
               WHERE e.building_id = $1 AND e.equipment_id <> $2 \
                 AND {type_filter} \
                 AND (SELECT count(*) FROM authorized_series c \
                      WHERE c.site_id = w.site_id AND c.equipment_id = w.equipment_id \
                        AND c.role = w.role) = 1 \
               ORDER BY e.equipment_id LIMIT 1))"
        ));
    }
    let insert_cols = roles
        .iter()
        .map(|r| crate::series_binding::quote_ident(r))
        .collect::<Vec<_>>()
        .join(", ");
    let binding_guard = if let Some(site_oa) = fill.and_then(|opts| opts.site_oa_t.as_ref()) {
        let key_lit = site_oa.openfdd_key.replace('\'', "''");
        let eq_lit = site_oa.equipment_id.replace('\'', "''");
        format!(
            "AND (
               (a.role = 'oa_t' AND a.openfdd_key = '{key_lit}' AND a.equipment_id = '{eq_lit}')
               OR (SELECT count(*) FROM authorized_series c
                   WHERE c.site_id = a.site_id AND c.equipment_id = a.equipment_id
                     AND c.role = a.role) = 1
             )"
        )
    } else {
        "AND (SELECT count(*) FROM authorized_series c
             WHERE c.site_id = a.site_id AND c.equipment_id = a.equipment_id
               AND c.role = a.role) = 1"
            .to_string()
    };
    let sql = format!(
        r#"
INSERT INTO history (equipment_id, timestamp_utc, {insert_cols})
SELECT $2, s.ts {max_cols}
FROM sample s
JOIN authorized_series a
  ON a.site_id = s.site_id AND a.openfdd_key = s.openfdd_key
WHERE s.site_id = $1
  AND a.role = ANY($3)
  AND ({spine})
  {binding_guard}{window_sql}
GROUP BY s.ts
"#
    );
    let res = crate::admitted_sample::apply_binds(
        sqlx::query(&sql)
            .bind(building_id)
            .bind(equipment_id)
            .bind(roles),
        admit.binds(),
    )
    .execute(&mut *conn)
    .await
    .context("fill history")?;
    Ok(res.rows_affected() as i64)
}

/// Soft-OPEN R6: required roles must have ≥1 non-null sample in TEMP history.
async fn missing_required_roles(
    conn: &mut PgConnection,
    required: &[String],
) -> Result<Vec<String>> {
    let mut missing = Vec::new();
    for role in required {
        if !safe_ident(role) {
            missing.push(role.clone());
            continue;
        }
        let sql = format!("SELECT COUNT(*)::bigint AS n FROM history WHERE \"{role}\" IS NOT NULL");
        let n: i64 = sqlx::query_scalar(&sql)
            .fetch_one(&mut *conn)
            .await
            .unwrap_or(0);
        if n == 0 {
            missing.push(role.clone());
        }
    }
    Ok(missing)
}

fn safe_rfc3339(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 40
        && s.chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | ':' | 'T' | 'Z' | '+' | '.'))
}

fn targets_for_rule(
    equipment: &[(String, Option<String>)],
    kinds: &[&str],
    equipment_filter: Option<&str>,
) -> Vec<(String, Option<String>)> {
    equipment
        .iter()
        .filter(|(id, equip_type)| {
            if kinds.is_empty() {
                return true;
            }
            if equip_matches_kinds(equip_type.as_deref(), kinds) {
                return true;
            }
            equipment_filter == Some(id.as_str()) && equip_type.is_none()
        })
        .cloned()
        .collect()
}

fn rule_file(
    rule_id: &str,
    building_id: &str,
    rows: Vec<Value>,
) -> open_fdd_edge_prototype::fdd::registry_api::RunRuleFile {
    open_fdd_edge_prototype::fdd::registry_api::RunRuleFile {
        rule_id: rule_id.to_string(),
        body: json!({
            "rule_id": rule_id,
            "engine": TS_ENGINE,
            "building_id": building_id,
            "rows": rows,
        }),
    }
}

fn metric_unit_for_column(column: &str) -> (&'static str, &'static str) {
    if let Some(quantity) = crate::si_api_response::metric_column_quantity(column) {
        if let Ok(contract) = fdd_core::units_contract::MetricUnitsContract::load_embedded() {
            if let Ok(unit) = contract.canonical_unit(quantity) {
                return (quantity, unit);
            }
        }
    }
    match column {
        "fan_runtime_hours" | "total_hours" => ("other", "h"),
        "comfort_pct" => ("percent", "percent_0_100"),
        _ => ("other", ""),
    }
}

fn numeric_column_map(row: &sqlx::postgres::PgRow) -> serde_json::Map<String, Value> {
    let mut values = serde_json::Map::new();
    for column in row.columns() {
        let name = column.name();
        if name == "equipment_id" || !safe_ident(name) {
            continue;
        }
        if let Some(number) = row_optional_f64(row, name) {
            values.insert(name.to_string(), json!(number));
        }
    }
    values
}

/// Observed first/last TEMP `history` timestamps for the equipment just filled.
/// Empty history yields `(None, None)` — callers must not invent a window.
async fn history_observed_bounds(
    conn: &mut PgConnection,
) -> Result<(Option<String>, Option<String>)> {
    let row = sqlx::query(
        "SELECT min(timestamp_utc) AS first_ts, max(timestamp_utc) AS last_ts FROM history",
    )
    .fetch_one(&mut *conn)
    .await
    .context("history observed bounds")?;
    let first = row
        .try_get::<Option<DateTime<Utc>>, _>("first_ts")
        .ok()
        .flatten()
        .map(|ts| ts.to_rfc3339());
    let last = row
        .try_get::<Option<DateTime<Utc>>, _>("last_ts")
        .ok()
        .flatten()
        .map(|ts| ts.to_rfc3339());
    Ok((first, last))
}

struct MetricWindowFacts<'a> {
    requested_start: Option<&'a str>,
    requested_end: Option<&'a str>,
    observed_start: Option<&'a str>,
    observed_end: Option<&'a str>,
    watermark: Option<&'a str>,
    sample_rows: i64,
    config_fingerprint: &'a str,
}

/// Metric window / coverage / provenance returned to the UI.
///
/// `window.start` / `window.end` are the **effective** bounds actually evaluated
/// (observed historian span). Requested bounds stay separate. When the historian
/// did not supply observed timestamps, start/end stay null and `unknown` is true
/// — never invent a window from the request alone.
fn metric_payload(
    rule: &RuleSpec,
    values: &serde_json::Map<String, Value>,
    facts: MetricWindowFacts<'_>,
) -> Value {
    let name = rule
        .output_columns
        .iter()
        .find(|column| column.as_str() != "equipment_id")
        .map(String::as_str)
        .unwrap_or("");
    let value = if name.is_empty() {
        Value::Null
    } else {
        values.get(name).cloned().unwrap_or(Value::Null)
    };
    let (quantity, unit_label) = metric_unit_for_column(name);
    let si_value = match (&value, name.is_empty()) {
        (_, true) => value,
        (Value::Number(n), false) => {
            if let Some(raw) = n.as_f64() {
                if let Some(qty) = crate::si_api_response::metric_column_quantity(name) {
                    let src = crate::si_api_response::default_pack_source_unit(qty);
                    if !src.is_empty() {
                        if let Ok(si) = crate::si_api_response::value_to_si(qty, src, raw) {
                            json!(si.value)
                        } else {
                            value
                        }
                    } else {
                        value
                    }
                } else {
                    value
                }
            } else {
                value
            }
        }
        _ => value,
    };
    let unknown = facts.observed_start.is_none() || facts.observed_end.is_none();
    json!({
        "name": name,
        "value": si_value,
        "unit": unit_label,
        "quantity": quantity,
        "window": {
            "start": if unknown { Value::Null } else { json!(facts.observed_start) },
            "end": if unknown { Value::Null } else { json!(facts.observed_end) },
            "requested_start": facts.requested_start,
            "requested_end": facts.requested_end,
            "observed_start": facts.observed_start,
            "observed_end": facts.observed_end,
            "watermark": facts.watermark,
            "unknown": unknown,
        },
        "coverage": { "sample_rows": facts.sample_rows },
        "provenance": {
            "source": "timescale",
            "config_fingerprint": facts.config_fingerprint,
            "watermark": facts.watermark,
        },
    })
}

fn config_fingerprint(payload: &Value, poll: f64) -> String {
    json!({
        "poll_seconds": poll,
        "confirmation_seconds": payload.get("confirmation_seconds"),
        "params": payload.get("params"),
        "start": payload.get("start").or_else(|| payload.get("window_start")),
        "end": payload.get("end").or_else(|| payload.get("window_end")),
        "rule_ids": payload.get("rule_ids"),
        "equipment_id": payload.get("equipment_id"),
    })
    .to_string()
}

async fn historian_watermark(tsdb: &Tsdb, building_id: &str) -> Option<String> {
    let row = sqlx::query("SELECT max(ts) AS watermark FROM sample WHERE site_id = $1")
        .bind(building_id)
        .fetch_optional(tsdb.pool())
        .await
        .ok()??;
    row.try_get::<Option<DateTime<Utc>>, _>("watermark")
        .ok()
        .flatten()
        .map(|ts| ts.to_rfc3339())
}

/// Analytics cache input. A failed model read and a failed watermark read stay
/// separate so a watermark failure can still name the model it did read.
#[derive(Debug)]
pub(crate) struct AnalyticsCacheInput {
    pub model_revision: Result<String, String>,
    pub watermark: Result<ScopedWatermark, String>,
}

#[derive(Debug)]
pub(crate) struct ScopedWatermark {
    pub order: u64,
    pub utc: String,
    pub coverage: String,
}

/// Analytics SQL pack plus the FDD pack fingerprint. A missing pack is an error.
pub(crate) fn analytics_cache_sql_pack() -> Result<String, String> {
    let fdd = fdd_sql_pack_fingerprint()?;
    Ok(format!(
        "analytics={};fdd={fdd}",
        crate::timescale_analytics::analytics_sql_pack_identity()
    ))
}

fn fdd_sql_pack_fingerprint() -> Result<String, String> {
    let root = sql_root_for_registry();
    static CACHE: std::sync::Mutex<Option<(PathBuf, String)>> = std::sync::Mutex::new(None);
    let mut guard = CACHE.lock().unwrap_or_else(|err| err.into_inner());
    if let Some((cached, digest)) = guard.as_ref() {
        if cached == &root {
            return Ok(digest.clone());
        }
    }
    let digest = hash_fdd_pack(&root)?;
    *guard = Some((root, digest.clone()));
    Ok(digest)
}

fn hash_fdd_pack(root: &Path) -> Result<String, String> {
    let registry = root.join("registry.yaml");
    let rules = root.join("postgres").join("rules");
    if !registry.is_file() {
        return Err(format!(
            "sql pack registry missing at {}",
            registry.display()
        ));
    }
    if !rules.is_dir() {
        return Err(format!("sql pack rules missing at {}", rules.display()));
    }
    let mut names = Vec::new();
    let rd = std::fs::read_dir(&rules).map_err(|err| format!("read sql pack: {err}"))?;
    for ent in rd {
        let ent = ent.map_err(|err| format!("read sql pack entry: {err}"))?;
        let path = ent.path();
        if path.extension().and_then(|ext| ext.to_str()) == Some("sql") {
            names.push(path);
        }
    }
    names.sort();
    let mut hasher = Sha256::new();
    hasher.update(b"fdd-sql-pack-v1");
    let registry_bytes =
        std::fs::read(&registry).map_err(|err| format!("read sql pack registry: {err}"))?;
    hasher.update((registry_bytes.len() as u64).to_le_bytes());
    hasher.update(&registry_bytes);
    for path in names {
        let bytes = std::fs::read(&path).map_err(|err| format!("read sql pack rule: {err}"))?;
        if let Some(name) = path.file_name().and_then(|name| name.to_str()) {
            hasher.update(name.as_bytes());
        }
        hasher.update((bytes.len() as u64).to_le_bytes());
        hasher.update(&bytes);
    }
    Ok(hex::encode(hasher.finalize()))
}

pub(crate) async fn read_analytics_cache_input_from(
    tsdb: &Tsdb,
    building_id: &str,
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
    equipment_ids: &[String],
) -> AnalyticsCacheInput {
    let model_revision = read_model_revision_string(tsdb, building_id).await;
    let watermark = read_scoped_watermark(tsdb, building_id, start, end, equipment_ids).await;
    AnalyticsCacheInput {
        model_revision,
        watermark,
    }
}

pub async fn read_model_revision_string(tsdb: &Tsdb, building_id: &str) -> Result<String, String> {
    let equipment = sqlx::query(
        r#"
        SELECT equipment_id, COALESCE(equip_type, ''), COALESCE(parent_equipment_id, '')
        FROM equipment
        WHERE building_id = $1
        ORDER BY equipment_id
        "#,
    )
    .bind(building_id)
    .fetch_all(tsdb.pool())
    .await
    .map_err(|err| public_db_error("model revision", &err))?;
    let roles = sqlx::query(
        r#"
        SELECT equipment_id, openfdd_key, role, COALESCE(unit, '')
        FROM role_map
        WHERE building_id = $1
        ORDER BY equipment_id, openfdd_key, role
        "#,
    )
    .bind(building_id)
    .fetch_all(tsdb.pool())
    .await
    .map_err(|err| public_db_error("model revision", &err))?;
    let points = sqlx::query(
        r#"
        SELECT COALESCE(equipment_id, ''), openfdd_key, COALESCE(role, ''),
               COALESCE(unit, ''), haystack_id
        FROM point_map
        WHERE site_id = $1
        ORDER BY openfdd_key, haystack_id
        "#,
    )
    .bind(building_id)
    .fetch_all(tsdb.pool())
    .await
    .map_err(|err| public_db_error("model revision", &err))?;

    let mut hasher = Sha256::new();
    hasher.update(b"openfdd-model-v1");
    for row in &equipment {
        hash_line(
            &mut hasher,
            &format!(
                "equip\t{}\t{}\t{}",
                text_cell(row, 0)?,
                text_cell(row, 1)?,
                text_cell(row, 2)?
            ),
        );
    }
    for row in &roles {
        hash_line(
            &mut hasher,
            &format!(
                "role\t{}\t{}\t{}\t{}",
                text_cell(row, 0)?,
                text_cell(row, 1)?,
                text_cell(row, 2)?,
                text_cell(row, 3)?
            ),
        );
    }
    for row in &points {
        hash_line(
            &mut hasher,
            &format!(
                "point\t{}\t{}\t{}\t{}\t{}",
                text_cell(row, 0)?,
                text_cell(row, 1)?,
                text_cell(row, 2)?,
                text_cell(row, 3)?,
                text_cell(row, 4)?
            ),
        );
    }
    Ok(hex::encode(hasher.finalize()))
}

fn hash_line(hasher: &mut Sha256, line: &str) {
    hasher.update([0xff]);
    hasher.update((line.len() as u64).to_le_bytes());
    hasher.update(line.as_bytes());
}

fn text_cell(row: &sqlx::postgres::PgRow, index: usize) -> Result<String, String> {
    row.try_get::<String, _>(index)
        .map_err(|err| public_db_error("model revision", &err))
}

/// Site window, narrowed to the requested equipment tokens when the caller
/// named them. Comparison is exact equality of the stored key's equipment
/// token (`RTU_01` does not select `RTU_010`). Weather-stamped equipment stays
/// in scope because scatter and other plots read it beside the requested cohort.
async fn read_scoped_watermark(
    tsdb: &Tsdb,
    building_id: &str,
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
    equipment_ids: &[String],
) -> Result<ScopedWatermark, String> {
    let equipment_bind: Option<Vec<String>> = if equipment_ids.is_empty() {
        None
    } else {
        Some(equipment_ids.to_vec())
    };
    let row = sqlx::query(
        r#"
        SELECT
          min(s.ts) AS coverage_start,
          max(s.ts) AS coverage_end,
          count(*)::bigint AS sample_count,
          count(DISTINCT s.openfdd_key)::bigint AS series_count,
          count(s.val)::bigint AS valued_count,
          sum(s.val) AS value_sum
        FROM sample s
        JOIN authorized_series a
          ON a.site_id = s.site_id AND a.openfdd_key = s.openfdd_key
        WHERE s.site_id = $1
          AND ($2::timestamptz IS NULL OR s.ts >= $2)
          AND ($3::timestamptz IS NULL OR s.ts < $3)
          AND (
            $4::text[] IS NULL
            OR a.equipment_id = ANY($4::text[])
            OR a.equipment_id IN (
              SELECT e.equipment_id
              FROM equipment e
              WHERE e.building_id = $1
                AND lower(btrim(e.equip_type)) = 'weather'
            )
          )
        "#,
    )
    .bind(building_id)
    .bind(start)
    .bind(end)
    .bind(equipment_bind)
    .fetch_one(tsdb.pool())
    .await
    .map_err(|err| public_db_error("timescale watermark", &err))?;
    let sample_count = row
        .try_get::<i64, _>("sample_count")
        .map_err(|err| public_db_error("timescale watermark", &err))?;
    let series_count = row
        .try_get::<i64, _>("series_count")
        .map_err(|err| public_db_error("timescale watermark", &err))?;
    let valued_count = row
        .try_get::<i64, _>("valued_count")
        .map_err(|err| public_db_error("timescale watermark", &err))?;
    let coverage_start = row
        .try_get::<Option<DateTime<Utc>>, _>("coverage_start")
        .map_err(|err| public_db_error("timescale watermark", &err))?;
    let coverage_end = row
        .try_get::<Option<DateTime<Utc>>, _>("coverage_end")
        .map_err(|err| public_db_error("timescale watermark", &err))?;
    let value_sum = row
        .try_get::<Option<f64>, _>("value_sum")
        .map_err(|err| public_db_error("timescale watermark", &err))?;
    let order = match coverage_end {
        Some(ts) => timestamp_order(ts)?,
        None => 0,
    };
    let utc = coverage_end
        .map(|ts| ts.to_rfc3339_opts(SecondsFormat::Secs, true))
        .unwrap_or_default();
    let min_utc = coverage_start
        .map(|ts| ts.to_rfc3339_opts(SecondsFormat::Secs, true))
        .unwrap_or_default();
    let sum_token = match value_sum {
        Some(value) if value.is_finite() => format!("{:x}", value.to_bits()),
        Some(_) => "nonfinite".to_string(),
        None => "none".to_string(),
    };
    let coverage = format!(
        "samples={sample_count};valued={valued_count};series={series_count};min={min_utc};max={utc};sum={sum_token}"
    );
    Ok(ScopedWatermark {
        order,
        utc,
        coverage,
    })
}

fn timestamp_order(ts: DateTime<Utc>) -> Result<u64, String> {
    let text = ts.format("%Y%m%d%H%M%S").to_string();
    text.parse::<u64>()
        .map_err(|err| format!("watermark order is not numeric: {err}"))
}

fn public_db_error(kind: &str, err: &impl std::fmt::Display) -> String {
    let detail = err.to_string();
    let lower = detail.to_ascii_lowercase();
    if detail.contains("://") || lower.contains("password") || lower.contains("secret") {
        format!("{kind} failed")
    } else {
        format!("{kind} failed: {detail}")
    }
}

/// Drop derived `analytics_result` rows for one building.
/// Historian samples, `fdd_run`, and labeled rule-result files are kept.
#[cfg_attr(
    not(test),
    expect(
        dead_code,
        reason = "selective derived-cache repair has no HTTP route in this change"
    )
)]
pub(crate) async fn repair_derived_analytics_cache(
    tsdb: &Tsdb,
    building_id: &str,
) -> Result<Value, String> {
    let deleted = sqlx::query("DELETE FROM analytics_result WHERE building_id = $1")
        .bind(building_id)
        .execute(tsdb.pool())
        .await
        .map_err(|err| public_db_error("derived analytics_result delete", &err))?;
    let samples = tsdb
        .sample_count(building_id)
        .await
        .map_err(|err| public_db_error("sample count", &err))?;
    let runs = sqlx::query("SELECT count(*)::bigint AS n FROM fdd_run WHERE site_id = $1")
        .bind(building_id)
        .fetch_one(tsdb.pool())
        .await
        .map_err(|err| public_db_error("fdd_run count", &err))?;
    let fdd_runs = runs
        .try_get::<i64, _>("n")
        .map_err(|err| public_db_error("fdd_run count", &err))?;
    Ok(json!({
        "ok": true,
        "analytics_result_rows_deleted": deleted.rows_affected(),
        "samples_remaining": samples,
        "fdd_runs_remaining": fdd_runs,
    }))
}

/// Timescale postgres-sql registry run-now (Soft-OPEN).
pub async fn run_fdd_registry(payload: &Value) -> Result<Value> {
    let building_id = payload
        .get("building_id")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| anyhow!("building_id required for Timescale FDD run"))?
        .to_string();
    let rule_filter: Option<Vec<String>> = payload.get("rule_ids").and_then(|v| {
        v.as_array().map(|a| {
            a.iter()
                .filter_map(|x| x.as_str().map(str::to_string))
                .collect()
        })
    });
    let equipment_filter = payload
        .get("equipment_id")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);

    let reg = load_reg()?;
    let mut rules: Vec<&RuleSpec> = reg.rules.iter().collect();
    if let Some(ids) = &rule_filter {
        if !ids.is_empty() {
            rules.retain(|r| {
                ids.iter()
                    .any(|id| r.rule_id == *id || r.aliases.iter().any(|a| a == id))
            });
        }
    }
    let tsdb = Tsdb::connect_from_env().await?;
    let pack = crate::sql_pack::pack_status(tsdb.pool()).await?;
    let pack_json = pack.to_json();
    let inventory = list_equipment(&tsdb, &building_id).await?;
    // The committed model is the site inventory. An equipment filter narrows
    // the rows this call evaluates and must not drop the rest of the model.
    let mut site_model = inventory.clone();
    let mut equipment = inventory;
    if let Some(eq) = &equipment_filter {
        // Soft-OPEN R6: never broaden an exact equipment_id miss into all equipment.
        equipment.retain(|(id, _)| id == eq);
        if equipment.is_empty() {
            // Exact id may exist only on samples (no equipment row yet).
            let rows = sqlx::query(
                r#"
                SELECT DISTINCT equipment_id
                FROM authorized_series
                WHERE site_id = $1 AND equipment_id = $2
                LIMIT 1
                "#,
            )
            .bind(&building_id)
            .bind(eq)
            .fetch_all(tsdb.pool())
            .await?;
            equipment = rows
                .into_iter()
                .map(|r| (r.get::<String, _>("equipment_id"), None))
                .collect();
        }
        if equipment.is_empty() {
            return Ok(json!({
                "ok": false,
                "engine": TS_ENGINE,
                "building_id": building_id,
                "historian": "timescale",
                "error": format!("equipment_id `{eq}` not found for site"),
                "status": "INELIGIBLE_EQUIPMENT",
                "rules_run": 0,
                "rules_succeeded": 0,
                "rules_failed": 0,
                "rules_skipped": 0,
                "results": [],
            }));
        }
        if site_model.is_empty() {
            site_model.clone_from(&equipment);
        }
    } else if equipment.is_empty() {
        // No selector: inventory from sample keys (site-scoped).
        let rows = sqlx::query(
            r#"
            SELECT DISTINCT equipment_id
            FROM authorized_series
            WHERE site_id = $1
            ORDER BY 1 LIMIT 200
            "#,
        )
        .bind(&building_id)
        .fetch_all(tsdb.pool())
        .await?;
        equipment = rows
            .into_iter()
            .map(|r| (r.get::<String, _>("equipment_id"), None))
            .collect();
        site_model.clone_from(&equipment);
    }

    let window_start = payload
        .get("start")
        .or_else(|| payload.get("window_start"))
        .and_then(|v| v.as_str());
    let window_end = payload
        .get("end")
        .or_else(|| payload.get("window_end"))
        .and_then(|v| v.as_str());
    let mut window_start_s = window_start.map(str::to_string);
    let mut window_end_s = window_end.map(str::to_string);
    let needs_window = window_start_s
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .is_none()
        || window_end_s
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .is_none();
    if needs_window {
        let row = sqlx::query(
            "SELECT min(ts) AS start_ts, max(ts) AS end_ts FROM sample WHERE site_id = $1",
        )
        .bind(&building_id)
        .fetch_optional(tsdb.pool())
        .await?;
        if let Some(row) = row {
            if window_start_s.is_none() {
                window_start_s = row
                    .try_get::<Option<DateTime<Utc>>, _>("start_ts")?
                    .map(|ts| ts.to_rfc3339());
            }
            if window_end_s.is_none() {
                window_end_s = row
                    .try_get::<Option<DateTime<Utc>>, _>("end_ts")?
                    .map(|ts| ts.to_rfc3339());
            }
        }
    }
    if window_start_s
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .is_none()
        || window_end_s
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .is_none()
    {
        let end = historian_watermark(&tsdb, &building_id)
            .await
            .and_then(|s| DateTime::parse_from_rfc3339(s.trim()).ok())
            .map(|dt| dt.with_timezone(&Utc))
            .unwrap_or_else(Utc::now);
        let start = end - chrono::Duration::hours(24);
        if window_start_s.is_none() {
            window_start_s = Some(start.to_rfc3339());
        }
        if window_end_s.is_none() {
            window_end_s = Some(end.to_rfc3339());
        }
    }

    let full_cohort = equipment_filter.is_none()
        && rule_filter
            .as_ref()
            .map(|ids| ids.is_empty())
            .unwrap_or(true);
    let poll = poll_seconds_from_payload(payload);
    let t0 = std::time::Instant::now();
    let watermark = historian_watermark(&tsdb, &building_id).await;
    let mut rule_files = Vec::new();

    for rule in rules {
        let kinds: Vec<&str> = rule.equipment_kinds.iter().map(String::as_str).collect();
        // Type-first. An exact id is allowed only after the type filter, and only
        // when the caller named that id and it has no stamp yet.
        let site_targets = targets_for_rule(&site_model, &kinds, None);
        let run_targets = targets_for_rule(&equipment, &kinds, equipment_filter.as_deref());
        let metric = rule_is_metric(rule);
        if site_targets.is_empty() {
            if full_cohort && kinds.as_slice() == ["vav"] {
                continue;
            }
            rule_files.push(rule_file(
                &rule.rule_id,
                &building_id,
                vec![json!({
                    "status": "SKIP_NO_TARGETS",
                    "output_kind": if metric { "metric" } else { "diagnostic" },
                    "notes": "no equipment of this rule's type is on the site model",
                })],
            ));
            continue;
        }
        if run_targets.is_empty() {
            continue;
        }

        let confirm = confirm_seconds_from_payload(payload, rule);
        let session_override = session_override_for_rule(payload, &rule.rule_id);
        let sql_body = match render_rule_sql(
            &reg,
            rule,
            poll,
            confirm,
            &building_id,
            equipment_filter.as_deref(),
            session_override.as_ref(),
        ) {
            Ok(s) => wrap_rule_sql(&s, rule),
            Err(e) => {
                tracing::warn!(rule = %rule.rule_id, error = %e, "render rule sql failed");
                rule_files.push(rule_file(
                    &rule.rule_id,
                    &building_id,
                    vec![json!({
                        "status": "ERROR",
                        "output_kind": if metric { "metric" } else { "diagnostic" },
                        "notes": e.to_string(),
                    })],
                ));
                continue;
            }
        };
        if let Some(stop) = crate::sql_pack::schema_stop(&sql_body, &pack) {
            rule_files.push(rule_file(
                &rule.rule_id,
                &building_id,
                vec![stop.to_json(None, metric)],
            ));
            continue;
        }

        let roles = rule_history_roles(rule);
        let oat_fill = if rule.rule_id.eq_ignore_ascii_case("OAT-METEO") {
            resolve_site_oa_t_reference(tsdb.pool(), &building_id)
                .await?
                .map(|site_oa| HistoryFillOptions {
                    site_oa_t: Some(site_oa),
                })
        } else {
            None
        };

        let mut rule_rows = Vec::new();
        for (eq_id, _) in &run_targets {
            let mut tx = tsdb.pool().begin().await?;
            if let Err(e) = ensure_history_table(&mut tx, &roles).await {
                tracing::warn!(rule = %rule.rule_id, error = %e, "temp history");
                rule_rows.push(json!({
                    "status": "ERROR",
                    "output_kind": if metric { "metric" } else { "diagnostic" },
                    "notes": e.to_string(),
                }));
                let _ = tx.rollback().await;
                break;
            }
            let n = fill_history_for_equipment(
                &mut tx,
                &building_id,
                eq_id,
                &roles,
                window_start,
                window_end,
                oat_fill.as_ref(),
            )
            .await?;
            if n == 0 {
                rule_rows.push(json!({
                    "equipment_id": eq_id,
                    "status": "SKIP_NO_HISTORY",
                    "missing_roles": rule.required_roles,
                    "output_kind": if metric { "metric" } else { "diagnostic" },
                    "sample_rows": n,
                }));
                let _ = tx.rollback().await;
                continue;
            }
            if rule.rule_id.eq_ignore_ascii_case("VAV-1") {
                let require_occ = session_override
                    .as_ref()
                    .and_then(|m| m.get("require_occupied"))
                    .copied()
                    .unwrap_or(1.0);
                if require_occ >= 0.5 {
                    let has_modeled =
                        crate::occupancy_calendar::history_has_modeled_occ_mode(&mut tx).await?;
                    if !has_modeled {
                        match crate::occupancy_calendar::resolve_occupancy_schedule_from_payload(
                            payload,
                        ) {
                            crate::occupancy_calendar::OccupancyScheduleResolution::Valid(
                                sched,
                            ) => {
                                crate::occupancy_calendar::synthesize_occ_mode_from_schedule(
                                    &mut tx, &sched,
                                )
                                .await?;
                            }
                            crate::occupancy_calendar::OccupancyScheduleResolution::Invalid(
                                err,
                            ) => {
                                rule_rows.push(json!({
                                    "equipment_id": eq_id,
                                    "status": "NOT_ASSESSED_NO_OCCUPANCY",
                                    "fault_hours": 0.0,
                                    "covered_hours": 0.0,
                                    "fault_pct": Value::Null,
                                    "output_kind": "diagnostic",
                                    "sample_rows": n,
                                    "input_condition": "occupancy_schedule_invalid",
                                    "notes": format!(
                                        "VAV-1 occupancy schedule invalid: {err}"
                                    ),
                                }));
                                let _ = tx.rollback().await;
                                continue;
                            }
                            crate::occupancy_calendar::OccupancyScheduleResolution::Absent => {
                                rule_rows.push(json!({
                                    "equipment_id": eq_id,
                                    "status": "NOT_ASSESSED_NO_OCCUPANCY",
                                    "fault_hours": 0.0,
                                    "covered_hours": 0.0,
                                    "fault_pct": Value::Null,
                                    "output_kind": "diagnostic",
                                    "sample_rows": n,
                                    "notes": "VAV-1 requires modeled occ_mode or a site occupancy schedule",
                                }));
                                let _ = tx.rollback().await;
                                continue;
                            }
                        }
                    }
                }
            }
            let (observed_start, observed_end) = history_observed_bounds(&mut tx).await?;
            let missing = missing_required_roles(&mut tx, &rule.required_roles).await?;
            if !missing.is_empty() {
                rule_rows.push(json!({
                    "equipment_id": eq_id,
                    "status": "SKIP_MISSING_ROLES",
                    "missing_roles": missing,
                    "sample_rows": n,
                    "output_kind": if metric { "metric" } else { "diagnostic" },
                }));
                let _ = tx.rollback().await;
                continue;
            }
            let gate = match crate::sql_pack::prepare_rule_inputs(
                &mut tx,
                &building_id,
                window_start,
                window_end,
                &sql_body,
                !metric,
            )
            .await
            {
                Ok(gate) => gate,
                Err(err) => {
                    let (status, class) =
                        crate::sql_pack::classify_database_error(&err.to_string());
                    rule_rows.push(json!({
                        "equipment_id": eq_id,
                        "status": status,
                        "failure_class": class,
                        "output_kind": if metric { "metric" } else { "diagnostic" },
                        "notes": err.to_string(),
                    }));
                    let _ = tx.rollback().await;
                    continue;
                }
            };
            let scope = match gate {
                crate::sql_pack::InputGate::Stop(stop) => {
                    rule_rows.push(stop.to_json(Some(eq_id), metric));
                    let _ = tx.rollback().await;
                    continue;
                }
                crate::sql_pack::InputGate::Ready(scope) => scope,
            };
            let config_fp = config_fingerprint(payload, poll);
            match sqlx::query(&sql_body).fetch_all(&mut *tx).await {
                Ok(rows) => {
                    if metric {
                        let values = rows.first().map(numeric_column_map).unwrap_or_default();
                        let metric_doc = metric_payload(
                            rule,
                            &values,
                            MetricWindowFacts {
                                requested_start: window_start,
                                requested_end: window_end,
                                observed_start: observed_start.as_deref(),
                                observed_end: observed_end.as_deref(),
                                watermark: watermark.as_deref(),
                                sample_rows: n,
                                config_fingerprint: &config_fp,
                            },
                        );
                        let mut row_json = json!({
                            "equipment_id": eq_id,
                            "status": "METRIC",
                            "output_kind": "metric",
                            "sample_rows": n,
                            "confirm_seconds": confirm,
                            "poll_seconds": poll,
                            "metric": metric_doc,
                        });
                        if let Some(obj) = row_json.as_object_mut() {
                            let mut stored = serde_json::Map::new();
                            for (key, value) in &values {
                                stored.insert(key.clone(), value.clone());
                            }
                            obj.insert("values".into(), Value::Object(stored));
                            for (key, value) in values {
                                obj.insert(key, value);
                            }
                        }
                        crate::sql_pack::attach_ready_scope(&mut row_json, &scope);
                        rule_rows.push(row_json);
                    } else {
                        let mut hours = 0.0_f64;
                        let mut covered_sum = 0.0_f64;
                        let mut saw_covered = false;
                        let mut sql_pct: Option<f64> = None;
                        for r in &rows {
                            hours += row_fault_hours(r);
                            if let Some(value) = row_optional_f64(r, "covered_hours") {
                                covered_sum += value;
                                saw_covered = true;
                            }
                            if sql_pct.is_none() {
                                sql_pct = row_optional_f64(r, "fault_pct");
                            }
                        }
                        let covered = saw_covered.then_some(covered_sum);
                        let span = history_span_hours(&mut tx).await.ok().flatten();
                        let unknown = match (span, covered) {
                            (Some(span_h), Some(covered_h)) => {
                                json!((span_h - covered_h).max(0.0))
                            }
                            _ => Value::Null,
                        };
                        let status = if hours > 0.0 { "FAULT" } else { "PASS" };
                        let fault_pct = match sql_pct {
                            Some(value) => json!(value),
                            None => fault_pct_from_covered(hours, covered),
                        };
                        let mut row_json = json!({
                            "equipment_id": eq_id,
                            "fault_hours": hours,
                            "covered_hours": json_finite(covered),
                            "span_hours": json_finite(span),
                            "unknown_hours": unknown,
                            "fault_pct": fault_pct,
                            "status": status,
                            "output_kind": "diagnostic",
                            "sample_rows": n,
                            "confirm_seconds": confirm,
                            "poll_seconds": poll,
                            "fault_series": {
                                "kind": "confirm_aggregate",
                                "fault_hours": hours,
                                "confirm_seconds": confirm,
                                "poll_seconds": poll,
                                "status": status,
                                "note": "confirm aggregate from eligible elapsed time"
                            },
                        });
                        if rule.rule_id.eq_ignore_ascii_case("OAT-METEO") {
                            if let Some(ref fill) = oat_fill {
                                if let Some(ref site_oa) = fill.site_oa_t {
                                    if let Some(obj) = row_json.as_object_mut() {
                                        obj.insert(
                                            "oat_reference".into(),
                                            json!({
                                                "openfdd_key": site_oa.openfdd_key,
                                                "equipment_id": site_oa.equipment_id,
                                                "selection": site_oa.selection,
                                            }),
                                        );
                                    }
                                }
                            }
                        }
                        crate::sql_pack::attach_ready_scope(&mut row_json, &scope);
                        rule_rows.push(row_json);
                    }
                    let _ = tx.commit().await;
                }
                Err(e) => {
                    let (status, class) = crate::sql_pack::classify_database_error(&e.to_string());
                    rule_rows.push(json!({
                        "equipment_id": eq_id,
                        "status": status,
                        "failure_class": class,
                        "output_kind": if metric { "metric" } else { "diagnostic" },
                        "notes": e.to_string(),
                    }));
                    let _ = tx.rollback().await;
                }
            }
        }
        rule_files.push(rule_file(&rule.rule_id, &building_id, rule_rows));
    }

    let commit = open_fdd_edge_prototype::fdd::registry_api::RunGenerationCommit {
        building_id: building_id.clone(),
        full_cohort,
        equipment: site_model
            .iter()
            .map(
                |(id, equip_type)| open_fdd_edge_prototype::fdd::registry_api::RunModelEquipment {
                    equipment_id: id.clone(),
                    equip_type: equip_type.clone(),
                },
            )
            .collect(),
        rules: rule_files,
        config_fingerprint: config_fingerprint(payload, poll),
        window_start: window_start_s,
        window_end: window_end_s,
        watermark,
        poll_seconds: poll,
        pack: pack_json,
    };
    let mut summary =
        crate::fdd_registry_persist::commit_and_persist_registry_run(&tsdb, commit).await?;
    if let Some(obj) = summary.as_object_mut() {
        obj.insert("engine".into(), json!(TS_ENGINE));
        obj.insert("historian".into(), json!("timescale"));
        obj.insert("dual_write".into(), json!(false));
        obj.insert("total_ms".into(), json!(t0.elapsed().as_millis() as u64));
    }
    Ok(summary)
}

#[derive(Clone, Copy)]
struct SampleSpan {
    first: Option<DateTime<Utc>>,
    last: Option<DateTime<Utc>>,
    rows: i64,
}

fn sampling_json(
    first: Option<DateTime<Utc>>,
    last: Option<DateTime<Utc>>,
    row_count: i64,
) -> Value {
    json!({
        "ok": row_count > 0,
        "row_count": row_count,
        "source": "timescale_sample",
        "first_timestamp": first.map(|ts| ts.to_rfc3339()),
        "last_timestamp": last.map(|ts| ts.to_rfc3339()),
    })
}

fn json_finite(hours: Option<f64>) -> Value {
    match hours {
        Some(hours) if hours.is_finite() => json!(hours),
        _ => Value::Null,
    }
}

fn row_optional_f64(row: &sqlx::postgres::PgRow, column: &str) -> Option<f64> {
    if let Ok(value) = row.try_get::<f64, _>(column) {
        return value.is_finite().then_some(value);
    }
    if let Ok(Some(value)) = row.try_get::<Option<f64>, _>(column) {
        return value.is_finite().then_some(value);
    }
    if let Ok(value) = row.try_get::<i64, _>(column) {
        return Some(value as f64);
    }
    if let Ok(value) = row.try_get::<i32, _>(column) {
        return Some(value as f64);
    }
    None
}

/// History span is first sample to last sample. Covered time is the sum of
/// eligible forward holds; a single sample has no span and no covered time.
async fn history_span_hours(conn: &mut PgConnection) -> Result<Option<f64>> {
    let span: Option<f64> = sqlx::query_scalar(
        "SELECT (EXTRACT(EPOCH FROM (MAX(timestamp_utc) - MIN(timestamp_utc))) / 3600.0)::float8 \
         FROM history",
    )
    .fetch_one(&mut *conn)
    .await
    .context("history span")?;
    Ok(span.filter(|hours| hours.is_finite() && *hours >= 0.0))
}

/// Percent of eligible covered hours. Missing or empty coverage stays null.
/// Values above 100 are left visible so a duration bug is not hidden.
fn fault_pct_from_covered(hours: f64, covered_hours: Option<f64>) -> Value {
    let Some(covered) = covered_hours else {
        return Value::Null;
    };
    if !hours.is_finite() || hours < 0.0 || !covered.is_finite() || covered <= 0.0 {
        return Value::Null;
    }
    json!((100.0 * hours) / covered)
}

fn safe_building_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 128
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
}

/// Package-mapping shape from Timescale `equipment` + `sample` keys.
///
/// CSV sidecars are optional. A provider building (hourly NF pull) still lists
/// equipment and roles so Inspect can plot the samples.
pub async fn package_mapping_from_samples(
    building_id: &str,
    equipment_id: Option<&str>,
) -> Result<Value> {
    let bid = building_id.trim();
    if !safe_building_id(bid) {
        return Ok(json!({
            "ok": false,
            "error": "building_id required",
            "source": "timescale_sample",
        }));
    }
    let tsdb = Tsdb::connect_from_env().await?;
    let typed = list_equipment(&tsdb, bid).await?;
    let mut types: BTreeMap<String, Option<String>> = typed.into_iter().collect();
    let role_rows = sqlx::query(
        r#"
        SELECT equipment_id, role, openfdd_key
        FROM authorized_series
        WHERE site_id = $1
        ORDER BY equipment_id, role, openfdd_key
        "#,
    )
    .bind(bid)
    .fetch_all(tsdb.pool())
    .await
    .context("sample roles for mapping")?;
    let mut roles_by_eq: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut ambiguous_by_eq: BTreeMap<String, BTreeMap<String, Vec<String>>> = BTreeMap::new();
    let mut keys_by_role: BTreeMap<(String, String), Vec<String>> = BTreeMap::new();
    for row in role_rows {
        let eq = row.try_get::<String, _>("equipment_id").unwrap_or_default();
        let role = row.try_get::<String, _>("role").unwrap_or_default();
        let key = row.try_get::<String, _>("openfdd_key").unwrap_or_default();
        if eq.is_empty() || role.is_empty() || key.is_empty() {
            continue;
        }
        types.entry(eq.clone()).or_insert(None);
        keys_by_role.entry((eq, role)).or_default().push(key);
    }
    for ((eq, role), keys) in keys_by_role {
        if keys.len() > 1 {
            ambiguous_by_eq.entry(eq).or_default().insert(role, keys);
        } else {
            roles_by_eq.entry(eq).or_default().push(role);
        }
    }
    if let Some(want) = equipment_id.map(str::trim).filter(|s| !s.is_empty()) {
        types.retain(|id, _| id == want);
        roles_by_eq.retain(|id, _| id == want);
    }
    if types.is_empty() {
        return Ok(json!({
            "ok": false,
            "error": format!("no Timescale samples for building {bid}"),
            "building_id": bid,
            "source": "timescale_sample",
            "equipment": [],
        }));
    }
    let sample_count = tsdb.sample_count(bid).await.unwrap_or(0);
    let span_rows = sqlx::query(
        r#"
        SELECT a.equipment_id,
               MIN(s.ts) AS first_ts,
               MAX(s.ts) AS last_ts,
               COUNT(*)::bigint AS row_count
        FROM sample s
        JOIN authorized_series a
          ON a.site_id = s.site_id AND a.openfdd_key = s.openfdd_key
        WHERE s.site_id = $1
        GROUP BY a.equipment_id
        "#,
    )
    .bind(bid)
    .fetch_all(tsdb.pool())
    .await
    .context("sample span for mapping")?;
    let mut spans: BTreeMap<String, SampleSpan> = BTreeMap::new();
    for row in span_rows {
        let eq = row.try_get::<String, _>("equipment_id").unwrap_or_default();
        if eq.is_empty() {
            continue;
        }
        spans.insert(
            eq,
            SampleSpan {
                first: row.try_get("first_ts").ok(),
                last: row.try_get("last_ts").ok(),
                rows: row.try_get("row_count").unwrap_or(0),
            },
        );
    }
    let mut equipment = Vec::new();
    for (eq, typ) in &types {
        let roles = roles_by_eq.get(eq).cloned().unwrap_or_default();
        let span = spans.get(eq).copied().unwrap_or(SampleSpan {
            first: None,
            last: None,
            rows: 0,
        });
        let mut role_obj = serde_json::Map::new();
        let columns: Vec<Value> = roles
            .iter()
            .map(|role| {
                role_obj.insert(role.clone(), json!(role));
                json!({"column": role, "role": role, "status": "mapped"})
            })
            .collect();
        equipment.push(json!({
            "equipment_id": eq,
            "equipment_type": typ.clone().unwrap_or_else(|| "unclassified".into()),
            "equipment_type_raw": typ,
            "equipment_type_source": if typ.is_some() { "timescale_equipment" } else { "timescale_sample" },
            "ok": !roles.is_empty(),
            "columns": columns,
            "roles": role_obj,
            "unmapped_columns": [],
            "ambiguous_roles": ambiguous_by_eq.get(eq).cloned().unwrap_or_default(),
            "blockers": [],
            "warnings": [],
            "sampling": sampling_json(span.first, span.last, span.rows),
        }));
    }
    let ids: Vec<&str> = equipment
        .iter()
        .filter_map(|row| row.get("equipment_id").and_then(Value::as_str))
        .collect();
    let n = equipment.len();
    Ok(json!({
        "ok": true,
        "building_id": bid,
        "source": "timescale_sample",
        "sample_count": sample_count,
        "equipment_ids": ids,
        "equipment": equipment,
        "validation": {
            "blocker_count": 0,
            "warning_count": 0,
            "equipment_count": n,
        },
    }))
}

pub async fn equipment_from_timescale(building_id: Option<&str>) -> Result<Value> {
    let Some(bid) = building_id.map(str::trim).filter(|s| !s.is_empty()) else {
        return Ok(json!({"ok": true, "count": 0, "equipment": [], "engine": TS_ENGINE}));
    };
    let tsdb = Tsdb::connect_from_env().await?;
    let rows = list_equipment(&tsdb, bid).await?;
    let equipment: Vec<Value> = rows
        .into_iter()
        .map(|(id, typ)| {
            json!({
                "equipment_id": id,
                "equipment_type": typ.clone().unwrap_or_else(|| "unclassified".into()),
                "equipment_type_raw": typ,
                "equipment_type_source": if typ.is_some() { "timescale_equipment" } else { "missing" },
            })
        })
        .collect();
    Ok(json!({
        "ok": true,
        "count": equipment.len(),
        "equipment": equipment,
        "engine": TS_ENGINE,
        "building_id": bid,
    }))
}

#[cfg(test)]
mod plot_role_tests {
    use super::*;

    fn assert_all_rules_have_plot_roles(reg: &RuleRegistry) -> Result<()> {
        if reg.rules.len() != 77 {
            return Err(anyhow!(
                "registry has {} rules; warehouse handoff requires exactly 77",
                reg.rules.len()
            ));
        }
        let mut empty = Vec::new();
        for rule in &reg.rules {
            if catalog_plot_roles(rule).is_empty() {
                empty.push(rule.rule_id.clone());
            }
        }
        if !empty.is_empty() {
            return Err(anyhow!(
                "catalog rules missing plot roles: {}",
                empty.join(", ")
            ));
        }
        Ok(())
    }

    #[test]
    fn all_77_catalog_rules_have_plot_roles() {
        let _lock = crate::test_env_lock::lock_env();
        let reg = load_reg().expect("load sql/fdd registry");
        assert_all_rules_have_plot_roles(&reg).expect("77 plot roles");
    }

    #[test]
    fn oat_meteo_roles_exclude_duct_static() {
        let _lock = crate::test_env_lock::lock_env();
        let reg = load_reg().expect("registry");
        let rule = reg
            .rules
            .iter()
            .find(|r| r.rule_id == "OAT-METEO")
            .expect("OAT-METEO");
        let roles = catalog_plot_roles(rule);
        assert!(
            !roles
                .iter()
                .any(|r| r.contains("duct") || r.contains("static")),
            "OAT-METEO roles={roles:?}"
        );
        assert!(
            roles.iter().any(|r| r.contains("oa") || r.contains("web")),
            "OAT-METEO should include OAT/web roles, got {roles:?}"
        );
    }

    #[test]
    fn fc1_sql_rewrites_to_per_sample_confirmed_fault() {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../sql/fdd/postgres/rules/fc1_duct_static_low.sql");
        let raw = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{path:?}: {e}"));
        let series = rewrite_rule_sql_to_fault_series(&raw, "AHU_1").expect("FC1 rewrite");
        assert!(series.contains("confirmed AS confirmed_fault"));
        assert!(series.contains("timestamp_utc"));
        assert!(series.contains("WHERE equipment_id = 'AHU_1'"));
        let lower = series.to_ascii_lowercase();
        let tail = lower.rfind("select").expect("outer select");
        assert!(
            !lower[tail..].contains("fault_hours"),
            "overlay select must be per-sample, not the fault_hours aggregate"
        );
        assert!(rewrite_rule_sql_to_fault_series(&raw, "AHU 1").is_none());
    }

    #[test]
    fn starter_rules_apply_to_building50_stamps() {
        let _lock = crate::test_env_lock::lock_env();
        let reg = load_reg().expect("registry");
        let starter = [
            "FC1",
            "AHU-SATDEV",
            "AHU-DUCTHI",
            "FAN-RUNTIME-HOURS",
            "FC10",
            "FC12",
            "CHW-1",
        ];
        let ahu_roles = [
            "duct_static",
            "duct_static_sp",
            "fan_cmd",
            "fan_status",
            "sat",
            "sat_sp",
            "mat",
            "oa_t",
            "oa_damper_pct",
            "clg_valve_pct",
        ];
        let chw_roles = ["chw_supply_t", "chw_return_t", "chiller_status"];
        for rule_id in starter {
            let rule = reg
                .rules
                .iter()
                .find(|r| r.rule_id == rule_id)
                .unwrap_or_else(|| panic!("missing starter rule {rule_id}"));
            let kinds: Vec<&str> = rule.equipment_kinds.iter().map(String::as_str).collect();
            let ahu = kinds.is_empty() || equip_matches_kinds(Some("ahu"), &kinds);
            let chw = kinds.is_empty() || equip_matches_kinds(Some("chwPlant"), &kinds);
            assert!(
                ahu || chw,
                "{rule_id} matches neither ahu nor chwPlant ({kinds:?})"
            );
            let pool: &[&str] = if equip_matches_kinds(Some("chwPlant"), &kinds) && !ahu {
                &chw_roles
            } else {
                &ahu_roles
            };
            for role in &rule.required_roles {
                assert!(
                    pool.contains(&role.as_str()) || chw_roles.contains(&role.as_str()),
                    "{rule_id} required role {role} is not in the Building 50 starter pack"
                );
            }
        }
    }

    #[test]
    fn fc1_confirm_min_zero_fills_sql_placeholders() {
        let _lock = crate::test_env_lock::lock_env();
        let reg = load_reg().expect("load sql/fdd registry");
        let rule = reg.rules.iter().find(|r| r.rule_id == "FC1").expect("FC1");
        let payload = json!({
            "params": { "FC1": { "confirm_min": 0 } }
        });
        let confirm = confirm_seconds_from_payload(&payload, rule);
        assert_eq!(
            confirm, 0,
            "confirm_min=0 is immediate, not the catalog default"
        );
        let session = session_override_for_rule(&payload, "FC1");
        let sql = render_rule_sql(
            &reg,
            rule,
            300.0,
            confirm,
            "SYNTH",
            Some("AHU_1"),
            session.as_ref(),
        )
        .expect("render FC1");
        assert!(
            !sql.contains("{{"),
            "unfilled placeholder left in FC1 SQL: {sql}"
        );
        assert!(
            sql.contains("streak_elapsed >= 0"),
            "confirm_min=0 must confirm on the first eligible interval: {sql}"
        );
        assert!(
            sql.contains("held_seconds"),
            "duration must use the forward hold: {sql}"
        );
        assert!(
            !sql.contains("SUM(confirmed) *"),
            "duration must not multiply confirmed rows by a poll: {sql}"
        );
    }

    #[test]
    fn clamp_max_points_bounds() {
        assert_eq!(clamp_max_points(None), 1500);
        assert_eq!(clamp_max_points(Some(10)), 50);
        assert_eq!(clamp_max_points(Some(99_999)), 5000);
    }

    #[test]
    fn candidate_keys_include_role_when_column_is_sat() {
        // Soft-OPEN #1278: SPARQL/opaque IRI uses CSV column SAT; seed stores AHU_1.sat.
        let keys = candidate_openfdd_keys_for_point("SYNTH_01", "AHU_1", "SAT");
        assert!(
            keys.iter().any(|k| k == "AHU_1.SAT"),
            "exact column key missing: {keys:?}"
        );
        assert!(
            keys.iter().any(|k| k == "AHU_1.sat"),
            "normalized role key missing: {keys:?}"
        );
    }
}

#[cfg(test)]
mod span_and_fault_pct_tests {
    use super::*;
    use chrono::TimeZone;

    #[test]
    fn sampling_json_carries_historian_bounds() {
        let first = Utc.with_ymd_and_hms(2026, 3, 16, 0, 40, 0).unwrap();
        let last = Utc.with_ymd_and_hms(2026, 7, 17, 10, 0, 0).unwrap();
        let body = sampling_json(Some(first), Some(last), 12);
        assert_eq!(body["row_count"], json!(12));
        assert_eq!(body["first_timestamp"], json!(first.to_rfc3339()));
        assert_eq!(body["last_timestamp"], json!(last.to_rfc3339()));
        let empty = sampling_json(None, None, 0);
        assert!(empty["first_timestamp"].is_null());
        assert!(empty["last_timestamp"].is_null());
    }

    #[test]
    fn diagnostic_wrapper_keeps_declared_fault_pct() {
        let _lock = crate::test_env_lock::lock_env();
        let reg = load_reg().expect("load sql/fdd registry");
        let oat = reg
            .rules
            .iter()
            .find(|rule| rule.rule_id == "OAT-METEO")
            .expect("OAT-METEO");
        let wrapped = wrap_rule_sql("SELECT 1", oat);
        assert!(wrapped.contains("fault_pct::double precision AS fault_pct"));
        let fc1 = reg
            .rules
            .iter()
            .find(|rule| rule.rule_id == "FC1")
            .expect("FC1");
        let fc1_sql = wrap_rule_sql("SELECT 1", fc1);
        assert!(fc1_sql.contains("fault_pct::double precision AS fault_pct"));
        assert!(fc1_sql.contains("covered_hours::double precision AS covered_hours"));
        assert!(fc1_sql.contains("fault_hours::double precision AS fault_hours"));
    }

    #[test]
    fn fault_pct_uses_covered_hours_without_clamping() {
        let pct = fault_pct_from_covered(2.0, Some(4.0));
        assert!((pct.as_f64().expect("pct") - 50.0).abs() < 1e-9);
        let over = fault_pct_from_covered(3.0, Some(2.0));
        assert!(
            (over.as_f64().expect("over") - 150.0).abs() < 1e-9,
            "a percent above 100 stays visible"
        );
        assert!(fault_pct_from_covered(1.0, None).is_null());
        assert!(fault_pct_from_covered(1.0, Some(0.0)).is_null());
        assert!(fault_pct_from_covered(f64::NAN, Some(1.0)).is_null());
    }

    #[test]
    fn duct_high_sql_integrates_elapsed_hold() {
        let _lock = crate::test_env_lock::lock_env();
        let reg = load_reg().expect("load sql/fdd registry");
        let rule = reg
            .rules
            .iter()
            .find(|item| item.rule_id == "AHU-DUCTHI")
            .expect("AHU-DUCTHI");
        let sql = render_rule_sql(&reg, rule, 300.0, 0, "SYNTH", Some("AHU_1"), None)
            .expect("render AHU-DUCTHI");
        assert!(sql.contains("held_seconds"));
        assert!(sql.contains("streak_elapsed >= 0"));
        assert!(!sql.contains("{{"));
        assert!(!sql.contains("SUM(confirmed) *"));
        let series = rewrite_rule_sql_to_fault_series(&sql, "AHU_1").expect("overlay");
        assert!(series.contains("confirmed AS confirmed_fault"));
    }

    #[test]
    fn metric_wrapper_casts_runtime_hours_to_float8() {
        let _lock = crate::test_env_lock::lock_env();
        let reg = load_reg().expect("load sql/fdd registry");
        let rule = reg
            .rules
            .iter()
            .find(|item| item.rule_id == "FAN-RUNTIME-HOURS")
            .expect("FAN-RUNTIME-HOURS");
        let wrapped = wrap_rule_sql("SELECT 1", rule);
        assert!(wrapped.contains("fan_runtime_hours\"::double precision"));
        assert!(wrapped.contains("total_hours\"::double precision"));
    }
}

/// Same physical hour at 1, 5, and 15 minute cadence.
///
/// Immediate confirmation agrees within one second. A fixed confirmation delay
/// may differ by one sample of the coarsest grid (15 minutes). A gap longer
/// than one hour is unknown: fault hours stay within the eligible covered
/// duration and do not reach the first-to-last span.
#[cfg(test)]
mod elapsed_time_contract {
    use super::*;
    use chrono::Duration as ChronoDuration;
    use chrono::TimeZone;
    use fdd_tsdb::{SampleRow, UpsertBatch};

    const SECOND_HOURS: f64 = 1.0 / 3600.0;
    const CADENCE_TOLERANCE_HOURS: f64 = 15.0 / 60.0;

    fn fixture_database_url() -> Option<String> {
        let url = std::env::var("OPENFDD_LIFECYCLE_DATABASE_URL")
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty());
        if url.is_none()
            && std::env::var("OPENFDD_LIFECYCLE_DATABASE_REQUIRED")
                .ok()
                .is_some_and(|value| matches!(value.trim(), "1" | "true" | "yes"))
        {
            panic!("OPENFDD_LIFECYCLE_DATABASE_URL is required for this run");
        }
        url
    }

    fn assert_disposable(id: &str) {
        let upper = id.to_ascii_uppercase();
        assert!(
            upper != "BUILDING_50"
                && upper != "BOSSPI"
                && !upper.contains("BUILDING_50")
                && !upper.contains("BOSSPI"),
            "refusing protected site id"
        );
    }

    struct EnvRestore {
        saved: Vec<(&'static str, Option<String>)>,
    }

    impl EnvRestore {
        fn capture(keys: &[&'static str]) -> Self {
            Self {
                saved: keys
                    .iter()
                    .map(|key| (*key, std::env::var(key).ok()))
                    .collect(),
            }
        }
    }

    impl Drop for EnvRestore {
        fn drop(&mut self) {
            for (key, value) in self.saved.drain(..) {
                match value {
                    Some(value) => std::env::set_var(key, value),
                    None => std::env::remove_var(key),
                }
            }
        }
    }

    struct DbCleanup {
        url: String,
        ids: Vec<String>,
    }

    impl Drop for DbCleanup {
        fn drop(&mut self) {
            let url = self.url.clone();
            let ids: Vec<String> = self
                .ids
                .drain(..)
                .filter(|id| {
                    let upper = id.to_ascii_uppercase();
                    upper != "BUILDING_50"
                        && upper != "BOSSPI"
                        && !upper.contains("BUILDING_50")
                        && !upper.contains("BOSSPI")
                })
                .collect();
            if ids.is_empty() {
                return;
            }
            let _ = std::thread::spawn(move || {
                let runtime = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("cleanup runtime");
                runtime.block_on(async move {
                    let Ok(tsdb) = Tsdb::connect(&url).await else {
                        return;
                    };
                    for id in ids {
                        let _ = tsdb.purge_building(&id).await;
                    }
                });
            })
            .join();
        }
    }

    fn origin() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 6, 1, 0, 0, 0).unwrap()
    }

    fn push_sample(
        batch: &mut UpsertBatch,
        site: &str,
        equipment_id: &str,
        minutes: i64,
        fan: f64,
    ) {
        let ts = origin() + ChronoDuration::minutes(minutes);
        for (role, val) in [
            ("duct_static", 2.0),
            ("duct_static_sp", 1.0),
            ("fan_status", fan),
            ("fan_cmd", fan),
        ] {
            let mut row = SampleRow::new(ts, site, format!("{equipment_id}.{role}"), Some(val));
            row.equipment_id = Some(equipment_id.to_string());
            row.role = Some(role.to_string());
            batch.push(row);
        }
    }

    fn seed_regular(batch: &mut UpsertBatch, site: &str, equipment_id: &str, step: i64, fan: f64) {
        let mut minute = 0;
        while minute <= 60 {
            push_sample(batch, site, equipment_id, minute, fan);
            minute += step;
        }
    }

    fn result_row<'a>(meta: &'a Value, rule_id: &str, equipment_id: &str) -> &'a Value {
        meta.get("results")
            .and_then(Value::as_array)
            .and_then(|rows| {
                rows.iter().find(|row| {
                    row.get("rule_id").and_then(Value::as_str) == Some(rule_id)
                        && row.get("equipment_id").and_then(Value::as_str) == Some(equipment_id)
                })
            })
            .unwrap_or_else(|| panic!("missing {rule_id}/{equipment_id} in {meta}"))
    }

    fn hours_of(row: &Value, key: &str) -> f64 {
        row.get(key)
            .and_then(Value::as_f64)
            .unwrap_or_else(|| panic!("{key} missing on {row}"))
    }

    fn assert_near(actual: f64, expected: f64, tolerance: f64, label: &str) {
        assert!(
            (actual - expected).abs() <= tolerance,
            "{label}: {actual} vs {expected} (tolerance {tolerance})"
        );
    }

    fn assert_bounded(row: &Value, label: &str) {
        let fault = hours_of(row, "fault_hours");
        let covered = hours_of(row, "covered_hours");
        let span = hours_of(row, "span_hours");
        assert!(
            fault <= covered + 1e-9 && covered <= span + 1e-9,
            "{label}: fault {fault} covered {covered} span {span}"
        );
        let status = row.get("status").and_then(Value::as_str).unwrap_or("");
        assert!(
            status == "FAULT" || status == "PASS",
            "{label} status {status} row {row}"
        );
    }

    async fn ensure_schema(tsdb: &Tsdb) {
        for stmt in crate::db_lifecycle::forward_statements() {
            sqlx::query(&stmt)
                .execute(tsdb.pool())
                .await
                .unwrap_or_else(|err| {
                    let preview: String = stmt.chars().take(80).collect();
                    panic!("schema statement failed ({preview}): {err}");
                });
        }
    }

    async fn run_rules(site: &str, confirm_seconds: u32) -> Value {
        let payload = json!({
            "building_id": site,
            "rule_ids": ["AHU-DUCTHI", "FAN-RUNTIME-HOURS"],
            "confirmation_seconds": confirm_seconds,
        });
        assert!(payload.get("poll_seconds").is_none());
        run_fdd_registry(&payload)
            .await
            .unwrap_or_else(|err| panic!("run_fdd_registry: {err}"))
    }

    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_* env while the disposable historian fixture is connected"
    )]
    #[tokio::test]
    async fn elapsed_time_cadence_and_gap_contract() {
        let Some(url) = fixture_database_url() else {
            eprintln!("skip: OPENFDD_LIFECYCLE_DATABASE_URL unset");
            return;
        };
        let _lock = crate::test_env_lock::lock_env();
        let results_dir = tempfile::tempdir().expect("results dir");
        let _env = EnvRestore::capture(&[
            "OPENFDD_DATABASE_URL",
            "OPENFDD_HISTORIAN",
            "OPENFDD_RULE_RESULTS_DIR",
            "OPENFDD_RESET_DB",
            "OPENFDD_ALLOW_DESTRUCTIVE_DB",
        ]);
        std::env::set_var("OPENFDD_DATABASE_URL", &url);
        std::env::set_var("OPENFDD_HISTORIAN", "timescale");
        std::env::set_var("OPENFDD_RULE_RESULTS_DIR", results_dir.path());
        std::env::remove_var("OPENFDD_RESET_DB");
        std::env::remove_var("OPENFDD_ALLOW_DESTRUCTIVE_DB");

        let cadence_site = format!("et{}", uuid::Uuid::new_v4().simple());
        let confirm_site = format!("ec{}", uuid::Uuid::new_v4().simple());
        assert_disposable(&cadence_site);
        assert_disposable(&confirm_site);
        let tsdb = Tsdb::connect(&url).await.expect("connect timescale");
        let cleanup = DbCleanup {
            url: url.clone(),
            ids: vec![cadence_site.clone(), confirm_site.clone()],
        };
        ensure_schema(&tsdb).await;

        let mut batch = UpsertBatch::default();
        seed_regular(&mut batch, &cadence_site, "AHU_M1", 1, 1.0);
        seed_regular(&mut batch, &cadence_site, "AHU_M5", 5, 1.0);
        seed_regular(&mut batch, &cadence_site, "AHU_M15", 15, 1.0);
        seed_regular(&mut batch, &cadence_site, "AHU_OFF", 1, 0.0);
        let mut minute = 0;
        while minute <= 30 {
            push_sample(&mut batch, &cadence_site, "AHU_GAP", minute, 1.0);
            minute += 1;
        }
        minute = 210;
        while minute <= 240 {
            push_sample(&mut batch, &cadence_site, "AHU_GAP", minute, 1.0);
            minute += 1;
        }
        let mut minute = 0;
        while minute <= 9 {
            push_sample(&mut batch, &confirm_site, "AHU_C9", minute, 1.0);
            minute += 1;
        }
        minute = 0;
        while minute <= 10 {
            push_sample(&mut batch, &confirm_site, "AHU_C10", minute, 1.0);
            minute += 1;
        }
        seed_regular(&mut batch, &confirm_site, "AHU_C60", 1, 1.0);
        seed_regular(&mut batch, &confirm_site, "AHU_C15", 15, 1.0);

        for site in [&cadence_site, &confirm_site] {
            tsdb.ensure_site_building(site)
                .await
                .expect("site building");
        }
        for (site, equipment_id) in [
            (cadence_site.as_str(), "AHU_M1"),
            (cadence_site.as_str(), "AHU_M5"),
            (cadence_site.as_str(), "AHU_M15"),
            (cadence_site.as_str(), "AHU_GAP"),
            (cadence_site.as_str(), "AHU_OFF"),
            (confirm_site.as_str(), "AHU_C9"),
            (confirm_site.as_str(), "AHU_C10"),
            (confirm_site.as_str(), "AHU_C60"),
            (confirm_site.as_str(), "AHU_C15"),
        ] {
            tsdb.upsert_equipment(site, equipment_id, Some("ahu"))
                .await
                .expect("equipment");
        }
        tsdb.upsert_samples(&batch).await.expect("samples");

        let open = run_rules(&cadence_site, 0).await;
        assert_eq!(open["rules_failed"], json!(0), "{open}");
        let mut cadence_hours = Vec::new();
        for equipment_id in ["AHU_M1", "AHU_M5", "AHU_M15"] {
            let row = result_row(&open, "AHU-DUCTHI", equipment_id);
            assert_bounded(row, equipment_id);
            let fault = hours_of(row, "fault_hours");
            assert_near(fault, 1.0, SECOND_HOURS, equipment_id);
            assert!(
                fault < 1.5,
                "1-minute fault hours followed the 300s poll default: {fault}"
            );
            cadence_hours.push(fault);
            let runtime = result_row(&open, "FAN-RUNTIME-HOURS", equipment_id);
            assert_near(
                hours_of(runtime, "fan_runtime_hours"),
                1.0,
                SECOND_HOURS,
                "fan runtime",
            );
        }
        let spread = cadence_hours.iter().copied().fold(f64::MIN, f64::max)
            - cadence_hours.iter().copied().fold(f64::MAX, f64::min);
        assert!(
            spread <= CADENCE_TOLERANCE_HOURS,
            "1/5/15 cadence spread {spread} hours exceeds 15 minutes: {cadence_hours:?}"
        );

        let gap = result_row(&open, "AHU-DUCTHI", "AHU_GAP");
        assert_bounded(gap, "AHU_GAP");
        assert_near(hours_of(gap, "fault_hours"), 1.0, SECOND_HOURS, "gap fault");
        assert_near(
            hours_of(gap, "covered_hours"),
            1.0,
            SECOND_HOURS,
            "gap covered",
        );
        assert_near(hours_of(gap, "span_hours"), 4.0, SECOND_HOURS, "gap span");
        assert_near(
            hours_of(gap, "unknown_hours"),
            3.0,
            SECOND_HOURS,
            "gap unknown",
        );
        assert!(
            hours_of(gap, "fault_hours") + 1.0 < hours_of(gap, "span_hours"),
            "gap fault must stay inside the covered hour, not the 4h span"
        );
        let gap_runtime = result_row(&open, "FAN-RUNTIME-HOURS", "AHU_GAP");
        assert_near(
            hours_of(gap_runtime, "fan_runtime_hours"),
            1.0,
            SECOND_HOURS,
            "gap fan runtime",
        );

        let off = result_row(&open, "AHU-DUCTHI", "AHU_OFF");
        assert_bounded(off, "AHU_OFF");
        assert_near(hours_of(off, "fault_hours"), 0.0, SECOND_HOURS, "fan off");
        let off_runtime = result_row(&open, "FAN-RUNTIME-HOURS", "AHU_OFF");
        assert_near(
            hours_of(off_runtime, "fan_runtime_hours"),
            0.0,
            SECOND_HOURS,
            "fan off runtime",
        );

        let scope = crate::timescale_analytics::AnalyticsSqlScope {
            start: None,
            end: None,
            equipment_ids: Vec::new(),
        };
        let motor = crate::timescale_analytics::motor_weekly_runtime(&tsdb, &cadence_site, &scope)
            .await
            .expect("motor weekly");
        for (equipment_id, expected) in [
            ("AHU_M1", 1.0),
            ("AHU_M5", 1.0),
            ("AHU_M15", 1.0),
            ("AHU_GAP", 1.0),
            ("AHU_OFF", 0.0),
        ] {
            let hours: f64 = motor
                .get("rows")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter(|row| row.get("equipment_id").and_then(Value::as_str) == Some(equipment_id))
                .filter_map(|row| row.get("runtime_hours").and_then(Value::as_f64))
                .sum();
            assert_near(hours, expected, SECOND_HOURS, equipment_id);
        }

        let confirmed = run_rules(&confirm_site, 600).await;
        assert_eq!(confirmed["rules_failed"], json!(0), "{confirmed}");
        let short = result_row(&confirmed, "AHU-DUCTHI", "AHU_C9");
        assert_bounded(short, "AHU_C9");
        assert_near(
            hours_of(short, "fault_hours"),
            0.0,
            SECOND_HOURS,
            "nine minutes is short of ten",
        );
        let exact = result_row(&confirmed, "AHU-DUCTHI", "AHU_C10");
        assert_bounded(exact, "AHU_C10");
        assert_near(
            hours_of(exact, "fault_hours"),
            SECOND_HOURS * 60.0,
            SECOND_HOURS,
            "the tenth minute is the crossing interval",
        );
        let fine = result_row(&confirmed, "AHU-DUCTHI", "AHU_C60");
        let coarse = result_row(&confirmed, "AHU-DUCTHI", "AHU_C15");
        assert_bounded(fine, "AHU_C60");
        assert_bounded(coarse, "AHU_C15");
        assert_near(
            hours_of(fine, "fault_hours"),
            51.0 / 60.0,
            SECOND_HOURS,
            "1-min confirm",
        );
        assert_near(
            hours_of(coarse, "fault_hours"),
            1.0,
            SECOND_HOURS,
            "15-min confirm",
        );
        assert!(
            (hours_of(fine, "fault_hours") - hours_of(coarse, "fault_hours")).abs()
                <= CADENCE_TOLERANCE_HOURS,
            "confirm cadence spread exceeds 15 minutes"
        );

        duplicate_timestamp_does_not_double_count().await;
        drop(cleanup);
    }

    async fn duplicate_timestamp_does_not_double_count() {
        let reg = load_reg().expect("registry");
        let rule = reg
            .rules
            .iter()
            .find(|item| item.rule_id == "AHU-DUCTHI")
            .expect("AHU-DUCTHI");
        let sql = wrap_rule_sql(
            &render_rule_sql(&reg, rule, 300.0, 0, "SYNTH", Some("AHU_DUP"), None).expect("render"),
            rule,
        );
        let tsdb = Tsdb::connect_from_env().await.expect("connect");
        let mut tx = tsdb.pool().begin().await.expect("begin");
        sqlx::query(
            "CREATE TEMP TABLE history (
                equipment_id text,
                timestamp_utc timestamptz,
                duct_static double precision,
                duct_static_sp double precision,
                fan_status double precision,
                fan_cmd double precision
            ) ON COMMIT DROP",
        )
        .execute(&mut *tx)
        .await
        .expect("temp history");
        sqlx::query(
            "INSERT INTO history VALUES
                ('AHU_DUP', '2026-06-01 00:00:00+00', 2, 1, 1, 1),
                ('AHU_DUP', '2026-06-01 00:00:00+00', 2, 1, 1, 1),
                ('AHU_DUP', '2026-06-01 00:01:00+00', 2, 1, 1, 1)",
        )
        .execute(&mut *tx)
        .await
        .expect("duplicate rows");
        let rows = sqlx::query(&sql).fetch_all(&mut *tx).await.expect("rule");
        let _ = tx.rollback().await;
        let hours = rows
            .first()
            .and_then(|row| row_optional_f64(row, "fault_hours"))
            .expect("fault hours");
        assert_near(hours, 60.0 / 3600.0, SECOND_HOURS, "duplicate timestamps");
        assert!(
            hours < 120.0 / 3600.0,
            "duplicate timestamp doubled the interval"
        );
    }
}

/// Active generation: partial versus complete, metric values, obsolete equipment,
/// and two sites that do not share a result folder.
#[cfg(test)]
mod run_generation_contract {
    use super::*;
    use std::collections::BTreeMap;

    fn disposable(id: &str) {
        let upper = id.to_ascii_uppercase();
        assert!(
            upper != "BUILDING_50"
                && upper != "BOSSPI"
                && !upper.contains("BUILDING_50")
                && !upper.contains("BOSSPI"),
            "refusing protected site id"
        );
    }

    struct EnvRestore {
        saved: Vec<(&'static str, Option<String>)>,
    }

    impl EnvRestore {
        fn capture(keys: &[&'static str]) -> Self {
            Self {
                saved: keys
                    .iter()
                    .map(|key| (*key, std::env::var(key).ok()))
                    .collect(),
            }
        }
    }

    impl Drop for EnvRestore {
        fn drop(&mut self) {
            for (key, value) in self.saved.drain(..) {
                match value {
                    Some(value) => std::env::set_var(key, value),
                    None => std::env::remove_var(key),
                }
            }
            fdd_tsdb::clear_shared_pool();
        }
    }

    fn write_registry(dir: &std::path::Path) {
        let rules = dir.join("postgres").join("rules");
        std::fs::create_dir_all(&rules).expect("rules dir");
        std::fs::write(
            dir.join("registry.yaml"),
            r#"
rules:
  - rule_id: AVG-ZONE-TEMP
    sql_file: avg_zone_temp.sql
    description: Average zone temperature
    equipment_kinds: [ahu]
    required_roles: [zone_t]
    output_columns: [equipment_id, avg_zone_temp]
    confirm_seconds: 0
  - rule_id: VAV-ONLY
    sql_file: vav_only.sql
    description: VAV fault hours
    equipment_kinds: [vav]
    required_roles: [zone_t]
    output_columns: [equipment_id, fault_hours, fault_pct]
    confirm_seconds: 0
  - rule_id: BOILER-ONLY
    sql_file: boiler_only.sql
    description: Boiler fault hours
    equipment_kinds: [boiler]
    required_roles: [zone_t]
    output_columns: [equipment_id, fault_hours, fault_pct]
    confirm_seconds: 0
  - rule_id: BROKEN-RULE
    sql_file: broken_rule.sql
    description: Render failure until the file exists
    equipment_kinds: [ahu]
    required_roles: [zone_t]
    output_columns: [equipment_id, fault_hours, fault_pct]
    confirm_seconds: 0
"#,
        )
        .expect("registry");
        std::fs::write(
            rules.join("avg_zone_temp.sql"),
            "SELECT equipment_id, AVG(zone_t) AS avg_zone_temp FROM history WHERE zone_t IS NOT NULL GROUP BY equipment_id;\n",
        )
        .expect("avg sql");
        std::fs::write(
            rules.join("vav_only.sql"),
            "SELECT equipment_id, 1.25::float8 AS fault_hours, 1.25::float8 AS covered_hours, 50.0::float8 AS fault_pct FROM history WHERE zone_t IS NOT NULL GROUP BY equipment_id;\n",
        )
        .expect("vav sql");
        std::fs::write(
            rules.join("boiler_only.sql"),
            "SELECT equipment_id, 0.0::float8 AS fault_hours, 1.0::float8 AS covered_hours, 0.0::float8 AS fault_pct FROM history GROUP BY equipment_id;\n",
        )
        .expect("boiler sql");
    }

    fn repair_broken(dir: &std::path::Path) {
        std::fs::write(
            dir.join("postgres").join("rules").join("broken_rule.sql"),
            "SELECT equipment_id, 0.0::float8 AS fault_hours, 1.0::float8 AS covered_hours, 0.0::float8 AS fault_pct FROM history GROUP BY equipment_id;\n",
        )
        .expect("repair sql");
    }

    async fn ensure_schema(pool: &sqlx::PgPool) {
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
        ] {
            crate::test_ddl::execute_idempotent_ddl(pool, statement).await;
        }
        // Contract tests share one database. A narrower fixture can create
        // `sample` first, and CREATE TABLE IF NOT EXISTS will not add columns.
        for statement in [
            "ALTER TABLE sample ADD COLUMN IF NOT EXISTS haystack_id text",
            "ALTER TABLE sample ADD COLUMN IF NOT EXISTS unit text",
            "ALTER TABLE sample ADD COLUMN IF NOT EXISTS quality text",
        ] {
            crate::test_ddl::execute_idempotent_ddl(pool, statement).await;
        }
        for statement in
            fdd_tsdb::schema_statements(include_str!("../../../sql/schema/01_bps_core.sql"))
        {
            if statement.contains("fdd_run") {
                crate::test_ddl::execute_idempotent_ddl(pool, statement).await;
            }
        }
        for statement in
            fdd_tsdb::schema_statements(include_str!("../../../sql/schema/10_incremental_fdd.sql"))
        {
            crate::test_ddl::execute_idempotent_ddl(pool, statement).await;
        }
    }

    async fn seed_site(pool: &sqlx::PgPool, site: &str, equipment: &[(&str, &str)]) {
        sqlx::query(
            "INSERT INTO site(site_id, dis) VALUES ($1, $1) ON CONFLICT (site_id) DO NOTHING",
        )
        .bind(site)
        .execute(pool)
        .await
        .expect("site");
        sqlx::query(
            "INSERT INTO building(building_id, site_id, dis) VALUES ($1, $1, $1) ON CONFLICT (building_id) DO NOTHING",
        )
        .bind(site)
        .execute(pool)
        .await
        .expect("building");
        for (id, kind) in equipment {
            sqlx::query(
                "INSERT INTO equipment(building_id, equipment_id, equip_type) VALUES ($1, $2, $3)
                 ON CONFLICT (building_id, equipment_id) DO UPDATE SET equip_type = EXCLUDED.equip_type",
            )
            .bind(site)
            .bind(id)
            .bind(kind)
            .execute(pool)
            .await
            .expect("equipment");
        }
    }

    async fn seed_zone(
        pool: &sqlx::PgPool,
        site: &str,
        equipment_id: &str,
        values: &[(&str, f64)],
    ) {
        for (ts, val) in values {
            sqlx::query(
                "INSERT INTO sample(ts, site_id, openfdd_key, val, unit)
                 VALUES ($1::timestamptz, $2, $3, $4, 'degF')
                 ON CONFLICT (site_id, openfdd_key, ts) DO UPDATE SET val = EXCLUDED.val",
            )
            .bind(ts)
            .bind(site)
            .bind(format!("{equipment_id}.zone_t"))
            .bind(val)
            .execute(pool)
            .await
            .expect("sample");
        }
        crate::series_binding::bind_conventional_key(pool, site, &format!("{equipment_id}.zone_t"))
            .await;
    }

    async fn delete_site(pool: &sqlx::PgPool, site: &str) {
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

    fn row_for<'a>(body: &'a Value, rule_id: &str, equipment_id: &str) -> &'a Value {
        body.get("results")
            .and_then(Value::as_array)
            .and_then(|rows| {
                rows.iter().find(|row| {
                    row.get("rule_id").and_then(Value::as_str) == Some(rule_id)
                        && row.get("equipment_id").and_then(Value::as_str) == Some(equipment_id)
                })
            })
            .unwrap_or_else(|| panic!("missing {rule_id}/{equipment_id} in {body}"))
    }

    async fn rest_rows(
        pool: &sqlx::PgPool,
        building_id: &str,
        types: &BTreeMap<String, String>,
    ) -> Value {
        let tsdb = fdd_tsdb::Tsdb::from_pool(pool.clone());
        crate::fdd_registry_persist::results_from_timescale(&tsdb, Some(building_id), types)
            .await
            .expect("rest results")
    }

    async fn readiness(pool: &sqlx::PgPool, building_id: &str) -> Value {
        let tsdb = fdd_tsdb::Tsdb::from_pool(pool.clone());
        crate::fdd_registry_persist::readiness_from_timescale(&tsdb, Some(building_id))
            .await
            .expect("readiness")
    }

    #[expect(
        clippy::await_holding_lock,
        reason = "OPENFDD_* env is process-global while this historian fixture is connected"
    )]
    #[tokio::test]
    async fn generation_manifest_metric_and_site_contract() {
        let explicit = std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty());
        let url = explicit
            .clone()
            .unwrap_or_else(|| "postgresql://openfdd:openfdd@127.0.0.1:5432/openfdd".into());
        let pool = match sqlx::postgres::PgPoolOptions::new()
            .max_connections(2)
            .connect(&url)
            .await
        {
            Ok(pool) => pool,
            Err(err) if explicit.is_some() => {
                panic!("OPENFDD_TEST_DATABASE_URL connect failed: {err}")
            }
            Err(err) => {
                eprintln!("skip: postgres fixture unavailable: {err}");
                return;
            }
        };
        let _lock = crate::test_env_lock::lock_env();
        let registry = tempfile::tempdir().expect("registry");
        let results = tempfile::tempdir().expect("results");
        write_registry(registry.path());
        let _env = EnvRestore::capture(&[
            "OPENFDD_DATABASE_URL",
            "OPENFDD_HISTORIAN",
            "OPENFDD_SQL_ROOT",
            "OPENFDD_SQL_RULES_DIR",
            "OPENFDD_RULE_RESULTS_DIR",
            "OPENFDD_RESET_DB",
            "OPENFDD_ALLOW_DESTRUCTIVE_DB",
        ]);
        std::env::set_var("OPENFDD_DATABASE_URL", &url);
        std::env::set_var("OPENFDD_HISTORIAN", "timescale");
        std::env::set_var("OPENFDD_SQL_ROOT", registry.path());
        std::env::set_var("OPENFDD_SQL_RULES_DIR", registry.path());
        std::env::set_var("OPENFDD_RULE_RESULTS_DIR", results.path());
        std::env::remove_var("OPENFDD_RESET_DB");
        std::env::remove_var("OPENFDD_ALLOW_DESTRUCTIVE_DB");
        fdd_tsdb::clear_shared_pool();

        let token = uuid::Uuid::new_v4().simple().to_string();
        let suffix = &token[..8];
        let site_a = format!("w3gena{suffix}");
        let site_b = format!("w3genb{suffix}");
        let site_fail = format!("w3genf{suffix}");
        let site_legacy = format!("w3genl{suffix}");
        for id in [&site_a, &site_b, &site_fail, &site_legacy] {
            disposable(id);
        }
        ensure_schema(&pool).await;
        for id in [&site_a, &site_b, &site_fail, &site_legacy] {
            delete_site(&pool, id).await;
        }
        seed_site(&pool, &site_a, &[("AHU_A", "ahu"), ("VAV_1", "vav")]).await;
        seed_zone(
            &pool,
            &site_a,
            "AHU_A",
            &[
                ("2026-06-01T00:00:00Z", 70.0),
                ("2026-06-01T01:00:00Z", 74.0),
            ],
        )
        .await;
        seed_zone(
            &pool,
            &site_a,
            "VAV_1",
            &[
                ("2026-06-01T00:00:00Z", 71.0),
                ("2026-06-01T01:00:00Z", 73.0),
            ],
        )
        .await;
        seed_site(&pool, &site_b, &[("AHU_B", "ahu")]).await;
        seed_zone(
            &pool,
            &site_b,
            "AHU_B",
            &[
                ("2026-06-01T00:00:00Z", 50.0),
                ("2026-06-01T01:00:00Z", 50.0),
            ],
        )
        .await;
        seed_site(&pool, &site_fail, &[("AHU_F", "ahu")]).await;

        let window = json!({
            "building_id": site_a,
            "start": "2026-06-01T00:00:00Z",
            "end": "2026-06-02T00:00:00Z",
        });
        let partial = run_fdd_registry(&window).await.expect("partial run");
        assert_eq!(partial["ok"], json!(true), "{partial}");
        assert_eq!(partial["run_status"], json!("partial"), "{partial}");
        assert_eq!(partial["rules_failed"], json!(1), "{partial}");
        assert_eq!(partial["rules_skipped"], json!(1), "{partial}");
        assert_eq!(partial["rules_succeeded"], json!(2), "{partial}");
        assert!(partial["run_id"].as_str().unwrap_or("").starts_with("run-"));
        assert!(partial["watermark"]
            .as_str()
            .unwrap_or("")
            .contains("2026-06-01"));
        assert_eq!(partial["window"]["start"], json!("2026-06-01T00:00:00Z"));
        let metric = row_for(&partial, "AVG-ZONE-TEMP", "AHU_A");
        let value = metric["metric"]["value"].as_f64().expect("metric value");
        assert!((value - 22.22222222222222).abs() < 1e-6, "{metric}");
        assert_eq!(metric["metric"]["unit"], json!("degC"));
        assert_eq!(metric["metric"]["quantity"], json!("absolute_temperature"));
        assert_eq!(metric["status"], json!("METRIC"));
        assert_ne!(metric["status"], json!("PASS"));
        assert!(metric.get("fault_hours").is_none());
        let vav = row_for(&partial, "VAV-ONLY", "VAV_1");
        assert_eq!(vav["status"], json!("FAULT"));
        let first_run = partial["run_id"].as_str().unwrap().to_string();
        let first_vav_rows: i64 = sqlx::query_scalar(
            "SELECT COUNT(*)::bigint FROM fdd_run WHERE site_id = $1 AND rule_id = 'VAV-ONLY'",
        )
        .bind(&site_a)
        .fetch_one(&pool)
        .await
        .expect("vav run count");

        let mut stale_types = BTreeMap::new();
        stale_types.insert("AHU_A".into(), "ahu".into());
        stale_types.insert("VAV_1".into(), "vav".into());
        let partial_rest = rest_rows(&pool, &site_a, &stale_types).await;
        let partial_ready = readiness(&pool, &site_a).await;
        assert_eq!(partial_ready["clean"], json!(false), "{partial_ready}");
        assert_eq!(partial_ready["run_status"], json!("partial"));
        assert_eq!(
            partial_ready["result_count"],
            json!(partial_rest["results"].as_array().unwrap().len())
        );
        assert!(partial_rest["results"]
            .as_array()
            .unwrap()
            .iter()
            .any(|row| row["equipment_id"] == "VAV_1"));

        let failed = run_fdd_registry(&json!({ "building_id": site_fail }))
            .await
            .expect("failed run");
        assert_eq!(failed["run_status"], json!("failed"), "{failed}");
        assert_eq!(failed["rules_failed"], json!(1), "{failed}");
        assert!(failed["rules_skipped"].as_u64().unwrap_or(0) >= 1);
        let failed_ready = readiness(&pool, &site_fail).await;
        assert_eq!(failed_ready["clean"], json!(false), "{failed_ready}");
        assert_eq!(failed_ready["run_status"], json!("failed"));
        let failed_rest = rest_rows(&pool, &site_fail, &BTreeMap::new()).await;
        assert_eq!(
            failed_ready["result_count"].as_u64().unwrap(),
            failed_rest["results"].as_array().unwrap().len() as u64
        );

        sqlx::query("DELETE FROM equipment WHERE building_id = $1 AND equipment_id = 'VAV_1'")
            .bind(&site_a)
            .execute(&pool)
            .await
            .expect("drop vav");
        repair_broken(registry.path());
        let complete = run_fdd_registry(&window).await.expect("complete run");
        assert_eq!(complete["ok"], json!(true), "{complete}");
        assert_eq!(complete["run_status"], json!("complete"), "{complete}");
        assert_eq!(complete["rules_failed"], json!(0), "{complete}");
        assert_eq!(complete["rules_skipped"], json!(1), "{complete}");
        assert!(complete["results"]
            .as_array()
            .unwrap()
            .iter()
            .all(|row| row["equipment_id"] != "VAV_1"));
        assert_eq!(first_vav_rows, 1, "partial run persisted VAV-ONLY");
        let vav_rows_after_full: i64 = sqlx::query_scalar(
            "SELECT COUNT(*)::bigint FROM fdd_run WHERE site_id = $1 AND rule_id = 'VAV-ONLY'",
        )
        .bind(&site_a)
        .fetch_one(&pool)
        .await
        .expect("vav run count after full cohort");
        assert_eq!(
            vav_rows_after_full, 0,
            "full cohort replaces prior VAV-ONLY rows"
        );
        let second_run = complete["run_id"].as_str().unwrap().to_string();
        assert_ne!(second_run, first_run);

        let current = rest_rows(&pool, &site_a, &stale_types).await;
        let current_ready = readiness(&pool, &site_a).await;
        assert_eq!(current_ready["clean"], json!(true), "{current_ready}");
        assert_eq!(current_ready["run_status"], json!("complete"));
        assert_eq!(
            current_ready["result_count"].as_u64().unwrap(),
            current["results"].as_array().unwrap().len() as u64
        );
        assert_eq!(current["count"], current_ready["result_count"]);
        assert!(current["results"]
            .as_array()
            .unwrap()
            .iter()
            .all(|row| { row["equipment_id"] != "VAV_1" && row["equipment_id"] != "AHU_B" }));
        let metric_rest = current["results"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| row["rule_id"] == "AVG-ZONE-TEMP" && row["equipment_id"] == "AHU_A")
            .expect("rest metric");
        assert_eq!(metric_rest["status"], json!("METRIC"));
        assert!(metric_rest["fault_hours"].is_null());
        assert!((metric_rest["metric"]["value"].as_f64().unwrap() - 22.22222222222222).abs() < 1e-6);
        assert_eq!(metric_rest["metric"]["unit"], json!("degC"));
        assert!(metric_rest["metric"]["window"]["watermark"]
            .as_str()
            .unwrap_or("")
            .contains("2026-06-01"));
        // Effective window is the observed historian span, not an invented request.
        assert_eq!(metric_rest["metric"]["window"]["unknown"], json!(false));
        assert!(
            metric_rest["metric"]["window"]["start"]
                .as_str()
                .unwrap_or("")
                .contains("2026-06-01"),
            "effective start: {metric_rest}"
        );
        assert!(
            metric_rest["metric"]["window"]["end"]
                .as_str()
                .unwrap_or("")
                .contains("2026-06-01"),
            "effective end: {metric_rest}"
        );
        assert_eq!(
            metric_rest["metric"]["window"]["observed_start"],
            metric_rest["metric"]["window"]["start"]
        );
        assert_eq!(
            metric_rest["metric"]["window"]["observed_end"],
            metric_rest["metric"]["window"]["end"]
        );
        assert_eq!(metric_rest["metric"]["coverage"]["sample_rows"], json!(2));
        assert_eq!(
            metric_rest["metric"]["provenance"]["source"],
            json!("timescale")
        );
        assert!(
            metric_rest["metric"]["provenance"]["config_fingerprint"]
                .as_str()
                .map(|s| !s.is_empty())
                .unwrap_or(false),
            "provenance config fingerprint: {metric_rest}"
        );

        let tuned = run_fdd_registry(&json!({
            "building_id": site_a,
            "rule_ids": ["AVG-ZONE-TEMP"],
        }))
        .await
        .expect("single rule");
        assert_eq!(tuned["parent_run_id"], json!(second_run), "{tuned}");
        assert_eq!(tuned["cohort"], json!("derived"));
        assert_eq!(tuned["run_status"], json!("complete"), "{tuned}");
        assert!(tuned["results"]
            .as_array()
            .unwrap()
            .iter()
            .any(|row| row["rule_id"] == "BOILER-ONLY"));
        let other = run_fdd_registry(&json!({ "building_id": site_b }))
            .await
            .expect("other site");
        assert_eq!(other["run_status"], json!("complete"), "{other}");
        let other_metric = row_for(&other, "AVG-ZONE-TEMP", "AHU_B");
        assert!((other_metric["metric"]["value"].as_f64().unwrap() - 50.0).abs() < 1e-6);
        let site_a_after = rest_rows(&pool, &site_a, &stale_types).await;
        assert!(site_a_after["results"]
            .as_array()
            .unwrap()
            .iter()
            .all(|row| row["equipment_id"] != "AHU_B"));
        assert_ne!(site_a_after["run_id"], other["run_id"]);

        let legacy_dir = results.path().join(format!("building={site_legacy}"));
        std::fs::create_dir_all(&legacy_dir).expect("legacy dir");
        let legacy_file = legacy_dir.join("FC1.json");
        std::fs::write(
            &legacy_file,
            br#"{"rule_id":"FC1","rows":[{"equipment_id":"OLD","status":"PASS","fault_hours":0}]}"#,
        )
        .expect("legacy");
        let legacy_ready = readiness(&pool, &site_legacy).await;
        assert_eq!(legacy_ready["result_count"], json!(0), "{legacy_ready}");
        assert_eq!(legacy_ready["clean"], json!(false));
        assert!(legacy_ready["dirty_reasons"]
            .as_array()
            .unwrap()
            .iter()
            .any(|reason| reason == "legacy_unmanifested"));
        assert!(legacy_file.is_file(), "legacy history is kept");
        let legacy_rest = rest_rows(&pool, &site_legacy, &BTreeMap::new()).await;
        assert_eq!(legacy_rest["count"], json!(0));
        assert_eq!(legacy_rest["legacy_withheld"], json!(true));

        for id in [&site_a, &site_b, &site_fail, &site_legacy] {
            delete_site(&pool, id).await;
        }
    }
}

#[cfg(test)]
mod analytics_cache_identity {
    use super::{
        read_analytics_cache_input_from, repair_derived_analytics_cache, AnalyticsCacheInput,
    };
    use chrono::{Duration, TimeZone, Utc};
    use fdd_tsdb::{SampleRow, Tsdb, UpsertBatch};

    fn disposable(id: &str) {
        let upper = id.to_ascii_uppercase();
        assert!(
            upper != "BUILDING_50" && upper != "BOSSPI" && !upper.contains("BUILDING_100"),
            "refusing protected site id"
        );
    }

    async fn connect() -> Option<sqlx::PgPool> {
        let explicit = std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty());
        let url = explicit
            .clone()
            .unwrap_or_else(|| "postgresql://openfdd:openfdd@127.0.0.1:5432/openfdd".into());
        match sqlx::postgres::PgPoolOptions::new()
            .max_connections(2)
            .connect(&url)
            .await
        {
            Ok(pool) => Some(pool),
            Err(err) if explicit.is_some() => {
                panic!("OPENFDD_TEST_DATABASE_URL connect failed: {err}")
            }
            Err(err) => {
                eprintln!("skip: postgres fixture unavailable: {err}");
                None
            }
        }
    }

    async fn apply_schema(pool: &sqlx::PgPool) {
        // Plain Postgres is enough. The identity queries do not need a hypertable,
        // and the main CI job has no Timescale extension.
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
                site_id text NOT NULL,
                openfdd_key text NOT NULL,
                haystack_id text NOT NULL,
                role text,
                unit text,
                equipment_id text,
                PRIMARY KEY (site_id, openfdd_key)
            )",
            "CREATE TABLE IF NOT EXISTS fdd_run (
                run_id bigserial PRIMARY KEY,
                site_id text NOT NULL,
                equipment_id text NOT NULL,
                rule_id text NOT NULL,
                window_start timestamptz NOT NULL,
                window_end timestamptz NOT NULL,
                poll_seconds integer NOT NULL DEFAULT 300,
                confirm_min double precision NOT NULL DEFAULT 0,
                config_hash text,
                status text NOT NULL,
                fault_seconds integer,
                fault_hours double precision,
                sample_count integer,
                detail jsonb,
                created_at timestamptz NOT NULL DEFAULT now()
            )",
            "CREATE TABLE IF NOT EXISTS analytics_result (
                building_id text NOT NULL,
                query_id text NOT NULL,
                query_version text NOT NULL,
                window_key text NOT NULL,
                config_hash text NOT NULL,
                stale boolean NOT NULL DEFAULT false,
                payload jsonb NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (building_id, query_id, query_version, window_key, config_hash)
            )",
        ] {
            crate::test_ddl::execute_idempotent_ddl(pool, statement).await;
        }
        for statement in [
            "ALTER TABLE sample ADD COLUMN IF NOT EXISTS haystack_id text",
            "ALTER TABLE sample ADD COLUMN IF NOT EXISTS unit text",
            "ALTER TABLE sample ADD COLUMN IF NOT EXISTS quality text",
        ] {
            crate::test_ddl::execute_idempotent_ddl(pool, statement).await;
        }
    }

    async fn cleanup(pool: &sqlx::PgPool, site: &str) {
        for sql in [
            "DELETE FROM analytics_result WHERE building_id = $1",
            "DELETE FROM fdd_run WHERE site_id = $1",
            "DELETE FROM sample WHERE site_id = $1",
            "DELETE FROM role_map WHERE building_id = $1",
            "DELETE FROM point_map WHERE site_id = $1",
            "DELETE FROM equipment WHERE building_id = $1",
            "DELETE FROM building WHERE building_id = $1",
            "DELETE FROM site WHERE site_id = $1",
        ] {
            let _ = sqlx::query(sql).bind(site).execute(pool).await;
        }
    }

    #[tokio::test]
    async fn scoped_watermark_model_remap_and_repair_keep_history() {
        let Some(pool) = connect().await else {
            return;
        };
        apply_schema(&pool).await;
        let token = uuid::Uuid::new_v4().simple().to_string();
        let site = format!("w1cache{}", &token[..8]);
        disposable(&site);
        let eq_a = format!("eq{}", &token[..8]);
        let eq_prefix = format!("eq{}0", &token[..8]);
        let weather = format!("wx{}", &token[..8]);
        let tsdb = Tsdb::from_pool(pool.clone());
        tsdb.ensure_site_building(&site).await.expect("site");
        tsdb.upsert_equipment(&site, &eq_a, Some("ahu"))
            .await
            .expect("ahu");
        tsdb.upsert_equipment(&site, &eq_prefix, Some("ahu"))
            .await
            .expect("longer id");
        tsdb.upsert_equipment(&site, &weather, Some("weather"))
            .await
            .expect("weather");
        let t0 = Utc.with_ymd_and_hms(2026, 6, 1, 0, 0, 0).unwrap();
        let mut batch = UpsertBatch::default();
        batch.push(SampleRow::new(t0, &site, format!("{eq_a}.sat"), Some(70.0)));
        batch.push(SampleRow::new(
            t0,
            &site,
            format!("{eq_prefix}.sat"),
            Some(71.0),
        ));
        tsdb.upsert_samples(&batch).await.expect("samples");
        crate::series_binding::bind_conventional_key(&pool, &site, &format!("{eq_a}.sat")).await;
        crate::series_binding::bind_conventional_key(&pool, &site, &format!("{eq_prefix}.sat"))
            .await;
        sqlx::query(
            "INSERT INTO role_map (building_id, equipment_id, openfdd_key, role, unit)
             VALUES ($1, $2, $3, 'sat', 'degF')
             ON CONFLICT (building_id, equipment_id, openfdd_key) DO UPDATE SET role = EXCLUDED.role",
        )
        .bind(&site)
        .bind(&eq_a)
        .bind(format!("{eq_a}.sat"))
        .execute(&pool)
        .await
        .expect("role");
        sqlx::query(
            "INSERT INTO fdd_run (site_id, equipment_id, rule_id, window_start, window_end, status)
             VALUES ($1, $2, 'FC1', $3, $4, 'PASS')",
        )
        .bind(&site)
        .bind(&eq_a)
        .bind(t0)
        .bind(t0 + Duration::hours(1))
        .execute(&pool)
        .await
        .expect("fdd_run");
        sqlx::query(
            "INSERT INTO analytics_result
                (building_id, query_id, query_version, window_key, config_hash, payload)
             VALUES ($1, 'rcx-preset', 'rcx-preset-v1', 'open', 'old', '{}'::jsonb)",
        )
        .bind(&site)
        .execute(&pool)
        .await
        .expect("analytics_result");

        let scoped = read_analytics_cache_input_from(
            &tsdb,
            &site,
            Some(t0),
            Some(t0 + Duration::hours(1)),
            std::slice::from_ref(&eq_a),
        )
        .await;
        let first = scoped.watermark.expect("watermark");
        let model = scoped.model_revision.expect("model");
        // The longer equipment token shares a prefix and must not be counted.
        assert!(
            first.coverage.starts_with("samples=1;"),
            "exact token only: {}",
            first.coverage
        );

        let mut weather_batch = UpsertBatch::default();
        weather_batch.push(SampleRow::new(
            t0 + Duration::minutes(5),
            &site,
            format!("{weather}.web_oa_t"),
            Some(60.0),
        ));
        tsdb.upsert_samples(&weather_batch)
            .await
            .expect("weather sample");
        crate::series_binding::bind_conventional_key(&pool, &site, &format!("{weather}.web_oa_t"))
            .await;
        let with_weather = read_analytics_cache_input_from(
            &tsdb,
            &site,
            Some(t0),
            Some(t0 + Duration::hours(1)),
            std::slice::from_ref(&eq_a),
        )
        .await
        .watermark
        .expect("weather watermark");
        assert!(with_weather.coverage.starts_with("samples=2;"));
        assert_ne!(with_weather.order, first.order);

        sqlx::query(
            "UPDATE sample SET val = 72.0 WHERE site_id = $1 AND openfdd_key = $2 AND ts = $3",
        )
        .bind(&site)
        .bind(format!("{eq_a}.sat"))
        .bind(t0)
        .execute(&pool)
        .await
        .expect("edit value");
        let edited = read_analytics_cache_input_from(
            &tsdb,
            &site,
            Some(t0),
            Some(t0 + Duration::hours(1)),
            std::slice::from_ref(&eq_a),
        )
        .await
        .watermark
        .expect("edited watermark");
        assert_eq!(edited.order, with_weather.order);
        assert_ne!(edited.coverage, with_weather.coverage);

        sqlx::query(
            "UPDATE role_map SET role = 'sat_sp' WHERE building_id = $1 AND equipment_id = $2",
        )
        .bind(&site)
        .bind(&eq_a)
        .execute(&pool)
        .await
        .expect("remap");
        let remapped = read_analytics_cache_input_from(&tsdb, &site, None, None, &[] as &[String])
            .await
            .model_revision
            .expect("remapped model");
        assert_ne!(remapped, model);

        let before_samples = tsdb.sample_count(&site).await.expect("count");
        let repair = repair_derived_analytics_cache(&tsdb, &site)
            .await
            .expect("repair");
        assert_eq!(
            repair["samples_remaining"],
            serde_json::json!(before_samples)
        );
        assert_eq!(repair["fdd_runs_remaining"], serde_json::json!(1));
        assert_eq!(
            repair["analytics_result_rows_deleted"],
            serde_json::json!(1)
        );
        assert!(repair.get("derived_files_removed").is_none());
        assert_eq!(
            tsdb.sample_count(&site).await.expect("samples stay"),
            before_samples
        );
        let runs: i64 =
            sqlx::query_scalar("SELECT count(*)::bigint FROM fdd_run WHERE site_id = $1")
                .bind(&site)
                .fetch_one(&pool)
                .await
                .expect("runs");
        assert_eq!(runs, 1);
        cleanup(&pool, &site).await;

        pool.close().await;
        let failed: AnalyticsCacheInput =
            read_analytics_cache_input_from(&tsdb, &site, None, None, &[]).await;
        let reason = failed.watermark.expect_err("closed pool is a failed read");
        assert!(failed.model_revision.is_err());
        assert!(!reason.contains("://"));
        assert!(!reason.to_ascii_lowercase().contains("password"));
        let _ = reason;
    }
}

#[cfg(test)]
mod opaque_series_binding {
    use super::{
        fdd_plot, inspect_equipment, package_mapping_from_samples, rcx_timeseries, RcxQuery,
    };
    use chrono::{TimeZone, Utc};
    use fdd_tsdb::{PurgeTarget, Tsdb};
    use serde_json::json;

    struct EnvGuard {
        key: &'static str,
        prev: Option<String>,
    }

    impl EnvGuard {
        fn set(key: &'static str, value: &str) -> Self {
            let prev = std::env::var(key).ok();
            std::env::set_var(key, value);
            Self { key, prev }
        }
    }

    impl Drop for EnvGuard {
        fn drop(&mut self) {
            match self.prev.take() {
                Some(value) => std::env::set_var(self.key, value),
                None => std::env::remove_var(self.key),
            }
            fdd_tsdb::clear_shared_pool();
        }
    }

    fn database_url() -> Option<String> {
        let explicit = std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty());
        if explicit.is_some() {
            return explicit;
        }
        Some("postgresql://openfdd:openfdd@127.0.0.1:5432/openfdd".into())
    }

    async fn connect() -> Option<sqlx::PgPool> {
        let explicit = std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .is_some_and(|value| !value.trim().is_empty());
        let url = database_url().unwrap_or_default();
        match sqlx::postgres::PgPoolOptions::new()
            .max_connections(2)
            .connect(&url)
            .await
        {
            Ok(pool) => Some(pool),
            Err(err) if explicit => panic!("OPENFDD_TEST_DATABASE_URL connect failed: {err}"),
            Err(err) => {
                eprintln!("skip: postgres fixture unavailable: {err}");
                None
            }
        }
    }

    async fn seed_equipment(pool: &sqlx::PgPool, site: &str, equipment_id: &str, kind: &str) {
        sqlx::query(
            "INSERT INTO site(site_id, dis) VALUES ($1, $1) ON CONFLICT (site_id) DO NOTHING",
        )
        .bind(site)
        .execute(pool)
        .await
        .expect("site");
        sqlx::query(
            "INSERT INTO building(building_id, site_id, dis) VALUES ($1, $1, $1)
             ON CONFLICT (building_id) DO NOTHING",
        )
        .bind(site)
        .execute(pool)
        .await
        .expect("building");
        sqlx::query(
            "INSERT INTO equipment(building_id, equipment_id, equip_type) VALUES ($1, $2, $3)
             ON CONFLICT (building_id, equipment_id) DO UPDATE SET equip_type = EXCLUDED.equip_type",
        )
        .bind(site)
        .bind(equipment_id)
        .bind(kind)
        .execute(pool)
        .await
        .expect("equipment");
    }

    async fn put(
        pool: &sqlx::PgPool,
        site: &str,
        equipment_id: &str,
        role: &str,
        openfdd_key: &str,
        val: f64,
    ) {
        let ts = Utc.with_ymd_and_hms(2026, 6, 1, 12, 0, 0).unwrap();
        sqlx::query(
            "INSERT INTO sample(ts, site_id, openfdd_key, val)
             VALUES ($1, $2, $3, $4)
             ON CONFLICT (site_id, openfdd_key, ts) DO UPDATE SET val = EXCLUDED.val",
        )
        .bind(ts)
        .bind(site)
        .bind(openfdd_key)
        .bind(val)
        .execute(pool)
        .await
        .expect("sample");
        crate::series_binding::bind_series(pool, site, equipment_id, role, openfdd_key).await;
    }

    fn scope() -> crate::timescale_analytics::AnalyticsSqlScope {
        crate::timescale_analytics::AnalyticsSqlScope {
            start: None,
            end: None,
            equipment_ids: Vec::new(),
        }
    }

    fn plotted_value(body: &crate::analytics::AnalyticsEnvelope, role: &str) -> Option<f64> {
        body.points
            .iter()
            .find_map(|row| row.get(role).and_then(serde_json::Value::as_f64))
    }

    fn coverage(body: &crate::analytics::AnalyticsEnvelope) -> &serde_json::Value {
        body.coverage.as_ref().expect("coverage")
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize the database env for the shared fixture"
    )]
    async fn readers_follow_current_binding_for_opaque_keys() {
        let _lock = crate::test_env_lock::lock_env();
        let Some(pool) = connect().await else {
            return;
        };
        let url = database_url().unwrap_or_default();
        let _db = EnvGuard::set("OPENFDD_DATABASE_URL", &url);
        fdd_tsdb::clear_shared_pool();
        crate::series_binding::ensure_authorized_series(&pool).await;
        for statement in [
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
        ] {
            crate::test_ddl::execute_idempotent_ddl(&pool, statement).await;
        }
        let token = uuid::Uuid::new_v4().simple().to_string();
        let site = format!("w2b{}", &token[..8]);
        let dotted = "a.b";
        let quoted = "say 'hi'";
        let unicode = "机组一";
        let moved = format!("moved{}", &token[..6]);
        let ambiguous = format!("amb{}", &token[..6]);
        let kept = format!("kept{}", &token[..6]);
        for (id, kind) in [
            (dotted, "ahu"),
            (quoted, "ahu"),
            (unicode, "ahu"),
            (moved.as_str(), "ahu"),
            (ambiguous.as_str(), "ahu"),
            (kept.as_str(), "ahu"),
            ("decoy", "ahu"),
        ] {
            seed_equipment(&pool, &site, id, kind).await;
        }

        put(&pool, &site, dotted, "sat", "not-a-role", 7.0).await;
        put(&pool, &site, "decoy", "sat", "a.sat", 99.0).await;
        put(&pool, &site, dotted, "duct_static", "urn:static", 1.2).await;
        put(&pool, &site, dotted, "duct_static_sp", "urn:static-sp", 1.5).await;
        put(&pool, &site, dotted, "fan_cmd", "urn:fan", 1.0).await;
        put(&pool, &site, quoted, "sat", "k'1", 8.0).await;
        put(&pool, &site, unicode, "o'clock", "点位", 9.0).await;
        put(&pool, &site, &ambiguous, "sat", "urn:one", 11.0).await;
        put(&pool, &site, &ambiguous, "sat", "urn:two", 22.0).await;
        put(&pool, &site, &kept, "sat", "purge-me", 1.0).await;
        put(&pool, &site, &kept, "mat", "keep-key", 2.0).await;

        let dotted_inspect = inspect_equipment(&site, dotted, None, 100, &scope())
            .await
            .expect("inspect")
            .expect("dotted series");
        assert_eq!(plotted_value(&dotted_inspect, "sat"), Some(7.0));
        assert_eq!(
            coverage(&dotted_inspect)["selected_openfdd_keys"]["sat"],
            json!("not-a-role")
        );
        assert_ne!(plotted_value(&dotted_inspect, "sat"), Some(99.0));

        let rcx = rcx_timeseries(
            &site,
            "sat",
            None,
            None,
            &["ahu"],
            false,
            &RcxQuery {
                max_points: 200,
                scope: scope(),
            },
        )
        .await
        .expect("rcx")
        .expect("rcx rows");
        let dotted_rcx = rcx.points.iter().any(|row| {
            row.get("equipment_id").and_then(|v| v.as_str()) == Some(dotted)
                && row.get("value_f").and_then(|v| v.as_f64()) == Some(7.0)
                && row.get("series").and_then(|v| v.as_str()) == Some("primary")
        });
        assert!(
            dotted_rcx,
            "rcx did not select the bound opaque key: {}",
            serde_json::to_string(&rcx).unwrap_or_default()
        );

        let plot = fdd_plot(Some(&site), dotted, "FC1", Some(50), None, None)
            .await
            .expect("fdd plot");
        assert_eq!(plot["ok"], json!(true), "{plot}");
        assert_eq!(
            plot["selected_openfdd_keys"]["duct_static"],
            json!("urn:static")
        );
        assert_eq!(
            plot["rows"][0]["duct_static"],
            json!(1.2),
            "fdd plot did not use the current key: {plot}"
        );

        crate::series_binding::bind_series(&pool, &site, &moved, "sat", "not-a-role").await;
        let left = inspect_equipment(&site, dotted, Some(&["sat".into()]), 100, &scope())
            .await
            .expect("inspect after reparent");
        assert!(
            left.as_ref()
                .is_none_or(|body| plotted_value(body, "sat").is_none()),
            "reparented series still plotted on the old equipment: {left:?}"
        );
        let arrived = inspect_equipment(&site, &moved, None, 100, &scope())
            .await
            .expect("moved inspect")
            .expect("moved series");
        assert_eq!(plotted_value(&arrived, "sat"), Some(7.0));
        let still: f64 = sqlx::query_scalar(
            "SELECT val FROM sample WHERE site_id = $1 AND openfdd_key = 'not-a-role'",
        )
        .bind(&site)
        .fetch_one(&pool)
        .await
        .expect("sample stays");
        assert_eq!(still, 7.0);

        crate::series_binding::bind_series(&pool, &site, &moved, "mat", "not-a-role").await;
        let edited = inspect_equipment(&site, &moved, None, 100, &scope())
            .await
            .expect("role edit")
            .expect("edited series");
        assert_eq!(plotted_value(&edited, "mat"), Some(7.0));
        assert!(plotted_value(&edited, "sat").is_none());

        let clash = inspect_equipment(&site, &ambiguous, None, 100, &scope())
            .await
            .expect("ambiguous")
            .expect("ambiguous envelope");
        let plotted = coverage(&clash)["columns_plotted"]
            .as_array()
            .expect("columns");
        assert!(
            plotted.iter().all(|role| role != "sat"),
            "{}",
            serde_json::to_string(&clash).unwrap_or_default()
        );
        assert_eq!(
            coverage(&clash)["ambiguous_roles"]["sat"]
                .as_array()
                .map(|k| k.len()),
            Some(2)
        );

        let quoted_inspect = inspect_equipment(&site, quoted, None, 100, &scope())
            .await
            .expect("quoted")
            .expect("quoted series");
        assert_eq!(plotted_value(&quoted_inspect, "sat"), Some(8.0));
        let unicode_inspect = inspect_equipment(&site, unicode, None, 100, &scope())
            .await
            .expect("unicode")
            .expect("unicode series");
        assert_eq!(plotted_value(&unicode_inspect, "o'clock"), Some(9.0));

        let mapping = package_mapping_from_samples(&site, Some(quoted))
            .await
            .expect("mapping");
        assert_eq!(mapping["ok"], json!(true), "{mapping}");
        assert_eq!(mapping["equipment"][0]["equipment_id"], json!(quoted));

        let tsdb = Tsdb::from_pool(pool.clone());
        let report = tsdb
            .purge_historian(&site, PurgeTarget::Point("purge-me"))
            .await
            .expect("purge");
        assert_eq!(report.samples_deleted, 1);
        let kept_n: i64 = sqlx::query_scalar(
            "SELECT count(*)::bigint FROM sample WHERE site_id = $1 AND openfdd_key = 'keep-key'",
        )
        .bind(&site)
        .fetch_one(&pool)
        .await
        .expect("kept samples");
        let purged_n: i64 = sqlx::query_scalar(
            "SELECT count(*)::bigint FROM sample WHERE site_id = $1 AND openfdd_key = 'purge-me'",
        )
        .bind(&site)
        .fetch_one(&pool)
        .await
        .expect("purged samples");
        assert_eq!(kept_n, 1);
        assert_eq!(purged_n, 0);
        let kept_inspect = inspect_equipment(&site, &kept, None, 100, &scope())
            .await
            .expect("kept inspect")
            .expect("kept series");
        assert_eq!(plotted_value(&kept_inspect, "mat"), Some(2.0));
        assert!(plotted_value(&kept_inspect, "sat").is_none());

        for sql in [
            "DELETE FROM sample WHERE site_id = $1",
            "DELETE FROM role_map WHERE building_id = $1",
            "DELETE FROM point_map WHERE site_id = $1",
            "DELETE FROM equipment WHERE building_id = $1",
            "DELETE FROM building WHERE building_id = $1",
            "DELETE FROM site WHERE site_id = $1",
        ] {
            sqlx::query(sql)
                .bind(&site)
                .execute(&pool)
                .await
                .expect("cleanup");
        }
    }
}

#[cfg(test)]
#[path = "oat_meteo_bound_contract_test.rs"]
mod oat_meteo_bound_contract_test;
#[cfg(test)]
#[path = "oat_meteo_t1404_test.rs"]
mod oat_meteo_t1404_test;
#[cfg(test)]
#[path = "vav1_t1407_test.rs"]
mod vav1_t1407_test;

#[cfg(test)]
#[path = "duplicate_timestamp_parity.rs"]
mod duplicate_timestamp_parity;

#[cfg(test)]
#[path = "zone_comfort_decode_fixture.rs"]
mod zone_comfort_decode_fixture;
