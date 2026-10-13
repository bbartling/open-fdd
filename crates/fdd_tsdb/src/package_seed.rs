//! Seed an Open-FDD package directory into Timescale (product import path).
//!
//! Prefer per-equipment `columns.csv` (materialized by package import with SQL
//! roles already stamped). Fall back to root `column_map.json` + `role_map.json`.
//! Uses PostgreSQL COPY (no Parquet / DataFusion).

use std::collections::{HashMap, HashSet};
use std::fs::File;
use std::io::{BufReader, Write};
use std::path::{Path, PathBuf};

use anyhow::{anyhow, Context, Result};
use chrono::{DateTime, Utc};
use serde_json::Value;

use crate::client::Tsdb;

fn load_json(path: &Path) -> Result<Value> {
    let text = std::fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    serde_json::from_str(&text).with_context(|| format!("parse {}", path.display()))
}

fn hs_to_sql_map(sql_root: &Path) -> HashMap<String, String> {
    let candidates = [
        sql_root.join("role_map.json"),
        sql_root.join("fdd/role_map.json"),
        PathBuf::from("sql/fdd/role_map.json"),
    ];
    for path in candidates {
        if let Ok(v) = load_json(&path) {
            if let Some(obj) = v.as_object() {
                // role_map.json is sql_role -> haystack-role
                let mut out = HashMap::new();
                for (sql, hs) in obj {
                    if let Some(hs) = hs.as_str() {
                        out.insert(hs.to_string(), sql.clone());
                    }
                }
                return out;
            }
        }
    }
    HashMap::new()
}

fn csv_to_sql_roles_from_column_map(
    equipment_id: &str,
    column_map: &Value,
    hs_to_sql: &HashMap<String, String>,
) -> HashMap<String, String> {
    let mut out = HashMap::new();
    let Some(eq) = column_map
        .pointer(&format!("/equipment/{equipment_id}"))
        .or_else(|| column_map.get(equipment_id))
    else {
        return out;
    };
    let Some(roles) = eq.get("column_roles").and_then(|v| v.as_object()) else {
        return out;
    };
    for (hs_role, csv_col) in roles {
        let Some(csv_col) = csv_col.as_str() else {
            continue;
        };
        let sql_role = hs_to_sql
            .get(hs_role)
            .cloned()
            .unwrap_or_else(|| hs_role.replace('-', "_"));
        out.insert(csv_col.to_string(), sql_role);
    }
    out
}

/// Product path: `columns.csv` already has SQL roles (sat/mat/…) after package materialize.
fn csv_to_sql_roles_from_columns_csv(eq_dir: &Path) -> Result<HashMap<String, String>> {
    let path = eq_dir.join("columns.csv");
    if !path.is_file() {
        return Ok(HashMap::new());
    }
    let file = File::open(&path).with_context(|| format!("open {}", path.display()))?;
    let mut reader = csv::ReaderBuilder::new()
        .flexible(true)
        .from_reader(BufReader::new(file));
    let headers = reader.headers()?.clone();
    let col_idx = headers
        .iter()
        .position(|h| h.eq_ignore_ascii_case("column"))
        .unwrap_or(0);
    let role_idx = headers
        .iter()
        .position(|h| h.eq_ignore_ascii_case("role"))
        .unwrap_or(1);
    let mut out = HashMap::new();
    for rec in reader.records() {
        let rec = rec?;
        let col = rec.get(col_idx).unwrap_or("").trim();
        let role = rec.get(role_idx).unwrap_or("").trim();
        if col.is_empty() || role.is_empty() {
            continue;
        }
        if matches!(
            col.to_ascii_lowercase().as_str(),
            "timestamp_utc" | "timestamp" | "ts" | "time"
        ) {
            continue;
        }
        out.insert(col.to_string(), role.to_string());
    }
    Ok(out)
}

fn equip_types_registry(package_root: &Path) -> HashMap<String, String> {
    let path = package_root.join("equipment_types.json");
    let Ok(v) = load_json(&path) else {
        return HashMap::new();
    };
    let mut out = HashMap::new();
    if let Some(obj) = v.as_object() {
        for (k, val) in obj {
            if let Some(t) = val.as_str() {
                out.insert(k.clone(), t.to_string());
            }
        }
    }
    out
}

fn equip_type_stamp(equipment_id: &str, column_map: &Value) -> Option<String> {
    let eq = column_map
        .pointer(&format!("/equipment/{equipment_id}"))
        .or_else(|| column_map.get(equipment_id))?;
    let raw = eq
        .get("equipment_type")
        .or_else(|| eq.get("equipType"))
        .and_then(|v| v.as_str())?;
    let low = raw.to_ascii_lowercase();
    Some(match low.as_str() {
        "ahu" | "rtu" => "ahu".into(),
        "vav" => "vav".into(),
        "chwplant" | "chiller" | "chw" | "chw_plant" => "chwPlant".into(),
        "boiler" | "hwplant" => "boiler".into(),
        "weather" => "weather".into(),
        other => other.into(),
    })
}

fn equipment_id_from_csv(rel: &Path) -> String {
    let parts: Vec<_> = rel
        .iter()
        .map(|s| s.to_string_lossy().into_owned())
        .collect();
    if parts.first().map(|s| s.as_str()) == Some("VAV") && parts.len() >= 2 {
        return parts[1].clone();
    }
    parts.first().cloned().unwrap_or_else(|| "equipment".into())
}

fn parse_ts(raw: &str) -> Option<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(raw)
        .ok()
        .map(|t| t.with_timezone(&Utc))
        .or_else(|| {
            chrono::NaiveDateTime::parse_from_str(raw, "%Y-%m-%dT%H:%M:%SZ")
                .ok()
                .map(|n| n.and_utc())
        })
        .or_else(|| {
            chrono::NaiveDateTime::parse_from_str(raw, "%Y-%m-%d %H:%M:%S")
                .ok()
                .map(|n| n.and_utc())
        })
}

async fn copy_csv_body(tsdb: &Tsdb, body: &[u8]) -> Result<u64> {
    if body.is_empty() {
        return Ok(0);
    }
    let mut conn = tsdb.pool().acquire().await.context("acquire pool")?;
    let mut copy = conn
        .copy_in_raw(
            "COPY sample (ts, site_id, openfdd_key, haystack_id, val) FROM STDIN WITH (FORMAT csv)",
        )
        .await
        .context("copy_in_raw")?;
    copy.send(body.to_vec()).await.context("copy send")?;
    let n = copy.finish().await.context("copy finish")?;
    Ok(n as u64)
}

async fn seed_one_csv(
    tsdb: &Tsdb,
    building_id: &str,
    equipment_id: &str,
    equip_type: Option<&str>,
    csv_path: &Path,
    col_to_role: &HashMap<String, String>,
) -> Result<u64> {
    if col_to_role.is_empty() {
        tracing::warn!(%equipment_id, path = %csv_path.display(), "skip seed: empty column→role map");
        return Ok(0);
    }
    tsdb.ensure_site_building(building_id).await?;
    tsdb.upsert_equipment(building_id, equipment_id, equip_type)
        .await?;

    let file = File::open(csv_path).with_context(|| format!("open {}", csv_path.display()))?;
    let mut reader = csv::ReaderBuilder::new()
        .flexible(true)
        .from_reader(BufReader::new(file));
    let headers = reader.headers()?.clone();
    let ts_col = headers
        .iter()
        .find(|h| {
            matches!(
                h.to_ascii_lowercase().as_str(),
                "timestamp_utc" | "timestamp" | "ts" | "time"
            )
        })
        .ok_or_else(|| anyhow!("no timestamp column in {}", csv_path.display()))?
        .to_string();

    // Dedupe (ts, openfdd_key) — columns.csv can map multiple vendor cols → one SQL role.
    let mut pending: HashMap<(String, String), f64> = HashMap::new();
    let mut roles_seen: HashSet<String> = HashSet::new();
    let mut total = 0u64;

    async fn flush_pending(
        tsdb: &Tsdb,
        building_id: &str,
        equipment_id: &str,
        pending: &mut HashMap<(String, String), f64>,
    ) -> Result<u64> {
        if pending.is_empty() {
            return Ok(0);
        }
        let mut buf: Vec<u8> = Vec::with_capacity(pending.len() * 64);
        for ((ts_s, openfdd_key), val) in pending.drain() {
            writeln!(
                &mut buf,
                "{ts_s},{building_id},{openfdd_key},{equipment_id},{val}"
            )
            .ok();
        }
        copy_csv_body(tsdb, &buf).await
    }

    for rec in reader.records() {
        let rec = rec?;
        let map: HashMap<&str, &str> = headers.iter().zip(rec.iter()).collect();
        let Some(ts_raw) = map.get(ts_col.as_str()).copied() else {
            continue;
        };
        let Some(ts) = parse_ts(ts_raw) else {
            continue;
        };
        let ts_s = ts.to_rfc3339();
        for (csv_col, sql_role) in col_to_role {
            let Some(raw) = map.get(csv_col.as_str()).copied() else {
                continue;
            };
            if raw.is_empty() {
                continue;
            }
            let Ok(val) = raw.parse::<f64>() else {
                continue;
            };
            let openfdd_key = format!("{equipment_id}.{sql_role}");
            roles_seen.insert(sql_role.clone());
            pending.insert((ts_s.clone(), openfdd_key), val);
        }
        if pending.len() >= 50_000 {
            total += flush_pending(tsdb, building_id, equipment_id, &mut pending).await?;
        }
    }
    total += flush_pending(tsdb, building_id, equipment_id, &mut pending).await?;

    for role in roles_seen {
        let openfdd_key = format!("{equipment_id}.{role}");
        sqlx::query(
            r#"
            INSERT INTO role_map(building_id, equipment_id, openfdd_key, role)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT DO NOTHING
            "#,
        )
        .bind(building_id)
        .bind(equipment_id)
        .bind(&openfdd_key)
        .bind(&role)
        .execute(tsdb.pool())
        .await
        .context("role_map")?;
        sqlx::query(
            r#"
            INSERT INTO point_map(site_id, openfdd_key, haystack_id, role, equipment_id)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT DO NOTHING
            "#,
        )
        .bind(building_id)
        .bind(&openfdd_key)
        .bind(&openfdd_key)
        .bind(&role)
        .bind(equipment_id)
        .execute(tsdb.pool())
        .await
        .context("point_map")?;
    }

    Ok(total)
}

/// Import package folder (BUILDING_50-style) into Timescale. No Parquet writes.
///
/// Replaces existing `sample` rows for `building_id` (fail-closed sole historian).
pub async fn seed_package_dir(
    tsdb: &Tsdb,
    package_root: &Path,
    building_id: &str,
    sql_root: &Path,
) -> Result<u64> {
    let column_map_path = package_root.join("column_map.json");
    let column_map = if column_map_path.is_file() {
        load_json(&column_map_path)?
    } else {
        Value::Object(Default::default())
    };
    let hs_to_sql = hs_to_sql_map(sql_root);
    let type_reg = equip_types_registry(package_root);

    tsdb.ensure_site_building(building_id).await?;
    // Full replace for this building — product path is Timescale-only (no dual-write).
    let deleted = sqlx::query("DELETE FROM sample WHERE site_id = $1")
        .bind(building_id)
        .execute(tsdb.pool())
        .await
        .context("delete prior samples")?
        .rows_affected();
    tracing::info!(%building_id, deleted, "Wave-X package seed: cleared prior samples");

    let mut total = 0u64;
    let mut csvs = walkdir_history(package_root)?;
    csvs.sort();
    for csv_path in csvs {
        let rel = csv_path
            .strip_prefix(package_root)
            .unwrap_or(csv_path.as_path());
        let equipment_id = equipment_id_from_csv(rel);
        let eq_dir = csv_path
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_else(|| package_root.to_path_buf());
        let mut col_to_role = csv_to_sql_roles_from_columns_csv(&eq_dir)?;
        if col_to_role.is_empty() {
            col_to_role = csv_to_sql_roles_from_column_map(&equipment_id, &column_map, &hs_to_sql);
        }
        // Weather packages often leave columns.csv roles blank — map dry_bulb → web_oa_t.
        if equipment_id.eq_ignore_ascii_case("weather")
            && !col_to_role.values().any(|r| r == "web_oa_t" || r == "oa_t")
        {
            if let Ok(headers) = csv::Reader::from_path(&csv_path).and_then(|mut r| {
                Ok(r.headers()?
                    .iter()
                    .map(|s| s.to_string())
                    .collect::<Vec<_>>())
            }) {
                for h in headers {
                    let low = h.to_ascii_lowercase();
                    if low.contains("dry_bulb") || low == "web_oa_t" || low == "oa_t" {
                        col_to_role.entry(h).or_insert_with(|| "web_oa_t".into());
                    }
                }
            }
        }
        let et = type_reg
            .get(&equipment_id)
            .cloned()
            .or_else(|| equip_type_stamp(&equipment_id, &column_map));
        let n = seed_one_csv(
            tsdb,
            building_id,
            &equipment_id,
            et.as_deref(),
            &csv_path,
            &col_to_role,
        )
        .await?;
        tracing::info!(%equipment_id, n, roles = col_to_role.len(), "Wave-X package seed equipment");
        total += n;
    }
    Ok(total)
}

fn walkdir_history(root: &Path) -> Result<Vec<PathBuf>> {
    let mut out = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let rd = std::fs::read_dir(&dir).with_context(|| format!("read_dir {}", dir.display()))?;
        for ent in rd {
            let ent = ent?;
            let path = ent.path();
            if path.is_dir() {
                stack.push(path);
            } else if path
                .file_name()
                .and_then(|s| s.to_str())
                .is_some_and(|n| n == "history_wide.csv" || n == "history.csv")
            {
                out.push(path);
            }
        }
    }
    Ok(out)
}
