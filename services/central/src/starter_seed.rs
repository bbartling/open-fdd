//! Empty-database seed of the Building 50 starter pack.
//!
//! This is the in-image copy of `scripts/timescale/auto_seed.py` for a central
//! process that has no Python runtime. It uses the same `seed_meta` key
//! (`building50_seed` = `ok`) and the same rule: copy only into an empty
//! historian. It never deletes rows. A wipe is `scripts/timescale/purge_historian.py`
//! or the one-shot `OPENFDD_RESET_DB` token in `db_lifecycle`. After that wipe
//! the historian is empty, so the next boot copies Building 50 again.
//! Synthetic stress data is not seeded here.

use std::collections::{BTreeMap, BTreeSet};
use std::fs::File;
use std::io::BufReader;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Duration;

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use fdd_core::columns::haystack_point_to_role;
use flate2::read::GzDecoder;
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;
use sqlx::{PgPool, Row};

pub const STARTER_BUILDING_ID: &str = "BUILDING_50";
/// Same marker `scripts/timescale/auto_seed.py` writes. Either path seeing `ok`
/// leaves existing rows alone.
const SEED_KEY: &str = "building50_seed";
const BATCH: usize = 4_000;

static STATUS: Mutex<String> = Mutex::new(String::new());

pub fn status_label() -> String {
    STATUS.lock().unwrap_or_else(|p| p.into_inner()).clone()
}

fn set_status(label: &str) {
    *STATUS.lock().unwrap_or_else(|p| p.into_inner()) = label.to_string();
}

pub fn should_seed_starter(sample_rows: i64, disabled: bool) -> bool {
    !disabled && sample_rows == 0
}

fn starter_disabled() -> bool {
    match std::env::var("OPENFDD_STARTER_SEED") {
        Ok(raw) => matches!(
            raw.trim().to_ascii_lowercase().as_str(),
            "0" | "false" | "no" | "off"
        ),
        Err(_) => false,
    }
}

pub fn spawn() {
    if starter_disabled() {
        set_status("disabled");
        tracing::info!("starter seed disabled (OPENFDD_STARTER_SEED)");
        return;
    }
    if std::env::var("OPENFDD_DATABASE_URL")
        .ok()
        .map(|u| u.trim().is_empty())
        .unwrap_or(true)
    {
        set_status("skipped_no_database");
        return;
    }
    set_status("running");
    tokio::spawn(async move {
        match run().await {
            Ok(SeedReport::Skipped { rows }) => {
                set_status("skipped_existing");
                tracing::info!(rows, "starter seed skipped; historian already has samples");
            }
            Ok(SeedReport::Seeded { rows }) => {
                set_status("seeded");
                tracing::info!(
                    rows,
                    building_id = STARTER_BUILDING_ID,
                    "starter seed committed"
                );
                match run_starter_rules().await {
                    Ok(body) => {
                        set_status("seeded");
                        tracing::info!(
                            rules_succeeded = body
                                .get("rules_succeeded")
                                .and_then(|v| v.as_u64())
                                .unwrap_or(0),
                            "starter rules wrote pass/fault results"
                        );
                    }
                    Err(err) => {
                        set_status("seeded_rules_failed");
                        tracing::warn!(error = %err, "starter rules did not finish");
                    }
                }
            }
            Err(err) => {
                set_status("failed");
                tracing::warn!(error = %err, "starter seed failed; existing rows were not replaced");
            }
        }
    });
}

async fn run_starter_rules() -> Result<Value> {
    let payload = json!({
        "building_id": STARTER_BUILDING_ID,
        "rule_ids": [
            "FC1",
            "AHU-SATDEV",
            "AHU-DUCTHI",
            "FAN-RUNTIME-HOURS",
            "FC10",
            "FC12",
            "CHW-1"
        ],
    });
    crate::timescale_product::run_fdd_registry(&payload)
        .await
        .context("starter rule run")
}

enum SeedReport {
    Skipped { rows: i64 },
    Seeded { rows: u64 },
}

async fn run() -> Result<SeedReport> {
    let url = std::env::var("OPENFDD_DATABASE_URL").context("OPENFDD_DATABASE_URL")?;
    let pool = PgPoolOptions::new()
        .max_connections(1)
        .acquire_timeout(Duration::from_secs(20))
        .connect(url.trim())
        .await
        .context("starter seed connect")?;
    let existing: i64 = sqlx::query_scalar("SELECT COUNT(*)::bigint FROM sample")
        .fetch_one(&pool)
        .await
        .context("count sample")?;
    if !should_seed_starter(existing, false) || building50_already_marked(&pool).await {
        return Ok(SeedReport::Skipped { rows: existing });
    }
    let pack_dir = pack_dir().context("Building 50 starter pack not found")?;
    let pack: Value = serde_json::from_str(
        &std::fs::read_to_string(pack_dir.join("pack.json")).context("read pack.json")?,
    )
    .context("parse pack.json")?;
    let Some(rows) = seed_pack(&pool, &pack_dir, &pack).await? else {
        return Ok(SeedReport::Skipped { rows: existing });
    };
    write_sidecars(&pack).ok();
    let _ = open_fdd_edge_prototype::csv_ingest::register_package_dataset(
        STARTER_BUILDING_ID,
        rows,
        6,
        &json!({"source": "starter_building_50"}),
    );
    Ok(SeedReport::Seeded { rows })
}

async fn building50_already_marked(pool: &PgPool) -> bool {
    let marked: Option<String> = sqlx::query_scalar("SELECT value FROM seed_meta WHERE key = $1")
        .bind(SEED_KEY)
        .fetch_optional(pool)
        .await
        .ok()
        .flatten();
    marked.as_deref() == Some("ok")
}

fn pack_dir() -> Option<PathBuf> {
    if let Some(p) = std::env::var_os("OPENFDD_STARTER_PACK") {
        let path = PathBuf::from(p);
        if path.join("pack.json").is_file() {
            return Some(path);
        }
    }
    let candidates = [
        PathBuf::from("/app/fixtures/starter/building_50"),
        PathBuf::from("fixtures/starter/building_50"),
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/starter/building_50"),
    ];
    candidates
        .into_iter()
        .find(|p| p.join("pack.json").is_file())
}

async fn seed_pack(pool: &PgPool, pack_dir: &Path, pack: &Value) -> Result<Option<u64>> {
    let mut tx = pool.begin().await.context("begin starter seed")?;
    sqlx::query("SET LOCAL statement_timeout = 0")
        .execute(&mut *tx)
        .await
        .ok();
    sqlx::query("LOCK TABLE sample IN SHARE ROW EXCLUSIVE MODE")
        .execute(&mut *tx)
        .await
        .context("lock sample")?;
    let existing: i64 = sqlx::query_scalar("SELECT COUNT(*)::bigint FROM sample")
        .fetch_one(&mut *tx)
        .await
        .context("recheck sample")?;
    if existing > 0 {
        return Ok(None);
    }
    sqlx::query(
        "INSERT INTO site(site_id, dis, timezone, enabled) VALUES ($1, $2, 'UTC', true)
         ON CONFLICT (site_id) DO NOTHING",
    )
    .bind(STARTER_BUILDING_ID)
    .bind("Building 50")
    .execute(&mut *tx)
    .await?;
    sqlx::query(
        "INSERT INTO building(building_id, site_id, dis, timezone) VALUES ($1, $1, $2, 'UTC')
         ON CONFLICT (building_id) DO NOTHING",
    )
    .bind(STARTER_BUILDING_ID)
    .bind("Building 50")
    .execute(&mut *tx)
    .await?;

    let mut total = 0u64;
    let files = pack
        .get("history_files")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    for file in &files {
        let equipment_id = file
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim();
        let rel = file.get("path").and_then(|v| v.as_str()).unwrap_or("");
        if equipment_id.is_empty() || rel.is_empty() {
            continue;
        }
        let equip_type = equip_type_for(pack, equipment_id);
        sqlx::query(
            "INSERT INTO equipment(building_id, equipment_id, equip_type)
             VALUES ($1, $2, $3)
             ON CONFLICT (building_id, equipment_id) DO UPDATE
               SET equip_type = COALESCE(EXCLUDED.equip_type, equipment.equip_type)",
        )
        .bind(STARTER_BUILDING_ID)
        .bind(equipment_id)
        .bind(equip_type.as_deref())
        .execute(&mut *tx)
        .await?;
        let path = history_path(pack_dir, rel);
        let n = load_wide_csv(&mut tx, equipment_id, &path).await?;
        tracing::info!(equipment_id, n, "starter history staged");
        total += n;
    }
    upsert_points(&mut tx, pack).await?;
    sqlx::query(
        "INSERT INTO seed_meta(key, value) VALUES ($1, 'ok')
         ON CONFLICT (key) DO UPDATE SET value = 'ok', updated_at = now()",
    )
    .bind(SEED_KEY)
    .execute(&mut *tx)
    .await?;
    sqlx::query(
        "INSERT INTO seed_meta(key, value) VALUES ('building50_samples', $1)
         ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
    )
    .bind(total.to_string())
    .execute(&mut *tx)
    .await?;
    sqlx::query(
        "INSERT INTO seed_meta(key, value) VALUES ('building50_role_mode', 'sql_roles_via_starter_pack')
         ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
    )
    .execute(&mut *tx)
    .await?;
    if total == 0 {
        anyhow::bail!("starter pack staged zero samples");
    }
    tx.commit().await.context("commit starter seed")?;
    Ok(Some(total))
}

fn history_path(pack_dir: &Path, rel: &str) -> PathBuf {
    let plain = pack_dir.join(rel);
    let gz = pack_dir.join(format!("{rel}.gz"));
    if gz.is_file() {
        gz
    } else {
        plain
    }
}

fn read_history_text(path: &Path) -> Result<String> {
    let file = File::open(path).with_context(|| format!("open {}", path.display()))?;
    let mut text = String::new();
    if path.extension().and_then(|e| e.to_str()) == Some("gz") {
        std::io::Read::read_to_string(&mut BufReader::new(GzDecoder::new(file)), &mut text)?;
    } else {
        std::io::Read::read_to_string(&mut BufReader::new(file), &mut text)?;
    }
    Ok(text)
}

async fn load_wide_csv(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    equipment_id: &str,
    path: &Path,
) -> Result<u64> {
    let text = read_history_text(path)?;
    let mut csv_reader = csv::ReaderBuilder::new()
        .flexible(true)
        .from_reader(text.as_bytes());
    let headers = csv_reader.headers()?.clone();
    let mut roles: Vec<(usize, String, String)> = Vec::new();
    for (idx, header) in headers.iter().enumerate() {
        let name = header.trim();
        if name.is_empty()
            || matches!(
                name.to_ascii_lowercase().as_str(),
                "timestamp_utc" | "timestamp" | "ts" | "time"
            )
        {
            continue;
        }
        let sql_role = haystack_point_to_role(name);
        if sql_role.is_empty() || !safe_role(&sql_role) {
            continue;
        }
        let point_id = format!(
            "BUILDING_50_{}_{}",
            equipment_id.to_ascii_uppercase(),
            name.to_ascii_uppercase().replace('-', "_")
        );
        roles.push((idx, sql_role, point_id));
    }
    let ts_idx = headers
        .iter()
        .position(|h| h.eq_ignore_ascii_case("timestamp_utc"))
        .unwrap_or(0);
    let mut ts_buf = Vec::new();
    let mut site_buf = Vec::new();
    let mut key_buf = Vec::new();
    let mut hs_buf = Vec::new();
    let mut val_buf = Vec::new();
    let mut n = 0u64;
    for rec in csv_reader.records() {
        let rec = rec?;
        let raw_ts = rec.get(ts_idx).unwrap_or("").trim();
        let Some(ts) = parse_ts(raw_ts) else {
            continue;
        };
        for (idx, role, point_id) in &roles {
            let cell = rec.get(*idx).unwrap_or("").trim();
            if cell.is_empty() {
                continue;
            }
            let Ok(val) = cell.parse::<f64>() else {
                continue;
            };
            if !val.is_finite() {
                continue;
            }
            ts_buf.push(ts);
            site_buf.push(STARTER_BUILDING_ID.to_string());
            key_buf.push(format!("{equipment_id}.{role}"));
            hs_buf.push(point_id.clone());
            val_buf.push(val);
            if ts_buf.len() >= BATCH {
                n += flush_samples(tx, &ts_buf, &site_buf, &key_buf, &hs_buf, &val_buf).await?;
                ts_buf.clear();
                site_buf.clear();
                key_buf.clear();
                hs_buf.clear();
                val_buf.clear();
            }
        }
    }
    if !ts_buf.is_empty() {
        n += flush_samples(tx, &ts_buf, &site_buf, &key_buf, &hs_buf, &val_buf).await?;
    }
    Ok(n)
}

async fn flush_samples(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    ts: &[DateTime<Utc>],
    sites: &[String],
    keys: &[String],
    hs: &[String],
    vals: &[f64],
) -> Result<u64> {
    let rows: Vec<fdd_tsdb::writer::SampleWrite<'_>> = ts
        .iter()
        .zip(sites)
        .zip(keys)
        .zip(hs)
        .zip(vals)
        .map(
            |((((ts, site), key), hs), val)| fdd_tsdb::writer::SampleWrite {
                ts: *ts,
                site_id: site,
                openfdd_key: key,
                haystack_id: Some(hs),
                val: Some(*val),
                unit: None,
                quality: None,
            },
        )
        .collect();
    let stats = fdd_tsdb::writer::write_samples(tx, &rows)
        .await
        .context("insert sample batch")?;
    Ok(stats.inserted + stats.updated)
}

async fn upsert_points(tx: &mut sqlx::Transaction<'_, sqlx::Postgres>, pack: &Value) -> Result<()> {
    let points = pack
        .pointer("/haystack/points")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    for point in points {
        let equipment_id = point
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim();
        let haystack_role = point.get("role").and_then(|v| v.as_str()).unwrap_or("");
        let sql_role = haystack_point_to_role(haystack_role);
        if equipment_id.is_empty() || !safe_role(&sql_role) {
            continue;
        }
        let key = format!("{equipment_id}.{sql_role}");
        let haystack_id = point
            .get("point_id")
            .and_then(|v| v.as_str())
            .unwrap_or(key.as_str());
        let unit = point.get("canonical_unit").and_then(|v| v.as_str());
        sqlx::query(
            "INSERT INTO point_map(site_id, openfdd_key, haystack_id, role, unit, equipment_id)
             VALUES ($1, $2, $3, $4, $5, $6)
             ON CONFLICT (site_id, openfdd_key) DO UPDATE
               SET haystack_id = EXCLUDED.haystack_id,
                   role = EXCLUDED.role,
                   unit = EXCLUDED.unit,
                   equipment_id = EXCLUDED.equipment_id",
        )
        .bind(STARTER_BUILDING_ID)
        .bind(&key)
        .bind(haystack_id)
        .bind(&sql_role)
        .bind(unit)
        .bind(equipment_id)
        .execute(&mut **tx)
        .await?;
        sqlx::query(
            "INSERT INTO role_map(building_id, equipment_id, openfdd_key, role, unit)
             VALUES ($1, $2, $3, $4, $5)
             ON CONFLICT (building_id, equipment_id, openfdd_key) DO UPDATE
               SET role = EXCLUDED.role, unit = EXCLUDED.unit",
        )
        .bind(STARTER_BUILDING_ID)
        .bind(equipment_id)
        .bind(&key)
        .bind(&sql_role)
        .bind(unit)
        .execute(&mut **tx)
        .await?;
    }
    Ok(())
}

fn equip_type_for(pack: &Value, equipment_id: &str) -> Option<String> {
    let equipment = pack
        .pointer("/haystack/equipment")
        .and_then(|v| v.as_array())?;
    let row = equipment
        .iter()
        .find(|e| e.get("equipment_id").and_then(|v| v.as_str()) == Some(equipment_id))?;
    if let Some(explicit) = row.get("equipType").and_then(|v| v.as_str()) {
        return Some(normalize_equip_type(explicit));
    }
    let markers = row.get("markers").and_then(|v| v.as_array());
    let tags: Vec<String> = markers
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(|s| s.to_ascii_lowercase()))
                .collect()
        })
        .unwrap_or_default();
    if tags.iter().any(|t| t == "ahu") {
        return Some("ahu".into());
    }
    if tags.iter().any(|t| t == "chiller") {
        return Some("chwPlant".into());
    }
    if tags.iter().any(|t| t == "boiler") {
        return Some("boiler".into());
    }
    if tags.iter().any(|t| t == "weather") {
        return Some("weather".into());
    }
    None
}

fn normalize_equip_type(raw: &str) -> String {
    match raw.trim().to_ascii_lowercase().as_str() {
        "ahu" | "rtu" => "ahu".into(),
        "chiller" | "chw" | "chwplant" | "chw_plant" => "chwPlant".into(),
        "boiler" => "boiler".into(),
        "weather" => "weather".into(),
        other => other.to_string(),
    }
}

fn safe_role(role: &str) -> bool {
    !role.is_empty() && role.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
}

fn parse_ts(raw: &str) -> Option<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(raw)
        .ok()
        .map(|t| t.with_timezone(&Utc))
}

fn write_sidecars(pack: &Value) -> Result<()> {
    let root = open_fdd_edge_prototype::historian::store::workspace_dir()
        .join("data")
        .join("csv_buildings")
        .join(STARTER_BUILDING_ID);
    std::fs::create_dir_all(&root)?;
    std::fs::write(
        root.join("manifest.json"),
        serde_json::to_vec_pretty(&json!({
            "schema": "openfdd_package_v1",
            "building_id": STARTER_BUILDING_ID,
            "source": "starter_building_50",
            "dis": "Building 50"
        }))?,
    )?;
    let mut by_equip: BTreeMap<String, BTreeSet<(String, String)>> = BTreeMap::new();
    let points = pack
        .pointer("/haystack/points")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let mut meta_points = Vec::new();
    let mut meta_equip = Vec::new();
    if let Some(equipment) = pack
        .pointer("/haystack/equipment")
        .and_then(|v| v.as_array())
    {
        for eq in equipment {
            let id = eq
                .get("equipment_id")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if id.is_empty() {
                continue;
            }
            let tags = eq
                .get("markers")
                .and_then(|v| v.as_array())
                .cloned()
                .unwrap_or_default();
            meta_equip.push(json!({
                "equipment_id": id,
                "display_name": eq.get("dis").and_then(|v| v.as_str()).unwrap_or(id),
                "haystack_tags": tags,
            }));
        }
    }
    for point in &points {
        let equipment_id = point
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let haystack_role = point.get("role").and_then(|v| v.as_str()).unwrap_or("");
        let sql_role = haystack_point_to_role(haystack_role);
        if equipment_id.is_empty() || sql_role.is_empty() {
            continue;
        }
        by_equip
            .entry(equipment_id.to_string())
            .or_default()
            .insert((sql_role.clone(), haystack_role.to_string()));
        let tags = point
            .get("markers")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        meta_points.push(json!({
            "equipment_id": equipment_id,
            "column": sql_role,
            "point_id": point.get("point_id"),
            "haystack_tags": tags,
            "unit": point.get("canonical_unit"),
            "his": true,
            "provenance": "starter_building_50"
        }));
    }
    for (equipment_id, roles) in &by_equip {
        let dir = root.join(equipment_id);
        std::fs::create_dir_all(&dir)?;
        let mut body = String::from("column,role\n");
        for (sql_role, _) in roles {
            body.push_str(sql_role);
            body.push(',');
            body.push_str(sql_role);
            body.push('\n');
        }
        std::fs::write(dir.join("columns.csv"), body)?;
    }
    let meta = json!({
        "schema": "openfdd_semantic_meta_v1",
        "building_id": STARTER_BUILDING_ID,
        "note": "Building 50 starter seed",
        "equipment": meta_equip,
        "points": meta_points
    });
    std::fs::write(
        root.join("semantic_meta.json"),
        serde_json::to_vec_pretty(&meta)?,
    )?;
    Ok(())
}

/// Rebuild the semantic sidecar from Timescale when a container restart dropped
/// the workspace copy but the historian still has the building.
pub async fn ensure_semantic_sidecar(building_id: &str) -> Result<bool> {
    let id = building_id.trim();
    if id.is_empty() {
        return Ok(false);
    }
    let root = open_fdd_edge_prototype::historian::store::workspace_dir()
        .join("data")
        .join("csv_buildings")
        .join(id);
    if root.join("semantic_meta.json").is_file() {
        return Ok(false);
    }
    let url = match std::env::var("OPENFDD_DATABASE_URL") {
        Ok(url) if !url.trim().is_empty() => url,
        _ => return Ok(false),
    };
    let pool = PgPoolOptions::new()
        .max_connections(1)
        .acquire_timeout(Duration::from_secs(8))
        .connect(url.trim())
        .await?;
    let rows = sqlx::query(
        "SELECT equipment_id, openfdd_key, role, haystack_id
         FROM point_map WHERE site_id = $1 ORDER BY equipment_id, openfdd_key",
    )
    .bind(id)
    .fetch_all(&pool)
    .await?;
    if rows.is_empty() {
        return Ok(false);
    }
    std::fs::create_dir_all(&root)?;
    let mut points = Vec::new();
    let mut equipment = BTreeSet::new();
    for row in &rows {
        let equipment_id: String = row.try_get("equipment_id").unwrap_or_default();
        let role: String = row.try_get("role").unwrap_or_default();
        let haystack_id: String = row.try_get("haystack_id").unwrap_or_default();
        if equipment_id.is_empty() || role.is_empty() {
            continue;
        }
        equipment.insert(equipment_id.clone());
        points.push(json!({
            "equipment_id": equipment_id,
            "column": role,
            "point_id": haystack_id,
            "haystack_tags": ["point", "his"],
            "his": true,
            "provenance": "timescale_point_map"
        }));
    }
    let equip_rows =
        sqlx::query("SELECT equipment_id, equip_type FROM equipment WHERE building_id = $1")
            .bind(id)
            .fetch_all(&pool)
            .await
            .unwrap_or_default();
    let mut meta_equip = Vec::new();
    for row in equip_rows {
        let equipment_id: String = row.try_get("equipment_id").unwrap_or_default();
        let equip_type: Option<String> = row.try_get("equip_type").ok().flatten();
        let mut tags = vec![json!("equip")];
        if let Some(t) = equip_type {
            tags.push(json!(t));
        }
        meta_equip.push(json!({
            "equipment_id": equipment_id,
            "haystack_tags": tags
        }));
    }
    if meta_equip.is_empty() {
        for id in equipment {
            meta_equip.push(json!({"equipment_id": id, "haystack_tags": ["equip"]}));
        }
    }
    std::fs::write(
        root.join("semantic_meta.json"),
        serde_json::to_vec_pretty(&json!({
            "schema": "openfdd_semantic_meta_v1",
            "building_id": id,
            "equipment": meta_equip,
            "points": points
        }))?,
    )?;
    if !root.join("manifest.json").is_file() {
        std::fs::write(
            root.join("manifest.json"),
            serde_json::to_vec_pretty(&json!({
                "schema": "openfdd_package_v1",
                "building_id": id,
                "source": "timescale_point_map"
            }))?,
        )?;
    }
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mapped_sql_roles(pack: &Value, equipment_id: &str) -> BTreeSet<String> {
        let mut out = BTreeSet::new();
        let Some(points) = pack.pointer("/haystack/points").and_then(|v| v.as_array()) else {
            return out;
        };
        for point in points {
            if point.get("equipment_id").and_then(|v| v.as_str()) != Some(equipment_id) {
                continue;
            }
            let role = point.get("role").and_then(|v| v.as_str()).unwrap_or("");
            let sql = haystack_point_to_role(role);
            if safe_role(&sql) {
                out.insert(sql);
            }
        }
        out
    }

    #[test]
    fn empty_database_is_the_only_boot_seed() {
        assert!(should_seed_starter(0, false));
        assert!(!should_seed_starter(1, false));
        assert!(!should_seed_starter(0, true));
    }

    #[test]
    fn building_50_ahu_covers_starter_rule_roles() {
        let pack: Value = serde_json::from_str(include_str!(
            "../../../fixtures/starter/building_50/pack.json"
        ))
        .unwrap();
        let ahu = mapped_sql_roles(&pack, "AHU_1");
        for role in [
            "duct_static",
            "duct_static_sp",
            "fan_cmd",
            "fan_status",
            "sat",
            "sat_sp",
            "mat",
            "oa_t",
        ] {
            assert!(ahu.contains(role), "AHU_1 missing {role}");
        }
        let chiller = mapped_sql_roles(&pack, "CHILLER_1");
        assert!(chiller.contains("chw_supply_t"));
        assert!(chiller.contains("chw_return_t"));
        assert_eq!(
            equip_type_for(&pack, "CHILLER_1").as_deref(),
            Some("chwPlant")
        );
        assert_eq!(equip_type_for(&pack, "AHU_1").as_deref(), Some("ahu"));
        assert_eq!(equip_type_for(&pack, "weather").as_deref(), Some("weather"));
    }
}
