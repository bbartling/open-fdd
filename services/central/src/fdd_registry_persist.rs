//! Persist FDD registry runs to Timescale (`fdd_run`, `fdd_interval_result`,
//! `fdd_incremental_checkpoint`) — single writer, one transaction per run.

use std::collections::BTreeMap;

use anyhow::{anyhow, Context, Result};
use chrono::{DateTime, Utc};
use fdd_tsdb::{
    ensure_incremental_schema, replace_scope_results_in_tx, AnalysisWindow, BucketGrid,
    BucketResult, FddResultIdentity, IncrementalError, QualityPolicy, ResultScope, RuleHorizon,
    RuleParameters, SchedulePolicy, Tsdb,
};
use open_fdd_edge_prototype::fdd::registry_api::{
    prepare_run_generation_with_parent, RuleOutcome, RunGenerationCommit, RunGenerationPrepared,
};
use serde_json::{json, Value};
use sqlx::{Postgres, Row, Transaction};

fn parse_window(start: Option<&str>, end: Option<&str>) -> Result<AnalysisWindow> {
    let start = start
        .filter(|s| !s.is_empty())
        .context("window start required for Timescale FDD persist")?;
    let end = end
        .filter(|s| !s.is_empty())
        .context("window end required for Timescale FDD persist")?;
    let start = DateTime::parse_from_rfc3339(start)
        .map_err(|e| anyhow!("window start: {e}"))?
        .with_timezone(&Utc);
    let end = DateTime::parse_from_rfc3339(end)
        .map_err(|e| anyhow!("window end: {e}"))?
        .with_timezone(&Utc);
    AnalysisWindow::half_open(start, end).map_err(|e| anyhow!("window: {e}"))
}

fn pack_version(pack: &Value) -> String {
    pack.get("pack_version")
        .or_else(|| pack.get("version"))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or("unknown")
        .to_string()
}

fn row_f64(row: &Value, key: &str) -> Option<f64> {
    row.get(key)
        .and_then(Value::as_f64)
        .filter(|v| v.is_finite())
}

fn distribute_interval_buckets(
    grid: BucketGrid,
    window: AnalysisWindow,
    fault_hours: f64,
    covered_hours: Option<f64>,
    sample_rows: i32,
) -> Result<Vec<BucketResult>, IncrementalError> {
    let buckets = grid.buckets_overlapping(window.start(), window.end())?;
    if buckets.is_empty() {
        return Ok(Vec::new());
    }
    let window_secs = (window.end() - window.start()).num_seconds().max(1) as f64;
    let total_fault = if fault_hours.is_finite() && fault_hours >= 0.0 {
        fault_hours * 3600.0
    } else {
        0.0
    };
    let total_covered = covered_hours
        .filter(|h| h.is_finite() && *h > 0.0)
        .map(|h| h * 3600.0)
        .unwrap_or(window_secs);
    let per_bucket_samples = (sample_rows / buckets.len().max(1) as i32).max(0);
    let mut out = Vec::with_capacity(buckets.len());
    for bucket in buckets {
        let bucket_secs = (bucket.end() - bucket.start()).num_seconds().max(0) as f64;
        let covered = total_covered * (bucket_secs / window_secs);
        let fault = if total_covered > 0.0 {
            total_fault * (covered / total_covered)
        } else {
            0.0
        };
        out.push(BucketResult::new(
            bucket,
            fault,
            covered,
            per_bucket_samples as u64,
        )?);
    }
    Ok(out)
}

async fn model_revision_for_site(tsdb: &Tsdb, site_id: &str) -> Result<String> {
    crate::timescale_product::read_model_revision_string(tsdb, site_id)
        .await
        .map_err(|e| anyhow!(e))
}

/// Write one registry generation to Timescale. Replaces manifest JSON as the results store.
pub async fn persist_registry_run_timescale(
    tsdb: &Tsdb,
    commit: &RunGenerationCommit,
    prep: &RunGenerationPrepared,
) -> Result<()> {
    fdd_tsdb::ensure_revision_schema(tsdb.pool())
        .await
        .map_err(|e| anyhow!("revision schema: {e}"))?;
    ensure_incremental_schema(tsdb.pool())
        .await
        .map_err(|e| anyhow!("incremental schema: {e}"))?;
    let site_id = commit.building_id.trim();
    let window = parse_window(commit.window_start.as_deref(), commit.window_end.as_deref())?;
    let config_hash = prep
        .manifest
        .get("config_hash")
        .and_then(Value::as_str)
        .unwrap_or("");
    let through_revision = fdd_tsdb::current_data_revision(tsdb.pool(), site_id).await?;
    let model_revision = model_revision_for_site(tsdb, site_id).await?;
    let pack_ver = pack_version(&commit.pack);
    let poll = commit.poll_seconds.round().max(1.0) as i32;

    let mut tx = tsdb.pool().begin().await?;
    if commit.full_cohort {
        sqlx::query("DELETE FROM fdd_run WHERE site_id = $1")
            .bind(site_id)
            .execute(&mut *tx)
            .await?;
        sqlx::query("DELETE FROM fdd_interval_result WHERE site_id = $1")
            .bind(site_id)
            .execute(&mut *tx)
            .await?;
        sqlx::query("DELETE FROM fdd_incremental_checkpoint WHERE site_id = $1")
            .bind(site_id)
            .execute(&mut *tx)
            .await?;
    } else if let Some(parent) = prep.parent_run_id.as_deref() {
        let touched: Vec<String> = prep
            .prepared
            .iter()
            .map(|item| item.rule_id.clone())
            .collect();
        sqlx::query("DELETE FROM fdd_run WHERE site_id = $1 AND rule_id = ANY($2)")
            .bind(site_id)
            .bind(&touched)
            .execute(&mut *tx)
            .await?;
        copy_parent_runs(
            &mut tx,
            site_id,
            parent,
            &prep.run_id,
            &touched,
            &prep.manifest,
        )
        .await?;
    }

    for item in &prep.prepared {
        if let Some(rows) = item.body.get("rows").and_then(Value::as_array) {
            for row in rows {
                let equipment_id = row
                    .get("equipment_id")
                    .and_then(Value::as_str)
                    .map(str::trim)
                    .filter(|s| !s.is_empty());
                let confirm = row
                    .get("confirm_seconds")
                    .and_then(Value::as_f64)
                    .unwrap_or(0.0);
                let rule_params = RuleParameters::try_from_pairs([
                    ("confirm_min", confirm.to_string()),
                    ("poll_seconds", poll.to_string()),
                ])
                .map_err(|e| anyhow!("rule params: {e}"))?;
                let identity = FddResultIdentity::new(
                    through_revision,
                    &model_revision,
                    rule_params,
                    &pack_ver,
                    window,
                    QualityPolicy::DropBad,
                    SchedulePolicy::Sched1,
                );
                let status = row
                    .get("status")
                    .and_then(Value::as_str)
                    .unwrap_or("UNKNOWN");
                let fault_hours = row_f64(row, "fault_hours");
                let sample_rows =
                    row.get("sample_rows").and_then(Value::as_i64).unwrap_or(0) as i32;
                let detail = json!({
                    "generation": prep.manifest,
                    "run_id": prep.run_id,
                    "dirty_reason": prep.dirty_reason,
                    "row": row,
                });
                if let Some(eq) = equipment_id {
                    let fault_seconds = fault_hours.map(|h| (h * 3600.0).round() as i32);
                    sqlx::query(
                        r#"
                        INSERT INTO fdd_run(
                          site_id, equipment_id, rule_id, window_start, window_end,
                          poll_seconds, confirm_min, config_hash, status, fault_seconds,
                          fault_hours, sample_count, detail
                        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                        "#,
                    )
                    .bind(site_id)
                    .bind(eq)
                    .bind(&item.rule_id)
                    .bind(window.start())
                    .bind(window.end())
                    .bind(poll)
                    .bind(confirm)
                    .bind(config_hash)
                    .bind(status)
                    .bind(fault_seconds)
                    .bind(fault_hours)
                    .bind(sample_rows)
                    .bind(&detail)
                    .execute(&mut *tx)
                    .await?;

                    if item.outcome == RuleOutcome::Succeeded
                        && row.get("output_kind").and_then(Value::as_str) != Some("metric")
                        && fault_hours.is_some()
                    {
                        let grid = BucketGrid::UtcHour;
                        let horizon = RuleHorizon::new(
                            chrono::Duration::zero(),
                            chrono::Duration::seconds(confirm.round().max(0.0) as i64),
                        )?;
                        let scope =
                            ResultScope::new(site_id, &item.rule_id, eq, &identity, grid, horizon)?;
                        let covered = row_f64(row, "covered_hours");
                        let buckets = distribute_interval_buckets(
                            grid,
                            window,
                            fault_hours.unwrap_or(0.0),
                            covered,
                            sample_rows,
                        )?;
                        if !buckets.is_empty() {
                            replace_scope_results_in_tx(
                                &mut tx,
                                &scope,
                                window,
                                through_revision,
                                &buckets,
                            )
                            .await?;
                        }
                    }
                } else if item.outcome != RuleOutcome::Skipped {
                    sqlx::query(
                        r#"
                        INSERT INTO fdd_run(
                          site_id, equipment_id, rule_id, window_start, window_end,
                          poll_seconds, confirm_min, config_hash, status, fault_seconds,
                          fault_hours, sample_count, detail
                        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                        "#,
                    )
                    .bind(site_id)
                    .bind("")
                    .bind(&item.rule_id)
                    .bind(window.start())
                    .bind(window.end())
                    .bind(poll)
                    .bind(confirm)
                    .bind(config_hash)
                    .bind(status)
                    .bind(Option::<i32>::None)
                    .bind(Option::<f64>::None)
                    .bind(0_i32)
                    .bind(&detail)
                    .execute(&mut *tx)
                    .await?;
                }
            }
        }
    }
    tx.commit().await?;
    Ok(())
}

async fn copy_parent_runs(
    tx: &mut Transaction<'_, Postgres>,
    site_id: &str,
    parent_run_id: &str,
    new_run_id: &str,
    touched_rules: &[String],
    manifest: &Value,
) -> Result<()> {
    let rows = sqlx::query(
        r#"
        SELECT equipment_id, rule_id, window_start, window_end, poll_seconds, confirm_min,
               config_hash, status, fault_seconds, fault_hours, sample_count, detail
        FROM fdd_run
        WHERE site_id = $1 AND detail->>'run_id' = $2 AND NOT (rule_id = ANY($3))
        "#,
    )
    .bind(site_id)
    .bind(parent_run_id)
    .bind(touched_rules)
    .fetch_all(&mut **tx)
    .await?;
    for row in rows {
        let mut detail: Value = row.try_get("detail")?;
        if let Some(obj) = detail.as_object_mut() {
            obj.insert("run_id".into(), json!(new_run_id));
            if let Some(gen) = obj.get_mut("generation") {
                if let Some(g) = gen.as_object_mut() {
                    g.insert("run_id".into(), json!(new_run_id));
                    g.insert("parent_run_id".into(), json!(parent_run_id));
                    if let Some(src) = manifest.as_object() {
                        for (k, v) in src {
                            if k != "run_id" && k != "parent_run_id" {
                                g.insert(k.clone(), v.clone());
                            }
                        }
                    }
                }
            }
        }
        sqlx::query(
            r#"
            INSERT INTO fdd_run(
              site_id, equipment_id, rule_id, window_start, window_end,
              poll_seconds, confirm_min, config_hash, status, fault_seconds,
              fault_hours, sample_count, detail
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            "#,
        )
        .bind(site_id)
        .bind(row.try_get::<String, _>("equipment_id")?)
        .bind(row.try_get::<String, _>("rule_id")?)
        .bind(row.try_get::<DateTime<Utc>, _>("window_start")?)
        .bind(row.try_get::<DateTime<Utc>, _>("window_end")?)
        .bind(row.try_get::<i32, _>("poll_seconds")?)
        .bind(row.try_get::<f64, _>("confirm_min")?)
        .bind(row.try_get::<String, _>("config_hash")?)
        .bind(row.try_get::<String, _>("status")?)
        .bind(row.try_get::<Option<i32>, _>("fault_seconds")?)
        .bind(row.try_get::<Option<f64>, _>("fault_hours")?)
        .bind(row.try_get::<Option<i32>, _>("sample_count")?)
        .bind(&detail)
        .execute(&mut **tx)
        .await?;
    }
    Ok(())
}

/// Latest active run manifest for a site, if any rows exist.
pub async fn active_generation_manifest(tsdb: &Tsdb, building_id: &str) -> Result<Option<Value>> {
    let row = sqlx::query(
        r#"
        SELECT detail
        FROM fdd_run
        WHERE site_id = $1
        ORDER BY created_at DESC
        LIMIT 1
        "#,
    )
    .bind(building_id)
    .fetch_optional(tsdb.pool())
    .await?;
    let Some(row) = row else {
        return Ok(None);
    };
    let detail: Value = row.try_get("detail")?;
    Ok(detail.get("generation").cloned())
}

/// Build flat rule rows for the active Timescale generation (rule_id, row body).
pub async fn active_generation_rows(
    tsdb: &Tsdb,
    building_id: &str,
) -> Result<Vec<(String, Value)>> {
    let manifest = active_generation_manifest(tsdb, building_id).await?;
    let Some(manifest) = manifest else {
        return Ok(Vec::new());
    };
    let run_id = manifest.get("run_id").and_then(Value::as_str).unwrap_or("");
    if run_id.is_empty() {
        return Ok(Vec::new());
    }
    let rows = sqlx::query(
        r#"
        SELECT rule_id, detail
        FROM fdd_run
        WHERE site_id = $1 AND detail->>'run_id' = $2 AND equipment_id <> ''
        ORDER BY rule_id, equipment_id
        "#,
    )
    .bind(building_id)
    .bind(run_id)
    .fetch_all(tsdb.pool())
    .await?;
    let mut out = Vec::new();
    for row in rows {
        let rule_id = row.try_get::<String, _>("rule_id")?;
        let detail: Value = row.try_get("detail")?;
        let body_row = detail.get("row").cloned().unwrap_or(Value::Null);
        out.push((rule_id, body_row));
    }
    Ok(out)
}

pub async fn commit_and_persist_registry_run(
    tsdb: &Tsdb,
    commit: RunGenerationCommit,
) -> Result<Value> {
    let parent_manifest = if commit.full_cohort {
        None
    } else {
        active_generation_manifest(tsdb, commit.building_id.trim()).await?
    };
    let parent_rows = if parent_manifest.is_some() {
        active_generation_rows(tsdb, commit.building_id.trim()).await?
    } else {
        Vec::new()
    };
    let mut prep =
        prepare_run_generation_with_parent(&commit, parent_manifest.as_ref(), &parent_rows)
            .map_err(anyhow::Error::msg)?;
    if let Some(reason) = &prep.dirty_reason {
        if let Some(obj) = prep.manifest.as_object_mut() {
            obj.insert("dirty_reason".into(), json!(reason));
        }
    }
    persist_registry_run_timescale(tsdb, &commit, &prep).await?;
    let stored_rows = active_generation_rows(tsdb, commit.building_id.trim()).await?;
    let merged_results = stored_rows
        .into_iter()
        .map(|(rule_id, row)| {
            let mut cloned = row;
            if let Some(obj) = cloned.as_object_mut() {
                obj.entry("rule_id").or_insert(json!(rule_id));
            }
            cloned
        })
        .collect::<Vec<_>>();
    let result_count = merged_results.len();
    let mut summary = prep.manifest;
    if let Some(obj) = summary.as_object_mut() {
        obj.insert("results".into(), Value::Array(merged_results));
        obj.insert("building_id".into(), json!(commit.building_id));
        obj.insert("result_count".into(), json!(result_count));
    }
    Ok(summary)
}

pub async fn results_from_timescale(
    tsdb: &Tsdb,
    building_id: Option<&str>,
    stamped_types: &BTreeMap<String, String>,
) -> Result<Value> {
    let bid = building_id.filter(|s| !s.is_empty()).unwrap_or("");
    if bid.is_empty() {
        return Ok(json!({
            "ok": true,
            "count": 0,
            "results": [],
            "run_id": Value::Null,
            "run_status": Value::Null,
            "parent_run_id": Value::Null,
            "legacy_withheld": false,
            "source": "timescale",
        }));
    }
    let manifest = active_generation_manifest(tsdb, bid).await?;
    let Some(manifest) = manifest else {
        return Ok(json!({
            "ok": true,
            "count": 0,
            "results": [],
            "run_id": Value::Null,
            "run_status": Value::Null,
            "legacy_withheld": loose_legacy_count(bid) > 0,
            "source": "timescale",
        }));
    };
    let rule_rows = active_generation_rows(tsdb, bid).await?;
    let body = open_fdd_edge_prototype::fdd::registry_api::results_response_with_timescale_rows(
        Some(bid),
        stamped_types,
        "timescale_equipment",
        &manifest,
        &rule_rows,
    );
    Ok(body)
}

pub async fn readiness_from_timescale(tsdb: &Tsdb, building_id: Option<&str>) -> Result<Value> {
    let bid = building_id.filter(|s| !s.is_empty());
    let legacy = bid.map(loose_legacy_count).unwrap_or(0);
    let manifest = match bid {
        Some(id) => active_generation_manifest(tsdb, id).await?,
        None => None,
    };
    let stored_count = match bid {
        Some(id) => active_generation_rows(tsdb, id).await?.len(),
        None => 0,
    };
    let body = open_fdd_edge_prototype::fdd::registry_api::readiness_from_timescale_manifest(
        bid,
        legacy,
        manifest.as_ref(),
        stored_count,
    );
    Ok(body)
}

fn loose_legacy_count(building_id: &str) -> usize {
    open_fdd_edge_prototype::fdd::registry_api::loose_rule_file_count_for_building(building_id)
}

#[cfg(test)]
#[path = "fdd_registry_persist_test.rs"]
mod fdd_registry_persist_test;
