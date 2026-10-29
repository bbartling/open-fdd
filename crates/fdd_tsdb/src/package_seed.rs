//! Seed / append an Open-FDD package directory into Timescale (product import path).
//!
//! Prefer per-equipment `columns.csv` (materialized by package import with SQL
//! roles already stamped). Fall back to root `column_map.json` + `role_map.json`.
//! Uses staging + atomic promote for full replace; upsert for incremental append.
//! No Parquet / DataFusion.

use std::collections::{HashMap, HashSet};
use std::fs::File;
use std::io::{BufReader, Write};
use std::path::{Path, PathBuf};

use anyhow::{anyhow, bail, Context, Result};
use chrono::{DateTime, Utc};
use serde_json::Value;

use crate::client::Tsdb;
use crate::ingest_si::{prepare_numeric_sample, PointMapBinding, SampleDeclaredContext};
use crate::sample::{SampleRow, UpsertBatch};
use fdd_core::MetricUnitsContract;

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
fn csv_to_sql_roles_from_columns_csv(
    eq_dir: &Path,
) -> Result<(HashMap<String, String>, HashMap<String, String>)> {
    let path = eq_dir.join("columns.csv");
    if !path.is_file() {
        return Ok((HashMap::new(), HashMap::new()));
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
    let unit_idx = headers.iter().position(|h| h.eq_ignore_ascii_case("unit"));
    let mut roles = HashMap::new();
    let mut units = HashMap::new();
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
        roles.insert(col.to_string(), role.to_string());
        if let Some(uix) = unit_idx {
            let unit = rec.get(uix).unwrap_or("").trim();
            if !unit.is_empty() {
                units.insert(col.to_string(), unit.to_string());
            }
        }
    }
    Ok((roles, units))
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

struct SeedPlan {
    equipment_id: String,
    equip_type: Option<String>,
    csv_path: PathBuf,
    col_to_role: HashMap<String, String>,
    col_to_unit: HashMap<String, String>,
    unit_system: Option<String>,
}

fn package_unit_system(package_root: &Path) -> Option<String> {
    for name in ["session_config.json", "manifest.json"] {
        let path = package_root.join(name);
        let Ok(v) = load_json(&path) else {
            continue;
        };
        if let Some(sys) = v
            .pointer("/session_config/unit_system")
            .or_else(|| v.get("unit_system"))
            .and_then(|u| u.as_str())
        {
            let trimmed = sys.trim();
            if !trimmed.is_empty() {
                return Some(trimmed.to_string());
            }
        }
    }
    None
}

fn resolve_col_to_role(
    equipment_id: &str,
    eq_dir: &Path,
    csv_path: &Path,
    column_map: &Value,
    hs_to_sql: &HashMap<String, String>,
) -> Result<(HashMap<String, String>, HashMap<String, String>)> {
    let (mut col_to_role, col_to_unit) = csv_to_sql_roles_from_columns_csv(eq_dir)?;
    if col_to_role.is_empty() {
        col_to_role = csv_to_sql_roles_from_column_map(equipment_id, column_map, hs_to_sql);
    }
    if equipment_id.eq_ignore_ascii_case("weather")
        && !col_to_role.values().any(|r| r == "web_oa_t" || r == "oa_t")
    {
        if let Ok(headers) = csv::Reader::from_path(csv_path).and_then(|mut r| {
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
    Ok((col_to_role, col_to_unit))
}

fn build_seed_plans(
    package_root: &Path,
    sql_root: &Path,
    only_equipment: Option<&[String]>,
) -> Result<(Value, HashMap<String, String>, Vec<SeedPlan>)> {
    let column_map_path = package_root.join("column_map.json");
    let column_map = if column_map_path.is_file() {
        load_json(&column_map_path)?
    } else {
        Value::Object(Default::default())
    };
    let hs_to_sql = hs_to_sql_map(sql_root);
    let type_reg = equip_types_registry(package_root);
    let mut csvs = walkdir_history(package_root)?;
    csvs.sort();
    let package_unit_system = package_unit_system(package_root);
    let mut plans = Vec::new();
    for csv_path in csvs {
        let rel = csv_path
            .strip_prefix(package_root)
            .unwrap_or(csv_path.as_path());
        let equipment_id = equipment_id_from_csv(rel);
        if let Some(only) = only_equipment {
            if !only.iter().any(|e| e == &equipment_id) {
                continue;
            }
        }
        let eq_dir = csv_path
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_else(|| package_root.to_path_buf());
        let (col_to_role, col_to_unit) =
            resolve_col_to_role(&equipment_id, &eq_dir, &csv_path, &column_map, &hs_to_sql)?;
        if col_to_role.is_empty() {
            bail!(
                "equipment {equipment_id}: empty column→role map before Timescale mutation ({})",
                csv_path.display()
            );
        }
        let et = type_reg
            .get(&equipment_id)
            .cloned()
            .or_else(|| equip_type_stamp(&equipment_id, &column_map));
        plans.push(SeedPlan {
            equipment_id,
            equip_type: et,
            csv_path,
            col_to_role,
            col_to_unit,
            unit_system: package_unit_system.clone(),
        });
    }
    Ok((column_map, type_reg, plans))
}

async fn ensure_stage_table(tsdb: &Tsdb) -> Result<()> {
    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS sample_import_stage (
          import_id     uuid NOT NULL,
          ts            timestamptz NOT NULL,
          site_id       text NOT NULL,
          openfdd_key   text NOT NULL,
          haystack_id   text,
          val           double precision,
          unit          text,
          quality       text,
          PRIMARY KEY (import_id, site_id, openfdd_key, ts)
        )
        "#,
    )
    .execute(tsdb.pool())
    .await
    .context("create sample_import_stage")?;
    sqlx::query("ALTER TABLE sample_import_stage ADD COLUMN IF NOT EXISTS unit text")
        .execute(tsdb.pool())
        .await
        .context("stage unit column")?;
    sqlx::query("ALTER TABLE sample_import_stage ADD COLUMN IF NOT EXISTS quality text")
        .execute(tsdb.pool())
        .await
        .context("stage quality column")?;
    Ok(())
}

async fn copy_stage_csv(tsdb: &Tsdb, body: &[u8]) -> Result<u64> {
    if body.is_empty() {
        return Ok(0);
    }
    let mut conn = tsdb.pool().acquire().await.context("acquire pool")?;
    let mut copy = conn
        .copy_in_raw(
            "COPY sample_import_stage (import_id, ts, site_id, openfdd_key, haystack_id, val, unit, quality) FROM STDIN WITH (FORMAT csv)",
        )
        .await
        .context("copy_in_raw stage")?;
    copy.send(body.to_vec()).await.context("copy send")?;
    let n = copy.finish().await.context("copy finish")?;
    Ok(n as u64)
}

#[derive(Clone)]
struct StagedSample {
    val: f64,
    unit: Option<String>,
    quality: Option<String>,
}

struct CsvStageMaps<'a> {
    col_to_role: &'a HashMap<String, String>,
    col_to_unit: &'a HashMap<String, String>,
    unit_system: Option<&'a str>,
}

async fn stage_one_csv(
    tsdb: &Tsdb,
    import_id: uuid::Uuid,
    building_id: &str,
    equipment_id: &str,
    csv_path: &Path,
    maps: CsvStageMaps<'_>,
) -> Result<(u64, HashSet<String>)> {
    let contract = MetricUnitsContract::load_embedded().context("metric units contract")?;
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

    let mut pending: HashMap<(String, String), StagedSample> = HashMap::new();
    let mut roles_seen: HashSet<String> = HashSet::new();
    let import_s = import_id.to_string();

    async fn flush_stage(
        tsdb: &Tsdb,
        import_s: &str,
        building_id: &str,
        equipment_id: &str,
        pending: &mut HashMap<(String, String), StagedSample>,
    ) -> Result<u64> {
        if pending.is_empty() {
            return Ok(0);
        }
        let mut buf: Vec<u8> = Vec::with_capacity(pending.len() * 96);
        for ((ts_s, openfdd_key), staged) in pending.drain() {
            let unit = staged.unit.as_deref().unwrap_or("");
            let quality = staged.quality.as_deref().unwrap_or("");
            writeln!(
                &mut buf,
                "{import_s},{ts_s},{building_id},{openfdd_key},{equipment_id},{},{unit},{quality}",
                staged.val
            )
            .ok();
        }
        copy_stage_csv(tsdb, &buf).await
    }

    let mut total = 0u64;
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
        for (csv_col, sql_role) in maps.col_to_role {
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
            let csv_unit = maps.col_to_unit.get(csv_col).map(String::as_str);
            let prepared = prepare_numeric_sample(
                &contract,
                val,
                PointMapBinding::default(),
                SampleDeclaredContext {
                    role: Some(sql_role.as_str()),
                    csv_column_unit: csv_unit,
                    unit_system: maps.unit_system,
                    ..Default::default()
                },
            );
            pending.insert(
                (ts_s.clone(), openfdd_key),
                StagedSample {
                    val: prepared.val.unwrap_or(val),
                    unit: prepared.unit,
                    quality: prepared.quality,
                },
            );
        }
        if pending.len() >= 50_000 {
            total += flush_stage(tsdb, &import_s, building_id, equipment_id, &mut pending).await?;
        }
    }
    total += flush_stage(tsdb, &import_s, building_id, equipment_id, &mut pending).await?;
    Ok((total, roles_seen))
}

async fn upsert_roles(
    tsdb: &Tsdb,
    building_id: &str,
    equipment_id: &str,
    roles_seen: &HashSet<String>,
) -> Result<()> {
    for role in roles_seen {
        let openfdd_key = format!("{equipment_id}.{role}");
        sqlx::query(
            r#"
            INSERT INTO role_map(building_id, equipment_id, openfdd_key, role)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (building_id, equipment_id, openfdd_key) DO UPDATE
              SET role = EXCLUDED.role
            "#,
        )
        .bind(building_id)
        .bind(equipment_id)
        .bind(&openfdd_key)
        .bind(role)
        .execute(tsdb.pool())
        .await
        .context("role_map")?;
        sqlx::query(
            r#"
            INSERT INTO point_map(site_id, openfdd_key, haystack_id, role, equipment_id)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (site_id, openfdd_key) DO UPDATE
              SET haystack_id = EXCLUDED.haystack_id,
                  role = EXCLUDED.role,
                  equipment_id = EXCLUDED.equipment_id
            "#,
        )
        .bind(building_id)
        .bind(&openfdd_key)
        .bind(&openfdd_key)
        .bind(role)
        .bind(equipment_id)
        .execute(tsdb.pool())
        .await
        .context("point_map")?;
    }
    Ok(())
}

/// Debug and test builds can abort after this package's sample delete, inside
/// the open transaction, so the delete and the equipment rows roll back together.
/// Release binaries compile the hook out.
fn abort_after_sample_delete() -> bool {
    #[cfg(debug_assertions)]
    {
        std::env::var("OPENFDD_PACKAGE_SEED_FAIL_AFTER_DELETE")
            .ok()
            .is_some_and(|value| value == "1")
    }
    #[cfg(not(debug_assertions))]
    {
        false
    }
}

async fn discard_stage(tsdb: &Tsdb, import_id: uuid::Uuid) {
    if let Err(err) = sqlx::query("DELETE FROM sample_import_stage WHERE import_id = $1")
        .bind(import_id)
        .execute(tsdb.pool())
        .await
    {
        tracing::warn!(%err, %import_id, "package seed could not discard its stage rows");
    }
}

async fn ensure_site_building_tx(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    building_id: &str,
) -> Result<()> {
    sqlx::query(
        r#"
        INSERT INTO site(site_id, dis, timezone, enabled)
        VALUES ($1, $1, 'UTC', true)
        ON CONFLICT (site_id) DO NOTHING
        "#,
    )
    .bind(building_id)
    .execute(&mut **tx)
    .await
    .context("ensure site")?;
    sqlx::query(
        r#"
        INSERT INTO building(building_id, site_id, dis, timezone)
        VALUES ($1, $1, $1, 'UTC')
        ON CONFLICT (building_id) DO NOTHING
        "#,
    )
    .bind(building_id)
    .execute(&mut **tx)
    .await
    .context("ensure building")?;
    Ok(())
}

async fn upsert_equipment_tx(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    building_id: &str,
    equipment_id: &str,
    equip_type: Option<&str>,
) -> Result<()> {
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
    .execute(&mut **tx)
    .await
    .context("upsert equipment")?;
    Ok(())
}

async fn upsert_roles_tx(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    building_id: &str,
    equipment_id: &str,
    roles_seen: &HashSet<String>,
) -> Result<()> {
    for role in roles_seen {
        let openfdd_key = format!("{equipment_id}.{role}");
        sqlx::query(
            r#"
            INSERT INTO role_map(building_id, equipment_id, openfdd_key, role)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (building_id, equipment_id, openfdd_key) DO UPDATE
              SET role = EXCLUDED.role
            "#,
        )
        .bind(building_id)
        .bind(equipment_id)
        .bind(&openfdd_key)
        .bind(role)
        .execute(&mut **tx)
        .await
        .context("role_map")?;
        sqlx::query(
            r#"
            INSERT INTO point_map(site_id, openfdd_key, haystack_id, role, equipment_id)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (site_id, openfdd_key) DO UPDATE
              SET haystack_id = EXCLUDED.haystack_id,
                  role = EXCLUDED.role,
                  equipment_id = EXCLUDED.equipment_id
            "#,
        )
        .bind(building_id)
        .bind(&openfdd_key)
        .bind(&openfdd_key)
        .bind(role)
        .bind(equipment_id)
        .execute(&mut **tx)
        .await
        .context("point_map")?;
    }
    Ok(())
}

/// Full package replace: validate → stage → one transaction for this package.
///
/// Scratch rows live in `sample_import_stage`. Equipment, roles, and samples
/// for this building commit together. A failure rolls that transaction back
/// and discards the stage rows. Other buildings are not deleted, and the
/// database is not re-initialized.
pub async fn seed_package_dir(
    tsdb: &Tsdb,
    package_root: &Path,
    building_id: &str,
    sql_root: &Path,
) -> Result<u64> {
    let (_column_map, _type_reg, plans) = build_seed_plans(package_root, sql_root, None)?;
    if plans.is_empty() {
        bail!(
            "no history_wide.csv / history.csv under {}",
            package_root.display()
        );
    }

    ensure_stage_table(tsdb).await?;
    let import_id = uuid::Uuid::new_v4();
    discard_stage(tsdb, import_id).await;

    let mut staged = 0u64;
    let mut role_sets: Vec<(String, Option<String>, HashSet<String>)> = Vec::new();
    for plan in &plans {
        let staged_one = stage_one_csv(
            tsdb,
            import_id,
            building_id,
            &plan.equipment_id,
            &plan.csv_path,
            CsvStageMaps {
                col_to_role: &plan.col_to_role,
                col_to_unit: &plan.col_to_unit,
                unit_system: plan.unit_system.as_deref(),
            },
        )
        .await;
        let (n, roles) = match staged_one {
            Ok(pair) => pair,
            Err(err) => {
                discard_stage(tsdb, import_id).await;
                return Err(err).with_context(|| {
                    format!("stage {} ({})", plan.equipment_id, plan.csv_path.display())
                });
            }
        };
        tracing::info!(
            equipment_id = %plan.equipment_id,
            n,
            roles = plan.col_to_role.len(),
            "Wave-X package seed staged equipment"
        );
        staged += n;
        role_sets.push((plan.equipment_id.clone(), plan.equip_type.clone(), roles));
    }

    if staged == 0 {
        discard_stage(tsdb, import_id).await;
        bail!("staged zero samples for {building_id}; preserving last-good Timescale history");
    }

    let committed = promote_staged_package(tsdb, import_id, building_id, &plans, &role_sets).await;
    if committed.is_err() {
        discard_stage(tsdb, import_id).await;
    }
    committed
}

async fn promote_staged_package(
    tsdb: &Tsdb,
    import_id: uuid::Uuid,
    building_id: &str,
    plans: &[SeedPlan],
    role_sets: &[(String, Option<String>, HashSet<String>)],
) -> Result<u64> {
    let mut tx = tsdb.pool().begin().await.context("begin promote txn")?;
    ensure_site_building_tx(&mut tx, building_id).await?;
    for plan in plans {
        upsert_equipment_tx(
            &mut tx,
            building_id,
            &plan.equipment_id,
            plan.equip_type.as_deref(),
        )
        .await?;
    }
    let deleted = crate::writer::delete_samples_outside_stage(&mut tx, import_id, building_id)
        .await
        .context("delete prior samples in promote txn")?;
    if abort_after_sample_delete() {
        // Dropping `tx` rolls back this package's equipment rows and the
        // sample delete. The caller discards stage rows after the error.
        bail!(
            "package seed aborted after partial writes for {building_id}; transaction rolled back"
        );
    }
    let inserted = crate::writer::promote_stage(&mut tx, import_id, building_id)
        .await
        .context("promote stage → sample")?;
    for (equipment_id, _et, roles) in role_sets {
        upsert_roles_tx(&mut tx, building_id, equipment_id, roles).await?;
    }
    sqlx::query("DELETE FROM sample_import_stage WHERE import_id = $1")
        .bind(import_id)
        .execute(&mut *tx)
        .await
        .context("cleanup stage")?;
    tx.commit().await.context("commit promote")?;
    tracing::info!(
        %building_id,
        deleted,
        inserted,
        "Wave-X package seed: atomic promote complete"
    );
    Ok(inserted)
}

/// Incremental append/upsert for touched equipment only. Commits before success.
pub async fn append_package_equipment(
    tsdb: &Tsdb,
    package_root: &Path,
    building_id: &str,
    sql_root: &Path,
    equipment_ids: &[String],
) -> Result<u64> {
    if equipment_ids.is_empty() {
        bail!("append requires at least one equipment_id");
    }
    let (_column_map, _type_reg, plans) =
        build_seed_plans(package_root, sql_root, Some(equipment_ids))?;
    if plans.is_empty() {
        bail!(
            "no history CSV for equipment {:?} under {}",
            equipment_ids,
            package_root.display()
        );
    }
    tsdb.ensure_site_building(building_id).await?;
    let mut total = 0u64;
    for plan in plans {
        tsdb.upsert_equipment(building_id, &plan.equipment_id, plan.equip_type.as_deref())
            .await?;
        let (n, roles) = upsert_one_csv(
            tsdb,
            building_id,
            &plan.equipment_id,
            &plan.csv_path,
            &plan.col_to_role,
            &plan.col_to_unit,
            plan.unit_system.as_deref(),
        )
        .await?;
        upsert_roles(tsdb, building_id, &plan.equipment_id, &roles).await?;
        tracing::info!(
            equipment_id = %plan.equipment_id,
            n,
            "Wave-X package append equipment committed"
        );
        total += n;
    }
    Ok(total)
}

/// Remap roles for one equipment and re-upsert its CSV into Timescale (no Parquet).
pub async fn remap_equipment_roles(
    tsdb: &Tsdb,
    package_root: &Path,
    building_id: &str,
    equipment_id: &str,
    sql_root: &Path,
) -> Result<u64> {
    append_package_equipment(
        tsdb,
        package_root,
        building_id,
        sql_root,
        &[equipment_id.to_string()],
    )
    .await
}

async fn upsert_one_csv(
    tsdb: &Tsdb,
    building_id: &str,
    equipment_id: &str,
    csv_path: &Path,
    col_to_role: &HashMap<String, String>,
    col_to_unit: &HashMap<String, String>,
    unit_system: Option<&str>,
) -> Result<(u64, HashSet<String>)> {
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

    let mut batch = UpsertBatch { rows: Vec::new() };
    let mut roles_seen: HashSet<String> = HashSet::new();
    let mut total = 0u64;

    for rec in reader.records() {
        let rec = rec?;
        let map: HashMap<&str, &str> = headers.iter().zip(rec.iter()).collect();
        let Some(ts_raw) = map.get(ts_col.as_str()).copied() else {
            continue;
        };
        let Some(ts) = parse_ts(ts_raw) else {
            continue;
        };
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
            let mut row = SampleRow::new(ts, building_id, openfdd_key, Some(val));
            row.haystack_id = Some(equipment_id.to_string());
            row.equipment_id = Some(equipment_id.to_string());
            row.role = Some(sql_role.clone());
            if let Some(unit) = col_to_unit.get(csv_col) {
                row.unit = Some(unit.clone());
            }
            row.unit_system = unit_system.map(str::to_string);
            batch.rows.push(row);
        }
        if batch.rows.len() >= 5_000 {
            total += tsdb.upsert_samples(&batch).await?;
            batch.rows.clear();
        }
    }
    if !batch.rows.is_empty() {
        total += tsdb.upsert_samples(&batch).await?;
    }
    Ok((total, roles_seen))
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
