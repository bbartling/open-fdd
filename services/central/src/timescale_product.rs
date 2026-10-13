//! Wave-X Soft-OPEN product paths on Timescale (Inspect / RCx / FDD series / FDD run).
//! No DataFusion / Parquet. Soft-OPEN ≠ FQ.

use std::collections::{BTreeSet, HashMap};
use std::path::{Path, PathBuf};

use anyhow::{anyhow, Context, Result};
use chrono::{DateTime, Utc};
use fdd_rules::{
    effective_param_strings, load_registry, load_tuning_profiles, rule_params, substitute_sql,
    RuleRegistry, RuleSpec,
};
use fdd_tsdb::Tsdb;
use serde_json::{json, Value};
use sqlx::{PgConnection, Row};

use crate::analytics::{
    envelope_with_engine, AnalyticsEnvelope, AnalyticsQuery, AnalyticsRequest,
};

const TS_ENGINE: &str = "timescale-sql";

fn sql_root() -> PathBuf {
    std::env::var_os("OPENFDD_SQL_ROOT")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("OPENFDD_SQL_RULES_DIR").map(PathBuf::from))
        .unwrap_or_else(|| PathBuf::from("sql/fdd"))
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
        other if other == "zone_family" => {
            vec!["vav", "fcu", "zone", "zone_other", "heatpump", "baseboard", "hp"]
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
                r.try_get::<Option<String>, _>("equip_type")
                    .ok()
                    .flatten(),
            )
        })
        .collect())
}

async fn roles_for_equipment(
    tsdb: &Tsdb,
    building_id: &str,
    equipment_id: &str,
) -> Result<Vec<String>> {
    let rows = sqlx::query(
        r#"
        SELECT DISTINCT split_part(openfdd_key, '.', 2) AS role
        FROM sample
        WHERE site_id = $1
          AND split_part(openfdd_key, '.', 1) = $2
          AND split_part(openfdd_key, '.', 2) <> ''
        ORDER BY 1
        "#,
    )
    .bind(building_id)
    .bind(equipment_id)
    .fetch_all(tsdb.pool())
    .await
    .context("roles_for_equipment")?;
    Ok(rows
        .into_iter()
        .filter_map(|r| r.try_get::<String, _>("role").ok())
        .filter(|r| safe_ident(r))
        .collect())
}

/// Wide inspect points for one equipment (SPA equipmentInspectionChart).
pub async fn inspect_equipment(
    building_id: &str,
    equipment_id: &str,
    columns: Option<&[String]>,
    max_points: usize,
) -> Result<Option<AnalyticsEnvelope>> {
    let eq = equipment_id.trim();
    if eq.is_empty() || building_id.trim().is_empty() {
        return Ok(None);
    }
    let tsdb = Tsdb::connect_from_env().await?;
    let plottable = roles_for_equipment(&tsdb, building_id, eq).await?;
    if plottable.is_empty() {
        return Ok(None);
    }
    const PREFERRED: &[&str] = &[
        "sat", "mat", "rat", "oa_t", "web_oa_t", "oa_damper_pct", "fan_status", "fan_cmd",
        "duct_static", "duct_static_sp", "sat_sp", "clg_valve_pct", "htg_valve_pct", "zone_t",
        "zone_flow", "chw_supply_t", "chw_return_t", "hw_supply_t", "hw_return_t", "occ_mode",
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
    // Pivot selected roles; span-preserving downsample via row_number.
    let mut filters = String::new();
    for (i, role) in selected.iter().enumerate() {
        if i > 0 {
            filters.push_str(" OR ");
        }
        filters.push_str(&format!("openfdd_key = '{eq}.{role}'"));
    }
    let mut max_cols = String::new();
    for role in &selected {
        max_cols.push_str(&format!(
            ", MAX(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = '{role}') AS \"{role}\""
        ));
    }
    let sql = format!(
        r#"
SELECT timestamp_utc {max_cols_outer}
FROM (
  SELECT
    ts AS timestamp_utc
    {max_cols},
    ROW_NUMBER() OVER (ORDER BY ts) AS _rn,
    COUNT(*) OVER () AS _cnt
  FROM sample
  WHERE site_id = $1 AND ({filters})
  GROUP BY ts
) s
WHERE _rn = 1 OR _rn = _cnt
   OR (_rn % (CASE WHEN ((_cnt + $2 - 1) / $2) > 1 THEN ((_cnt + $2 - 1) / $2) ELSE 1 END)) = 0
ORDER BY timestamp_utc
LIMIT $2
"#,
        max_cols_outer = selected
            .iter()
            .map(|r| format!(", \"{r}\""))
            .collect::<String>(),
        max_cols = max_cols,
        filters = filters,
    );
    let rows = sqlx::query(&sql)
        .bind(building_id)
        .bind(limit)
        .fetch_all(tsdb.pool())
        .await
        .context("inspect pivot")?;
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
            for c in &selected {
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
    env.rows = selected.iter().map(|c| json!({ "column": c })).collect();
    env.coverage = Some(json!({
        "equipment_id": eq,
        "row_count": env.points.len(),
        "point_count": env.points.len(),
        "plottable_columns": plottable,
        "columns_plotted": selected,
        "first_timestamp": first,
        "last_timestamp": last,
        "source": "timescale_sample",
        "building_id": building_id,
        "engine": TS_ENGINE,
    }));
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
    max_points: usize,
) -> Result<Option<AnalyticsEnvelope>> {
    if !safe_ident(role_col) {
        return Ok(None);
    }
    let tsdb = Tsdb::connect_from_env().await?;
    let equipment = list_equipment(&tsdb, building_id).await?;
    let ids: Vec<String> = equipment
        .into_iter()
        .filter(|(_, t)| equip_matches_kinds(t.as_deref(), eq_kinds))
        .map(|(id, _)| id)
        .collect();
    if ids.is_empty() {
        return Ok(None);
    }
    let limit = max_points.clamp(200, 20000) as i64;
    let pattern = format!("%.{role_col}");
    let fan_join = if filter_fan_on {
        "AND EXISTS (
            SELECT 1 FROM sample f
            WHERE f.site_id = s.site_id AND f.ts = s.ts
              AND f.openfdd_key = split_part(s.openfdd_key,'.',1) || '.fan_status'
              AND COALESCE(f.val, 0) > 0.05
          )"
    } else {
        ""
    };
    // Bound equipment via ANY($3)
    let sql = format!(
        r#"
SELECT timestamp_utc, equipment_id, value_f, motor_f
FROM (
  SELECT
    s.ts AS timestamp_utc,
    split_part(s.openfdd_key, '.', 1) AS equipment_id,
    s.val AS value_f,
    (
      SELECT CASE WHEN COALESCE(m.val, 0) > 0.05 THEN 1.0 ELSE 0.0 END
      FROM sample m
      WHERE m.site_id = s.site_id AND m.ts = s.ts
        AND m.openfdd_key = split_part(s.openfdd_key, '.', 1) || '.fan_status'
      LIMIT 1
    ) AS motor_f,
    ROW_NUMBER() OVER (ORDER BY s.ts, s.openfdd_key) AS _rn,
    COUNT(*) OVER () AS _cnt
  FROM sample s
  WHERE s.site_id = $1
    AND s.openfdd_key LIKE $2
    AND split_part(s.openfdd_key, '.', 1) = ANY($3)
    AND s.val IS NOT NULL
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
        .bind(&pattern)
        .bind(&ids)
        .bind(limit)
        .fetch_all(tsdb.pool())
        .await
        .context("rcx_timeseries")?;
    if rows.is_empty() {
        return Ok(None);
    }
    let mut points = Vec::new();
    for r in &rows {
        let ts = r
            .try_get::<DateTime<Utc>, _>("timestamp_utc")
            .ok()
            .map(|t| t.to_rfc3339())
            .unwrap_or_default();
        let eq = r
            .try_get::<String, _>("equipment_id")
            .unwrap_or_default();
        let value_f = r.try_get::<Option<f64>, _>("value_f").ok().flatten();
        let motor_f = r.try_get::<Option<f64>, _>("motor_f").ok().flatten();
        points.push(json!({
            "timestamp_utc": ts,
            "equipment_id": eq,
            "value_f": value_f,
            "series": "primary",
        }));
        if let Some(m) = motor_f {
            points.push(json!({
                "timestamp_utc": ts,
                "equipment_id": eq,
                "value_f": if m > 0.05 { 1.0 } else { 0.0 },
                "series": "motor",
            }));
        }
        let _ = (overlay_col, pair_return_col); // Soft-OPEN: primary + motor first
    }
    let mut env = envelope_with_engine(
        "rcx-timeseries-v1",
        &AnalyticsQuery {
            building_id: Some(building_id.to_string()),
            ..Default::default()
        },
        vec!["RCx role timeseries from Timescale sample (Wave-X Soft-OPEN)".into()],
        TS_ENGINE,
    );
    let n = points.len();
    env.points = points;
    env.coverage = Some(json!({
        "point_count": n,
        "role_col": role_col,
        "chart_kind": "timeseries",
        "source": "timescale_sample",
        "building_id": building_id,
        "equipment_n": ids.len(),
        "engine": TS_ENGINE,
    }));
    Ok(Some(env))
}

pub async fn rcx_oat_scatter(
    building_id: &str,
    y_col: &str,
    eq_kinds: &[&str],
    prefer_wetbulb: bool,
    max_points: usize,
) -> Result<Option<AnalyticsEnvelope>> {
    if !safe_ident(y_col) {
        return Ok(None);
    }
    let _ = prefer_wetbulb;
    let tsdb = Tsdb::connect_from_env().await?;
    let equipment = list_equipment(&tsdb, building_id).await?;
    let ids: Vec<String> = equipment
        .into_iter()
        .filter(|(_, t)| equip_matches_kinds(t.as_deref(), eq_kinds))
        .map(|(id, _)| id)
        .collect();
    if ids.is_empty() {
        return Ok(None);
    }
    let limit = max_points.clamp(200, 20000) as i64;
    let y_pat = format!("%.{y_col}");
    let rows = sqlx::query(
        r#"
        WITH y AS (
          SELECT ts, split_part(openfdd_key,'.',1) AS equipment_id, val AS y_f
          FROM sample
          WHERE site_id = $1
            AND openfdd_key LIKE $2
            AND split_part(openfdd_key,'.',1) = ANY($3)
            AND val IS NOT NULL
        ),
        oat AS (
          SELECT ts, val AS oat_f
          FROM sample
          WHERE site_id = $1
            AND (openfdd_key LIKE '%.web_oa_t' OR openfdd_key LIKE '%.oa_t')
        )
        SELECT y.ts AS timestamp_utc, y.equipment_id, y.y_f, o.oat_f
        FROM y
        JOIN oat o ON o.ts = y.ts
        WHERE o.oat_f IS NOT NULL
        ORDER BY y.ts DESC
        LIMIT $4
        "#,
    )
    .bind(building_id)
    .bind(&y_pat)
    .bind(&ids)
    .bind(limit)
    .fetch_all(tsdb.pool())
    .await
    .context("rcx_oat_scatter")?;
    if rows.is_empty() {
        return Ok(None);
    }
    let mut points = Vec::new();
    for r in &rows {
        points.push(json!({
            "timestamp_utc": r.try_get::<DateTime<Utc>, _>("timestamp_utc").ok().map(|t| t.to_rfc3339()),
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "y_f": r.try_get::<Option<f64>, _>("y_f").ok().flatten(),
            "oat_f": r.try_get::<Option<f64>, _>("oat_f").ok().flatten(),
            "dry_bulb_f": r.try_get::<Option<f64>, _>("oat_f").ok().flatten(),
        }));
    }
    let mut env = envelope_with_engine(
        "rcx-scatter-v1",
        &AnalyticsQuery {
            building_id: Some(building_id.to_string()),
            ..Default::default()
        },
        vec!["RCx OAT scatter from Timescale sample (Wave-X Soft-OPEN)".into()],
        TS_ENGINE,
    );
    let n = points.len();
    env.points = points;
    env.coverage = Some(json!({
        "point_count": n,
        "role_col": y_col,
        "chart_kind": "scatter_oat",
        "source": "timescale_sample",
        "building_id": building_id,
        "engine": TS_ENGINE,
    }));
    Ok(Some(env))
}

pub async fn rcx_box(
    building_id: &str,
    role_col: &str,
    eq_kinds: &[&str],
    filter_fan_on: bool,
    max_points: usize,
) -> Result<Option<AnalyticsEnvelope>> {
    // Soft-OPEN: reuse timeseries points; SPA box chart tolerates value_f rows.
    rcx_timeseries(
        building_id,
        role_col,
        None,
        None,
        eq_kinds,
        filter_fan_on,
        max_points,
    )
    .await
}

pub async fn rcx_zone_comfort_rank(
    building_id: &str,
    eq_kinds: &[&str],
    comfort_low_f: f64,
    comfort_high_f: f64,
) -> Result<Option<AnalyticsEnvelope>> {
    let tsdb = Tsdb::connect_from_env().await?;
    let equipment = list_equipment(&tsdb, building_id).await?;
    let ids: Vec<String> = equipment
        .into_iter()
        .filter(|(_, t)| equip_matches_kinds(t.as_deref(), eq_kinds))
        .map(|(id, _)| id)
        .collect();
    if ids.is_empty() {
        return Ok(None);
    }
    let rows = sqlx::query(
        r#"
        SELECT
          split_part(openfdd_key, '.', 1) AS equipment_id,
          100.0 * AVG(CASE WHEN val BETWEEN $2 AND $3 THEN 1.0 ELSE 0.0 END) AS comfort_pct,
          COUNT(*)::bigint AS n
        FROM sample
        WHERE site_id = $1
          AND openfdd_key LIKE '%.zone_t'
          AND split_part(openfdd_key, '.', 1) = ANY($4)
          AND val IS NOT NULL
        GROUP BY 1
        ORDER BY comfort_pct ASC
        LIMIT 200
        "#,
    )
    .bind(building_id)
    .bind(comfort_low_f)
    .bind(comfort_high_f)
    .bind(&ids)
    .fetch_all(tsdb.pool())
    .await
    .context("rcx_zone_comfort_rank")?;
    if rows.is_empty() {
        return Ok(None);
    }
    let mut points = Vec::new();
    for r in &rows {
        points.push(json!({
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "comfort_pct": r.try_get::<Option<f64>, _>("comfort_pct").ok().flatten(),
            "n": r.try_get::<i64, _>("n").unwrap_or(0),
            "value_f": r.try_get::<Option<f64>, _>("comfort_pct").ok().flatten(),
        }));
    }
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
    Ok(Some(env))
}

/// Dispatch for respond_query("equipment-inspect").
pub async fn inspect_json(req: &AnalyticsRequest) -> Result<Value> {
    let building = req
        .query
        .building_id
        .clone()
        .unwrap_or_else(|| "BUILDING_50".into());
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
    match inspect_equipment(&building, eq, columns.as_deref(), max_points).await? {
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
            Ok(env.to_json())
        }
    }
}

/// FDD plot series: wide role columns for one equipment + rule roles.
pub async fn fdd_series(
    building_id: Option<&str>,
    equipment_id: &str,
    rule_id: &str,
) -> Result<Value> {
    let bid = building_id.map(str::trim).filter(|s| !s.is_empty());
    let Some(building_id) = bid else {
        return Ok(json!({
            "ok": false,
            "error": "building_id required for Timescale FDD series",
            "engine": TS_ENGINE,
            "rows": [],
        }));
    };
    let reg = load_reg()?;
    let Some(rule) = reg
        .rules
        .iter()
        .find(|r| r.rule_id == rule_id || r.aliases.iter().any(|a| a == rule_id))
    else {
        return Ok(json!({"ok": false, "error": format!("unknown rule_id {rule_id}"), "rows": []}));
    };
    let mut roles: Vec<String> = rule.required_roles.clone();
    for r in &rule.optional_roles {
        if !roles.iter().any(|x| x == r) {
            roles.push(r.clone());
        }
    }
    roles.retain(|r| safe_ident(r));
    if roles.is_empty() {
        return Ok(json!({
            "ok": true,
            "equipment_id": equipment_id,
            "rule_id": rule.rule_id,
            "rows": [],
            "roles": [],
            "engine": TS_ENGINE,
        }));
    }
    let tsdb = Tsdb::connect_from_env().await?;
    let present = roles_for_equipment(&tsdb, building_id, equipment_id).await?;
    let present_set: BTreeSet<_> = present.iter().cloned().collect();
    let missing: Vec<String> = rule
        .required_roles
        .iter()
        .filter(|r| !present_set.contains(*r))
        .cloned()
        .collect();
    if !missing.is_empty() {
        return Ok(json!({
            "ok": false,
            "error": format!("missing roles for rule {}: {}", rule.rule_id, missing.join(", ")),
            "missing_roles": missing,
            "equipment_id": equipment_id,
            "rule_id": rule.rule_id,
            "building_id": building_id,
            "rows": [],
            "engine": TS_ENGINE,
        }));
    }
    roles.retain(|r| present_set.contains(r));
    let mut max_cols = String::new();
    for role in &roles {
        max_cols.push_str(&format!(
            ", MAX(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = '{role}') AS \"{role}\""
        ));
    }
    let mut filters = String::new();
    for (i, role) in roles.iter().enumerate() {
        if i > 0 {
            filters.push_str(" OR ");
        }
        filters.push_str(&format!("openfdd_key = '{equipment_id}.{role}'"));
    }
    let sql = format!(
        r#"
SELECT timestamp_utc {sel}
FROM (
  SELECT
    ts AS timestamp_utc
    {max_cols},
    ROW_NUMBER() OVER (ORDER BY ts) AS _rn,
    COUNT(*) OVER () AS _cnt
  FROM sample
  WHERE site_id = $1 AND ({filters})
  GROUP BY ts
) s
WHERE _rn = 1 OR _rn = _cnt
   OR (_rn % (CASE WHEN ((_cnt + $2 - 1) / $2) > 1 THEN ((_cnt + $2 - 1) / $2) ELSE 1 END)) = 0
ORDER BY timestamp_utc
LIMIT $2
"#,
        sel = roles.iter().map(|r| format!(", \"{r}\"")).collect::<String>(),
        max_cols = max_cols,
        filters = filters,
    );
    let rows = sqlx::query(&sql)
        .bind(building_id)
        .bind(4000_i64)
        .fetch_all(tsdb.pool())
        .await
        .context("fdd_series pivot")?;
    let mut out_rows = Vec::with_capacity(rows.len());
    for r in &rows {
        let mut row = json!({
            "timestamp_utc": r.try_get::<DateTime<Utc>, _>("timestamp_utc").ok().map(|t| t.to_rfc3339()),
            "equipment_id": equipment_id,
        });
        if let Some(obj) = row.as_object_mut() {
            for c in &roles {
                let v = r.try_get::<Option<f64>, _>(c.as_str()).ok().flatten();
                obj.insert(c.clone(), json!(v));
            }
            // Soft-OPEN: confirmed_fault filled after /api/fdd/run when result JSON exists
            obj.insert("confirmed_fault".into(), Value::Null);
        }
        out_rows.push(row);
    }
    // Overlay confirmed_fault from last result file if present (best-effort).
    if let Ok(fault_map) = load_confirmed_fault_hint(building_id, equipment_id, &rule.rule_id) {
        for row in &mut out_rows {
            if let Some(ts) = row.get("timestamp_utc").and_then(|v| v.as_str()) {
                if let Some(flag) = fault_map.get(ts) {
                    if let Some(obj) = row.as_object_mut() {
                        obj.insert("confirmed_fault".into(), json!(flag));
                    }
                }
            }
        }
    }
    Ok(json!({
        "ok": true,
        "equipment_id": equipment_id,
        "rule_id": rule.rule_id,
        "building_id": building_id,
        "roles": roles,
        "rows": out_rows,
        "downsampled": true,
        "max_points": 4000,
        "has_confirmed_fault": out_rows.iter().any(|r| r.get("confirmed_fault").and_then(|v| v.as_bool()).is_some()),
        "engine": TS_ENGINE,
        "source": "timescale_sample",
    }))
}

fn results_dir(building_id: &str) -> PathBuf {
    let base = if let Ok(p) = std::env::var("OPENFDD_RULE_RESULTS_DIR") {
        PathBuf::from(p)
    } else if let Ok(url) = std::env::var("OPENFDD_STORAGE_URL") {
        PathBuf::from(url.trim_start_matches("file://")).join("rule_results")
    } else if let Ok(ws) = std::env::var("OPENFDD_WORKSPACE") {
        PathBuf::from(ws).join("openfdd").join("rule_results")
    } else {
        PathBuf::from(".cache/rule_results")
    };
    base.join(format!("building={building_id}"))
}

fn load_confirmed_fault_hint(
    building_id: &str,
    equipment_id: &str,
    rule_id: &str,
) -> Result<HashMap<String, bool>> {
    let path = results_dir(building_id).join(format!("{rule_id}.json"));
    let text = std::fs::read_to_string(path)?;
    let body: Value = serde_json::from_str(&text)?;
    let mut map = HashMap::new();
    if let Some(series) = body.get("fault_series").and_then(|v| v.as_array()) {
        for row in series {
            let eq = row.get("equipment_id").and_then(|v| v.as_str()).unwrap_or("");
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

fn render_rule_sql(reg: &RuleRegistry, rule: &RuleSpec, poll: f64, confirm: u32) -> Result<String> {
    let path = rule_sql_path(reg, &rule.sql_file);
    let raw = std::fs::read_to_string(&path)
        .with_context(|| format!("read rule sql {}", path.display()))?;
    let mut params = rule_params(poll, confirm);
    if let Ok(tuning) = load_tuning_profiles(Path::new(&reg.rules_dir)) {
        if let Ok(tuned) = effective_param_strings(rule, &tuning, None, None, None) {
            for (k, v) in tuned {
                params.insert(k, v);
            }
        }
    }
    Ok(substitute_sql(&raw, &params))
}

/// Rule SQL often yields `fault_hours` as PostgreSQL `numeric` (CASE with `0.0`).
/// sqlx `try_get::<f64>` fails on numeric → Soft-OPEN run-now reported 0h.
/// Cast through a wrapper SELECT so the product path always gets float8.
fn wrap_rule_sql_for_hours(sql_body: &str) -> String {
    let inner = sql_body.trim().trim_end_matches(';').trim();
    format!(
        "SELECT equipment_id::text AS equipment_id, \
         fault_hours::double precision AS fault_hours \
         FROM ({inner}) AS _fdd_rule_q"
    )
}

fn confirm_seconds_from_payload(payload: &Value, rule: &RuleSpec) -> u32 {
    if let Some(cs) = payload
        .get("confirmation_seconds")
        .and_then(|v| v.as_f64().or_else(|| v.as_u64().map(|u| u as f64)))
        .filter(|v| v.is_finite() && *v >= 0.0)
    {
        return cs.round() as u32;
    }
    if let Some(params) = payload.get("params") {
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
            .and_then(|v| v.as_f64())
            .filter(|v| v.is_finite() && *v >= 0.0)
        {
            return (cm * 60.0).round() as u32;
        }
    }
    rule.confirm_seconds
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

async fn ensure_history_table(conn: &mut PgConnection, roles: &[String]) -> Result<()> {
    let mut cols = String::from(
        "equipment_id text not null, timestamp_utc timestamptz not null",
    );
    for r in roles {
        cols.push_str(&format!(", \"{r}\" double precision"));
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
) -> Result<i64> {
    if roles.is_empty() {
        return Ok(0);
    }
    let mut max_cols = String::new();
    for role in roles {
        max_cols.push_str(&format!(
            ", MAX(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = '{role}') AS \"{role}\""
        ));
    }
    let mut filters = String::new();
    for (i, role) in roles.iter().enumerate() {
        if i > 0 {
            filters.push_str(" OR ");
        }
        filters.push_str(&format!("openfdd_key = '{equipment_id}.{role}'"));
    }
    let insert_cols = roles
        .iter()
        .map(|r| format!("\"{r}\""))
        .collect::<Vec<_>>()
        .join(", ");
    let sql = format!(
        r#"
INSERT INTO history (equipment_id, timestamp_utc, {insert_cols})
SELECT '{equipment_id}', ts {max_cols}
FROM sample
WHERE site_id = $1 AND ({filters})
GROUP BY ts
"#
    );
    let res = sqlx::query(&sql)
        .bind(building_id)
        .execute(&mut *conn)
        .await
        .context("fill history")?;
    Ok(res.rows_affected() as i64)
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
    let mut equipment = list_equipment(&tsdb, &building_id).await?;
    if let Some(eq) = &equipment_filter {
        equipment.retain(|(id, _)| id == eq);
    }
    if equipment.is_empty() {
        // Fall back to distinct equipment from sample
        let rows = sqlx::query(
            r#"
            SELECT DISTINCT split_part(openfdd_key,'.',1) AS equipment_id
            FROM sample WHERE site_id = $1
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
    }

    let out_dir = results_dir(&building_id);
    std::fs::create_dir_all(&out_dir)?;
    let _ = std::fs::remove_file(out_dir.join("_dirty.json"));

    let poll = 300.0_f64;
    let t0 = std::time::Instant::now();
    let mut rules_run = 0u32;
    let mut rules_succeeded = 0u32;
    let mut rules_failed = 0u32;
    let mut rules_skipped = 0u32;
    let mut all_results = Vec::new();

    for rule in rules {
        rules_run += 1;
        let kinds: Vec<&str> = rule.equipment_kinds.iter().map(String::as_str).collect();
        // Exact equipment_id (after caller filter) always runs; otherwise type-first.
        let targets: Vec<(String, Option<String>)> = if equipment_filter.is_some() {
            equipment.clone()
        } else {
            equipment
                .iter()
                .filter(|(_, t)| kinds.is_empty() || equip_matches_kinds(t.as_deref(), &kinds))
                .cloned()
                .collect()
        };
        if targets.is_empty() {
            rules_skipped += 1;
            continue;
        }

        let confirm = confirm_seconds_from_payload(payload, rule);
        let sql_body = match render_rule_sql(&reg, rule, poll, confirm) {
            Ok(s) => wrap_rule_sql_for_hours(&s),
            Err(e) => {
                rules_failed += 1;
                tracing::warn!(rule = %rule.rule_id, error = %e, "render rule sql failed");
                continue;
            }
        };

        let mut role_set: BTreeSet<String> = rule.required_roles.iter().cloned().collect();
        for r in &rule.optional_roles {
            role_set.insert(r.clone());
        }
        // Common gate roles
        for extra in ["fan_status", "fan_cmd", "occ_mode"] {
            role_set.insert(extra.into());
        }
        let roles: Vec<String> = role_set.into_iter().filter(|r| safe_ident(r)).collect();

        let mut rule_rows = Vec::new();
        let mut ok_any = false;
        for (eq_id, _) in &targets {
            let mut tx = tsdb.pool().begin().await?;
            if let Err(e) = ensure_history_table(&mut tx, &roles).await {
                rules_failed += 1;
                tracing::warn!(rule = %rule.rule_id, error = %e, "temp history");
                break;
            }
            let n = fill_history_for_equipment(&mut tx, &building_id, eq_id, &roles).await?;
            if n == 0 {
                rule_rows.push(json!({
                    "equipment_id": eq_id,
                    "fault_hours": 0.0,
                    "status": "SKIP_NO_HISTORY",
                    "missing_roles": rule.required_roles,
                }));
                let _ = tx.rollback().await;
                continue;
            }
            match sqlx::query(&sql_body).fetch_all(&mut *tx).await {
                Ok(rows) => {
                    let mut hours = 0.0_f64;
                    for r in &rows {
                        hours += row_fault_hours(r);
                    }
                    rule_rows.push(json!({
                        "equipment_id": eq_id,
                        "fault_hours": hours,
                        "status": if hours > 0.0 { "FAULT" } else { "PASS" },
                        "sample_rows": n,
                        "confirm_seconds": confirm,
                        "poll_seconds": poll,
                    }));
                    ok_any = true;
                    let _ = tx.commit().await;
                }
                Err(e) => {
                    rule_rows.push(json!({
                        "equipment_id": eq_id,
                        "fault_hours": 0.0,
                        "status": "ERROR",
                        "notes": e.to_string(),
                    }));
                    let _ = tx.rollback().await;
                }
            }
        }
        if ok_any {
            rules_succeeded += 1;
        } else {
            rules_failed += 1;
        }
        let body = json!({
            "rule_id": rule.rule_id,
            "engine": TS_ENGINE,
            "building_id": building_id,
            "rows": rule_rows,
            "generated_at": Utc::now().to_rfc3339(),
        });
        let path = out_dir.join(format!("{}.json", rule.rule_id));
        std::fs::write(&path, serde_json::to_vec_pretty(&body)?)?;
        all_results.extend(rule_rows.into_iter().map(|mut row| {
            if let Some(obj) = row.as_object_mut() {
                obj.insert("rule_id".into(), json!(rule.rule_id));
            }
            row
        }));
    }

    let meta = json!({
        "ok": true,
        "engine": TS_ENGINE,
        "building_id": building_id,
        "historian": "timescale",
        "dual_write": false,
        "rules_run": rules_run,
        "rules_succeeded": rules_succeeded,
        "rules_failed": rules_failed,
        "rules_skipped": rules_skipped,
        "total_ms": t0.elapsed().as_millis() as u64,
        "results_dir": out_dir.display().to_string(),
        "results": all_results,
        "note": "Wave-X Soft-OPEN Timescale postgres-sql run-now; Soft-OPEN ≠ FQ",
    });
    std::fs::write(out_dir.join("_run_meta.json"), serde_json::to_vec_pretty(&meta)?)?;
    Ok(meta)
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

/// Convert AnalyticsEnvelope helper for historian_stub.
pub fn envelope_engine() -> &'static str {
    TS_ENGINE
}
