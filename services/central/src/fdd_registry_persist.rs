//! Persist FDD registry runs to Timescale (`fdd_run`, `fdd_interval_result`,
//! `fdd_incremental_checkpoint`) — single writer, one transaction per run.

use std::collections::{BTreeMap, HashMap};

use anyhow::{anyhow, Context, Result};
use chrono::{DateTime, NaiveDate, Utc};
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

const ELAPSED_MAX_GAP_SECONDS: i64 = 3600;

/// Daily bucket evidence could not be computed from the confirmed-fault series.
pub(crate) const INTERVAL_EVIDENCE_UNKNOWN: &str = "INTERVAL_UNKNOWN";
/// Daily bucket evidence was persisted from the confirmed-fault series.
pub(crate) const INTERVAL_EVIDENCE_EXACT: &str = "INTERVAL_EXACT";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum IntervalPersistReasonCode {
    RegistryLoadFailed,
    RuleNotInRegistry,
    SeriesQueryFailed,
    SeriesEmptyNoSamples,
    SeriesExact,
}

impl IntervalPersistReasonCode {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::RegistryLoadFailed => "registry_load_failed",
            Self::RuleNotInRegistry => "rule_not_in_registry",
            Self::SeriesQueryFailed => "series_query_failed",
            Self::SeriesEmptyNoSamples => "series_empty_no_samples",
            Self::SeriesExact => "series_exact",
        }
    }
}

pub(crate) fn interval_persist_evidence_json(
    status: &str,
    reason_code: IntervalPersistReasonCode,
    reason_detail: Option<&str>,
) -> Value {
    json!({
        "status": status,
        "reason_code": reason_code.as_str(),
        "reason": reason_detail.unwrap_or(""),
    })
}

fn enrich_stored_row_with_interval_evidence(body_row: &mut Value, detail: &Value) {
    let Some(ip) = detail.get("interval_persist") else {
        return;
    };
    let Some(obj) = body_row.as_object_mut() else {
        return;
    };
    if let Some(status) = ip.get("status").and_then(Value::as_str) {
        obj.insert("interval_status".into(), json!(status));
    }
    if let Some(code) = ip.get("reason_code").and_then(Value::as_str) {
        obj.insert("interval_reason_code".into(), json!(code));
    }
}

fn append_hold_to_daily_utc(
    out: &mut BTreeMap<NaiveDate, (f64, f64)>,
    hold_start: DateTime<Utc>,
    hold_seconds: f64,
    confirmed: bool,
    clip: Option<AnalysisWindow>,
) {
    if hold_seconds <= 0.0 || !hold_seconds.is_finite() {
        return;
    }
    let mut remaining = hold_seconds;
    let mut cursor = hold_start;
    while remaining > 0.0 {
        if let Some(window) = clip {
            if cursor >= window.end() {
                break;
            }
            if cursor < window.start() {
                let skip = (window.start() - cursor).num_seconds() as f64;
                if skip >= remaining {
                    break;
                }
                remaining -= skip;
                cursor = window.start();
                continue;
            }
        }
        let day = cursor.date_naive();
        let mut segment_end = day
            .succ_opt()
            .and_then(|next| next.and_hms_opt(0, 0, 0))
            .map(|naive| DateTime::from_naive_utc_and_offset(naive, Utc))
            .filter(|midnight| *midnight > cursor)
            .map(|midnight| {
                let cap = (midnight - cursor).num_seconds() as f64;
                if cap >= remaining {
                    cursor + chrono::Duration::milliseconds((remaining * 1000.0) as i64)
                } else {
                    midnight
                }
            })
            .unwrap_or_else(|| {
                cursor + chrono::Duration::milliseconds((remaining * 1000.0) as i64)
            });
        if let Some(window) = clip {
            if segment_end > window.end() {
                segment_end = window.end();
            }
        }
        let segment_secs = (segment_end - cursor).num_seconds();
        if segment_secs <= 0 {
            break;
        }
        let segment = segment_secs as f64;
        let slot = out.entry(day).or_insert((0.0, 0.0));
        slot.1 += segment;
        if confirmed {
            slot.0 += segment;
        }
        remaining -= segment;
        cursor = segment_end;
    }
}

/// Per-UTC-day fault/covered seconds from a confirmed_fault series (pandas hold semantics).
fn daily_utc_fault_covered_from_confirmed_points(
    points: &[(DateTime<Utc>, bool)],
    clip: Option<AnalysisWindow>,
) -> BTreeMap<NaiveDate, (f64, f64)> {
    let mut sorted = points.to_vec();
    sorted.sort_by_key(|(ts, _)| *ts);
    let mut out: BTreeMap<NaiveDate, (f64, f64)> = BTreeMap::new();
    for i in 0..sorted.len() {
        let (ts, confirmed) = sorted[i];
        if let Some(window) = clip {
            if ts >= window.end() {
                continue;
            }
        }
        let hold = if i + 1 < sorted.len() {
            let delta = (sorted[i + 1].0 - ts).num_seconds();
            if delta > 0 && delta <= ELAPSED_MAX_GAP_SECONDS {
                delta as f64
            } else {
                0.0
            }
        } else {
            0.0
        };
        append_hold_to_daily_utc(&mut out, ts, hold, confirmed, clip);
    }
    out
}

fn interval_buckets_from_daily_utc(
    window: AnalysisWindow,
    daily: BTreeMap<NaiveDate, (f64, f64)>,
    sample_rows: i32,
) -> Result<Vec<BucketResult>, IncrementalError> {
    use chrono_tz::UTC;
    let grid = BucketGrid::LocalDay(UTC);
    let buckets = grid.buckets_overlapping(window.start(), window.end())?;
    if buckets.is_empty() {
        return Ok(Vec::new());
    }
    let per_bucket_samples = (sample_rows / buckets.len().max(1) as i32).max(0);
    let mut out = Vec::with_capacity(buckets.len());
    for bucket in buckets {
        let day = bucket.start().date_naive();
        let (fault, covered) = daily.get(&day).copied().unwrap_or((0.0, 0.0));
        out.push(BucketResult::new(
            bucket,
            fault,
            covered,
            per_bucket_samples as u64,
        )?);
    }
    Ok(out)
}

fn interval_buckets_from_confirmed_fault_map(
    window: AnalysisWindow,
    map: &HashMap<String, bool>,
    sample_rows: i32,
) -> Result<Vec<BucketResult>, IncrementalError> {
    let mut points: Vec<(DateTime<Utc>, bool)> = Vec::with_capacity(map.len());
    for (ts, flag) in map {
        let Ok(parsed) = DateTime::parse_from_rfc3339(ts) else {
            continue;
        };
        points.push((parsed.with_timezone(&Utc), *flag));
    }
    if points.is_empty() {
        return Ok(Vec::new());
    }
    let daily = daily_utc_fault_covered_from_confirmed_points(&points, Some(window));
    interval_buckets_from_daily_utc(window, daily, sample_rows)
}

/// Legacy proportional spreading (4.0.6). Not used for persisted qualification buckets.
#[cfg(test)]
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

#[derive(Debug, Clone, PartialEq)]
pub(crate) enum ExactIntervalPlan {
    Buckets(Vec<BucketResult>),
    SeriesUnavailable {
        reason_code: IntervalPersistReasonCode,
        reason_detail: String,
    },
}

pub(crate) fn exact_interval_plan_from_confirmed_map(
    window: AnalysisWindow,
    map: HashMap<String, bool>,
    sample_rows: i32,
) -> Result<ExactIntervalPlan, IncrementalError> {
    if map.is_empty() {
        return Ok(ExactIntervalPlan::SeriesUnavailable {
            reason_code: IntervalPersistReasonCode::SeriesEmptyNoSamples,
            reason_detail: String::new(),
        });
    }
    let buckets = interval_buckets_from_confirmed_fault_map(window, &map, sample_rows)?;
    Ok(ExactIntervalPlan::Buckets(buckets))
}

async fn exact_interval_plan_for_rule_row(
    tx: &mut Transaction<'_, Postgres>,
    rule_id: &str,
    site_id: &str,
    equipment_id: &str,
    window: AnalysisWindow,
    sample_rows: i32,
    run_ctx: &crate::effective_run_context::EffectiveRunContext,
) -> Result<ExactIntervalPlan, IncrementalError> {
    let reg = match crate::timescale_product::load_reg() {
        Ok(reg) => reg,
        Err(err) => {
            return Ok(ExactIntervalPlan::SeriesUnavailable {
                reason_code: IntervalPersistReasonCode::RegistryLoadFailed,
                reason_detail: err.to_string(),
            });
        }
    };
    let Some(rule) = reg.rules.iter().find(|spec| spec.rule_id == rule_id) else {
        return Ok(ExactIntervalPlan::SeriesUnavailable {
            reason_code: IntervalPersistReasonCode::RuleNotInRegistry,
            reason_detail: rule_id.to_string(),
        });
    };
    let ws = window
        .start()
        .to_rfc3339_opts(chrono::SecondsFormat::Secs, true);
    let we = window
        .end()
        .to_rfc3339_opts(chrono::SecondsFormat::Secs, true);
    match crate::timescale_product::load_live_confirmed_fault_in_tx(
        tx,
        &reg,
        rule,
        site_id,
        equipment_id,
        Some(ws.as_str()),
        Some(we.as_str()),
        run_ctx,
    )
    .await
    {
        Ok(map) => exact_interval_plan_from_confirmed_map(window, map, sample_rows),
        Err(err) => Ok(ExactIntervalPlan::SeriesUnavailable {
            reason_code: IntervalPersistReasonCode::SeriesQueryFailed,
            reason_detail: err.to_string(),
        }),
    }
}

async fn clear_interval_buckets_in_tx(
    tx: &mut Transaction<'_, Postgres>,
    site_id: &str,
    rule_id: &str,
    equipment_id: &str,
    window: AnalysisWindow,
) -> Result<(), sqlx::Error> {
    sqlx::query(
        r#"
        DELETE FROM fdd_interval_result
        WHERE site_id = $1 AND rule_id = $2 AND equipment_id = $3
          AND bucket_start >= $4 AND bucket_start < $5
        "#,
    )
    .bind(site_id)
    .bind(rule_id)
    .bind(equipment_id)
    .bind(window.start())
    .bind(window.end())
    .execute(&mut **tx)
    .await?;
    Ok(())
}

/// Active generation rows whose interval evidence is still unknown for a run id.
pub async fn interval_unknown_pairs_for_run(
    tsdb: &Tsdb,
    site_id: &str,
    run_id: &str,
) -> Result<Vec<(String, String)>> {
    let rows = sqlx::query(
        r#"
        SELECT rule_id, equipment_id
        FROM fdd_run
        WHERE site_id = $1
          AND detail->>'run_id' = $2
          AND equipment_id <> ''
          AND detail->'interval_persist'->>'status' = $3
        "#,
    )
    .bind(site_id)
    .bind(run_id)
    .bind(INTERVAL_EVIDENCE_UNKNOWN)
    .fetch_all(tsdb.pool())
    .await?;
    Ok(rows
        .into_iter()
        .filter_map(|row| {
            let rule_id = row.try_get::<String, _>("rule_id").ok()?;
            let equipment_id = row.try_get::<String, _>("equipment_id").ok()?;
            Some((rule_id, equipment_id))
        })
        .collect())
}

/// Re-attempt interval persist for unknown pairs on an existing run (bounded repair).
pub async fn repair_unknown_interval_evidence_for_run(
    tsdb: &Tsdb,
    site_id: &str,
    run_id: &str,
) -> Result<u32> {
    let pairs = interval_unknown_pairs_for_run(tsdb, site_id, run_id).await?;
    if pairs.is_empty() {
        return Ok(0);
    }
    let mut repaired = 0u32;
    for (rule_id, equipment_id) in pairs {
        let row = sqlx::query(
            r#"
            SELECT window_start, window_end, poll_seconds, confirm_min, sample_count, detail
            FROM fdd_run
            WHERE site_id = $1 AND rule_id = $2 AND equipment_id = $3
              AND detail->>'run_id' = $4
            LIMIT 1
            "#,
        )
        .bind(site_id)
        .bind(&rule_id)
        .bind(&equipment_id)
        .bind(run_id)
        .fetch_optional(tsdb.pool())
        .await?;
        let Some(row) = row else {
            continue;
        };
        let detail: Value = row.try_get("detail")?;
        let body_row = detail.get("row").cloned().unwrap_or(Value::Null);
        let poll: f64 = row.try_get("poll_seconds")?;
        let run_ctx =
            crate::effective_run_context::EffectiveRunContext::from_run_row(&body_row, poll as f64);
        let window =
            AnalysisWindow::half_open(row.try_get("window_start")?, row.try_get("window_end")?)
                .map_err(|e| anyhow!("repair window: {e}"))?;
        let sample_rows = row.try_get::<Option<i32>, _>("sample_count")?.unwrap_or(0);
        let mut tx = tsdb.pool().begin().await?;
        let plan = exact_interval_plan_for_rule_row(
            &mut tx,
            &rule_id,
            site_id,
            &equipment_id,
            window,
            sample_rows,
            &run_ctx,
        )
        .await?;
        match plan {
            ExactIntervalPlan::Buckets(buckets) if !buckets.is_empty() => {
                let through_revision =
                    fdd_tsdb::current_data_revision(tsdb.pool(), site_id).await?;
                let model_revision = model_revision_for_site(tsdb, site_id).await?;
                let confirm = run_ctx.confirm_seconds as f64;
                let rule_params = RuleParameters::try_from_pairs([
                    ("confirm_min", confirm.to_string()),
                    ("poll_seconds", run_ctx.poll_seconds.to_string()),
                ])
                .map_err(|e| anyhow!("repair params: {e}"))?;
                let pack_ver = detail
                    .get("generation")
                    .and_then(|g| g.get("pack_version"))
                    .and_then(Value::as_str)
                    .unwrap_or("unknown");
                let identity = FddResultIdentity::new(
                    through_revision,
                    &model_revision,
                    rule_params,
                    pack_ver,
                    window,
                    QualityPolicy::DropBad,
                    SchedulePolicy::Sched1,
                );
                use chrono_tz::UTC;
                let horizon = RuleHorizon::new(
                    chrono::Duration::zero(),
                    chrono::Duration::seconds(confirm.round().max(0.0) as i64),
                )?;
                let grid = BucketGrid::LocalDay(UTC);
                let scope =
                    ResultScope::new(site_id, &rule_id, &equipment_id, &identity, grid, horizon)?;
                replace_scope_results_in_tx(&mut tx, &scope, window, through_revision, &buckets)
                    .await?;
                let mut detail_mut = detail.clone();
                if let Some(obj) = detail_mut.as_object_mut() {
                    obj.insert(
                        "interval_persist".into(),
                        interval_persist_evidence_json(
                            INTERVAL_EVIDENCE_EXACT,
                            IntervalPersistReasonCode::SeriesExact,
                            None,
                        ),
                    );
                }
                sqlx::query(
                    r#"
                    UPDATE fdd_run SET detail = $5
                    WHERE site_id = $1 AND rule_id = $2 AND equipment_id = $3
                      AND detail->>'run_id' = $4
                    "#,
                )
                .bind(site_id)
                .bind(&rule_id)
                .bind(&equipment_id)
                .bind(run_id)
                .bind(&detail_mut)
                .execute(&mut *tx)
                .await?;
                tx.commit().await?;
                repaired += 1;
            }
            _ => {
                let _ = tx.rollback().await;
            }
        }
    }
    Ok(repaired)
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
                if let Some(eq) = equipment_id {
                    let run_ctx = crate::effective_run_context::EffectiveRunContext::from_run_row(
                        row,
                        poll as f64,
                    );
                    let mut interval_persist: Option<Value> = None;
                    let mut interval_buckets: Option<Vec<BucketResult>> = None;
                    if item.outcome == RuleOutcome::Succeeded
                        && row.get("output_kind").and_then(Value::as_str) != Some("metric")
                        && fault_hours.is_some()
                    {
                        match exact_interval_plan_for_rule_row(
                            &mut tx,
                            &item.rule_id,
                            site_id,
                            eq,
                            window,
                            sample_rows,
                            &run_ctx,
                        )
                        .await
                        {
                            Ok(ExactIntervalPlan::Buckets(buckets)) => {
                                interval_persist = Some(interval_persist_evidence_json(
                                    INTERVAL_EVIDENCE_EXACT,
                                    IntervalPersistReasonCode::SeriesExact,
                                    None,
                                ));
                                interval_buckets = Some(buckets);
                            }
                            Ok(ExactIntervalPlan::SeriesUnavailable {
                                reason_code,
                                reason_detail,
                            }) => {
                                interval_persist = Some(interval_persist_evidence_json(
                                    INTERVAL_EVIDENCE_UNKNOWN,
                                    reason_code,
                                    Some(reason_detail.as_str()),
                                ));
                                clear_interval_buckets_in_tx(
                                    &mut tx,
                                    site_id,
                                    &item.rule_id,
                                    eq,
                                    window,
                                )
                                .await?;
                            }
                            Err(err) => {
                                return Err(anyhow!("interval buckets: {err}"));
                            }
                        }
                    }
                    let detail = json!({
                        "generation": prep.manifest,
                        "run_id": prep.run_id,
                        "dirty_reason": prep.dirty_reason,
                        "row": row,
                        "interval_persist": interval_persist,
                    });
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

                    if let Some(buckets) = interval_buckets {
                        use chrono_tz::UTC;
                        let horizon = RuleHorizon::new(
                            chrono::Duration::zero(),
                            chrono::Duration::seconds(confirm.round().max(0.0) as i64),
                        )?;
                        let grid = BucketGrid::LocalDay(UTC);
                        let scope =
                            ResultScope::new(site_id, &item.rule_id, eq, &identity, grid, horizon)?;
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
                } else {
                    let detail = json!({
                        "generation": prep.manifest,
                        "run_id": prep.run_id,
                        "dirty_reason": prep.dirty_reason,
                        "row": row,
                    });
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
        SELECT generation
        FROM (
            SELECT detail->'generation' AS generation, MAX(created_at) AS latest
            FROM fdd_run
            WHERE site_id = $1 AND detail->'generation' IS NOT NULL
            GROUP BY detail->>'run_id', detail->'generation'
        ) runs
        ORDER BY latest DESC
        LIMIT 1
        "#,
    )
    .bind(building_id)
    .fetch_optional(tsdb.pool())
    .await?;
    let Some(row) = row else {
        return Ok(None);
    };
    Ok(row.try_get("generation")?)
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
        WHERE site_id = $1 AND detail->>'run_id' = $2
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
        let mut body_row = detail.get("row").cloned().unwrap_or(Value::Null);
        enrich_stored_row_with_interval_evidence(&mut body_row, &detail);
        out.push((rule_id, body_row));
    }
    Ok(out)
}

/// Latest run context for plot/series for one rule × equipment on the active generation.
pub async fn effective_run_context_for_active_row(
    tsdb: &Tsdb,
    site_id: &str,
    rule_id: &str,
    equipment_id: &str,
) -> Result<Option<crate::effective_run_context::EffectiveRunContext>> {
    let manifest = active_generation_manifest(tsdb, site_id).await?;
    let Some(manifest) = manifest else {
        return Ok(None);
    };
    let run_id = manifest.get("run_id").and_then(Value::as_str).unwrap_or("");
    if run_id.is_empty() {
        return Ok(None);
    }
    let row = sqlx::query(
        r#"
        SELECT poll_seconds, detail
        FROM fdd_run
        WHERE site_id = $1 AND rule_id = $2 AND equipment_id = $3
          AND detail->>'run_id' = $4
        LIMIT 1
        "#,
    )
    .bind(site_id)
    .bind(rule_id)
    .bind(equipment_id)
    .bind(run_id)
    .fetch_optional(tsdb.pool())
    .await?;
    let Some(row) = row else {
        return Ok(None);
    };
    let detail: Value = row.try_get("detail")?;
    let body_row = detail.get("row").cloned().unwrap_or(Value::Null);
    let poll: i32 = row.try_get("poll_seconds")?;
    Ok(Some(
        crate::effective_run_context::EffectiveRunContext::from_run_row(&body_row, f64::from(poll)),
    ))
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
mod interval_daily_unit_tests {
    use super::*;
    use chrono::{TimeZone, Utc};

    fn ts(s: &str) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339(s)
            .expect("ts")
            .with_timezone(&Utc)
    }

    #[test]
    fn daily_series_fault_only_on_one_day_not_equal_across_five() {
        let start = Utc.with_ymd_and_hms(2026, 10, 10, 0, 0, 0).unwrap();
        let mut points: Vec<(DateTime<Utc>, bool)> = Vec::new();
        for day in 0..5 {
            let base = start + chrono::Duration::days(day);
            for step in 0..12 {
                let ts = base + chrono::Duration::seconds(step * 300);
                let confirmed = day == 0 && step >= 2;
                points.push((ts, confirmed));
            }
        }
        let daily = daily_utc_fault_covered_from_confirmed_points(&points, None);
        let fault_day0 = daily
            .get(&NaiveDate::from_ymd_opt(2026, 10, 10).unwrap())
            .map(|(f, _)| *f)
            .unwrap_or(0.0);
        let fault_day1 = daily
            .get(&NaiveDate::from_ymd_opt(2026, 10, 11).unwrap())
            .map(|(f, _)| *f)
            .unwrap_or(0.0);
        assert!(fault_day0 > 0.0, "day 0 should have fault seconds");
        assert_eq!(fault_day1, 0.0, "day 1 should have no fault seconds");
    }

    #[test]
    fn up03_two_day_window_fault_only_on_day_two() {
        let start = ts("2026-10-10T00:00:00Z");
        let end = ts("2026-10-12T00:00:00Z");
        let window = AnalysisWindow::half_open(start, end).expect("window");
        let mut points = Vec::new();
        let day2 = ts("2026-10-11T00:00:00Z");
        points.push((day2, false));
        points.push((day2 + chrono::Duration::minutes(5), true));
        points.push((day2 + chrono::Duration::minutes(10), true));
        points.push((day2 + chrono::Duration::minutes(15), false));
        let buckets =
            interval_buckets_from_confirmed_fault_map(window, &map_from_points(&points), 4)
                .expect("buckets");
        let day1 = NaiveDate::from_ymd_opt(2026, 10, 10).unwrap();
        let day2d = NaiveDate::from_ymd_opt(2026, 10, 11).unwrap();
        let fault_day1 = bucket_fault_for_day(&buckets, day1);
        let fault_day2 = bucket_fault_for_day(&buckets, day2d);
        assert_eq!(fault_day1, 0.0);
        assert!((fault_day2 - 600.0).abs() < 0.01, "fault_day2={fault_day2}");
    }

    #[test]
    fn up03_midnight_hold_splits_five_min_each_day() {
        let t0 = ts("2026-10-10T23:55:00Z");
        let t1 = ts("2026-10-11T00:05:00Z");
        let points = vec![(t0, true), (t1, true)];
        let daily = daily_utc_fault_covered_from_confirmed_points(&points, None);
        let d0 = NaiveDate::from_ymd_opt(2026, 10, 10).unwrap();
        let d1 = NaiveDate::from_ymd_opt(2026, 10, 11).unwrap();
        let (_, cov0) = daily.get(&d0).copied().unwrap_or((0.0, 0.0));
        let (_, cov1) = daily.get(&d1).copied().unwrap_or((0.0, 0.0));
        assert!((cov0 - 300.0).abs() < 0.01, "cov0={cov0}");
        assert!((cov1 - 300.0).abs() < 0.01, "cov1={cov1}");
    }

    #[test]
    fn up03_max_gap_boundary() {
        let t0 = ts("2026-10-10T12:00:00Z");
        let below = t0 + chrono::Duration::seconds(ELAPSED_MAX_GAP_SECONDS);
        let above = t0 + chrono::Duration::seconds(ELAPSED_MAX_GAP_SECONDS + 1);
        let daily_below =
            daily_utc_fault_covered_from_confirmed_points(&[(t0, true), (below, false)], None);
        let daily_above =
            daily_utc_fault_covered_from_confirmed_points(&[(t0, true), (above, false)], None);
        let day = t0.date_naive();
        let (_, cov_below) = daily_below.get(&day).copied().unwrap_or((0.0, 0.0));
        let (_, cov_above) = daily_above.get(&day).copied().unwrap_or((0.0, 0.0));
        assert!((cov_below - ELAPSED_MAX_GAP_SECONDS as f64).abs() < 0.01);
        assert_eq!(cov_above, 0.0);
    }

    #[test]
    fn up03_clipped_window_trims_hold() {
        let t0 = ts("2026-10-10T10:00:00Z");
        let t1 = ts("2026-10-10T11:00:00Z");
        let window =
            AnalysisWindow::half_open(ts("2026-10-10T10:30:00Z"), ts("2026-10-10T11:00:00Z"))
                .expect("window");
        let daily =
            daily_utc_fault_covered_from_confirmed_points(&[(t0, true), (t1, false)], Some(window));
        let day = t0.date_naive();
        let (_, covered) = daily.get(&day).copied().unwrap_or((0.0, 0.0));
        assert!((covered - 1800.0).abs() < 0.01, "covered={covered}");
    }

    #[test]
    fn up03_empty_map_is_series_unavailable() {
        let window =
            AnalysisWindow::half_open(ts("2026-10-10T00:00:00Z"), ts("2026-10-11T00:00:00Z"))
                .expect("window");
        let plan = exact_interval_plan_from_confirmed_map(window, HashMap::new(), 0).expect("plan");
        assert_eq!(
            plan,
            ExactIntervalPlan::SeriesUnavailable {
                reason_code: IntervalPersistReasonCode::SeriesEmptyNoSamples,
                reason_detail: String::new(),
            }
        );
    }

    fn map_from_points(points: &[(DateTime<Utc>, bool)]) -> HashMap<String, bool> {
        points
            .iter()
            .map(|(ts, flag)| (ts.to_rfc3339_opts(chrono::SecondsFormat::Secs, true), *flag))
            .collect()
    }

    fn bucket_fault_for_day(buckets: &[BucketResult], day: NaiveDate) -> f64 {
        buckets
            .iter()
            .filter(|b| b.bucket().start().date_naive() == day)
            .map(BucketResult::fault_seconds)
            .sum()
    }

    #[test]
    fn distribute_interval_buckets_spreads_evenly_across_days() {
        let start = Utc.with_ymd_and_hms(2026, 10, 10, 0, 0, 0).unwrap();
        let end = Utc.with_ymd_and_hms(2026, 10, 15, 0, 0, 0).unwrap();
        let window = AnalysisWindow::half_open(start, end).expect("window");
        let grid = BucketGrid::UtcHour;
        let buckets =
            distribute_interval_buckets(grid, window, 6.8, Some(6.8), 100).expect("buckets");
        use chrono_tz::UTC;
        let day_grid = BucketGrid::LocalDay(UTC);
        let day_buckets = day_grid
            .buckets_overlapping(window.start(), window.end())
            .expect("days");
        let summed: BTreeMap<NaiveDate, f64> =
            buckets.iter().fold(BTreeMap::new(), |mut acc, b| {
                let day = b.bucket().start().date_naive();
                *acc.entry(day).or_insert(0.0) += b.fault_seconds();
                acc
            });
        let values: Vec<f64> = day_buckets
            .iter()
            .map(|db| summed.get(&db.start().date_naive()).copied().unwrap_or(0.0))
            .collect();
        if values.len() >= 2 {
            assert!(
                (values[0] - values[1]).abs() < 1.0,
                "legacy distribute spreads evenly: {values:?}"
            );
        }
    }
}

#[cfg(test)]
#[path = "fdd_registry_persist_test.rs"]
mod fdd_registry_persist_test;
