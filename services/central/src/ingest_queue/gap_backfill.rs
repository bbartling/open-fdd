//! Gap-only backfill job construction from Timescale stored hours.

use chrono::{DateTime, Utc};
use sqlx::PgPool;

use crate::providers::committed_model::IngestDeviceGroup;

use super::binding_state::{
    ensure_binding_row, last_stored_ts_for_device, stored_hour_starts_for_device,
};
use super::gap_planner::{default_max_span, plan_gap_windows, GapPlanInput, GapPlanResult};
use super::model::{NewJob, QueueError};

pub fn point_keys_for_group(group: &IngestDeviceGroup) -> Vec<String> {
    group
        .points
        .iter()
        .map(|point| point.semantic_point_id.clone())
        .collect()
}

#[expect(
    clippy::too_many_arguments,
    reason = "gap backfill planner passes through tenant, site, device, and UTC range anchors"
)]
pub async fn plan_device_gap_backfill(
    pool: &PgPool,
    tenant_id: &str,
    site_id: &str,
    group: &IngestDeviceGroup,
    model_revision: &str,
    range_start: DateTime<Utc>,
    range_end: DateTime<Utc>,
    force: bool,
    now: DateTime<Utc>,
) -> Result<(GapPlanResult, Vec<NewJob>), QueueError> {
    let keys = point_keys_for_group(group);
    let binding = ensure_binding_row(
        pool,
        tenant_id,
        site_id,
        &group.provider_instance_id,
        &group.equipment_id,
        model_revision,
        now,
    )
    .await?;
    let stored =
        stored_hour_starts_for_device(pool, site_id, &keys, range_start, range_end).await?;
    let last_stored = last_stored_ts_for_device(pool, site_id, &keys).await?;
    let plan = plan_gap_windows(GapPlanInput {
        requested_start: range_start,
        requested_end: range_end,
        provider_data_start: binding.provider_data_start,
        binding_created_at: binding.binding_created_at,
        stored_hour_starts: &stored,
        last_stored_ts: last_stored,
        force,
        max_span: default_max_span(),
    })
    .map_err(QueueError::Invalid)?;
    let mut jobs = Vec::new();
    for span in &plan.planned {
        jobs.push(NewJob {
            tenant_id: tenant_id.to_string(),
            canonical_site: site_id.to_string(),
            provider_instance_id: group.provider_instance_id.clone(),
            device_id: group.equipment_id.clone(),
            model_revision: model_revision.to_string(),
            logical_window_start: span.start,
            logical_window_end: span.end,
            shard: String::new(),
            not_before: now,
            estimated_cost: 1,
            requested_points_digest: None,
        });
    }
    Ok((plan, jobs))
}

#[expect(
    clippy::too_many_arguments,
    reason = "explicit window backfill keeps point keys and window list separate for HTTP bodies"
)]
pub async fn plan_explicit_windows(
    pool: &PgPool,
    tenant_id: &str,
    site_id: &str,
    provider_id: &str,
    device_id: &str,
    model_revision: &str,
    point_keys: &[String],
    windows: &[(DateTime<Utc>, DateTime<Utc>)],
    force: bool,
    now: DateTime<Utc>,
) -> Result<(GapPlanResult, Vec<NewJob>), QueueError> {
    if windows.is_empty() {
        return Err(QueueError::Invalid("backfill windows are empty".into()));
    }
    let range_start = windows[0].0;
    let range_end = windows.last().map(|(_, end)| *end).unwrap_or(range_start);
    let binding = ensure_binding_row(
        pool,
        tenant_id,
        site_id,
        provider_id,
        device_id,
        model_revision,
        now,
    )
    .await?;
    let stored =
        stored_hour_starts_for_device(pool, site_id, point_keys, range_start, range_end).await?;
    let last_stored = last_stored_ts_for_device(pool, site_id, point_keys).await?;
    let plan = plan_gap_windows(GapPlanInput {
        requested_start: range_start,
        requested_end: range_end,
        provider_data_start: binding.provider_data_start,
        binding_created_at: binding.binding_created_at,
        stored_hour_starts: &stored,
        last_stored_ts: last_stored,
        force,
        max_span: default_max_span(),
    })
    .map_err(QueueError::Invalid)?;
    let mut jobs = Vec::new();
    for span in &plan.planned {
        let overlaps = windows
            .iter()
            .any(|(start, end)| span.start < *end && span.end > *start);
        if overlaps {
            jobs.push(NewJob {
                tenant_id: tenant_id.to_string(),
                canonical_site: site_id.to_string(),
                provider_instance_id: provider_id.to_string(),
                device_id: device_id.to_string(),
                model_revision: model_revision.to_string(),
                logical_window_start: span.start,
                logical_window_end: span.end,
                shard: String::new(),
                not_before: now,
                estimated_cost: 1,
                requested_points_digest: None,
            });
        }
    }
    Ok((plan, jobs))
}
