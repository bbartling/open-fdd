//! Gap-only backfill job construction from Timescale stored hours.

use chrono::{DateTime, Utc};
use sqlx::PgPool;

use crate::providers::committed_model::{IngestDeviceGroup, IngestPlan};
use crate::providers::http_policy::provider_ids_equivalent;

use super::binding_state::{
    ensure_binding_row, last_stored_ts_for_device, stored_hour_starts_for_device, DeviceBindingKey,
    DevicePointCoverage, EnsureBindingInput,
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

pub fn point_coverage_for_group(group: &IngestDeviceGroup) -> Vec<DevicePointCoverage> {
    group
        .points
        .iter()
        .map(|point| DevicePointCoverage {
            openfdd_key: point.semantic_point_id.clone(),
            coverage_point_id: point.source_point_id.clone(),
            history_mode: point.history_mode.clone(),
            cadence_secs: point.cadence_secs,
            heartbeat_secs: point.heartbeat_secs,
        })
        .collect()
}

pub fn point_keys_for_plan_device(
    plan: &IngestPlan,
    provider_instance_id: &str,
    device_id: &str,
) -> Option<Vec<String>> {
    plan.groups
        .iter()
        .find(|group| {
            group.equipment_id == device_id
                && provider_ids_equivalent(&group.provider_instance_id, provider_instance_id)
        })
        .map(point_keys_for_group)
}

#[derive(Debug, Clone)]
pub struct DeviceGapBackfillRequest<'a> {
    pub key: DeviceBindingKey,
    pub group: &'a IngestDeviceGroup,
    pub range_start: DateTime<Utc>,
    pub range_end: DateTime<Utc>,
    pub force: bool,
    pub now: DateTime<Utc>,
}

#[derive(Debug, Clone)]
pub struct ExplicitGapBackfillRequest {
    pub key: DeviceBindingKey,
    pub point_keys: Vec<String>,
    pub windows: Vec<(DateTime<Utc>, DateTime<Utc>)>,
    pub force: bool,
    pub now: DateTime<Utc>,
}

pub async fn plan_device_gap_backfill(
    pool: &PgPool,
    request: DeviceGapBackfillRequest<'_>,
) -> Result<(GapPlanResult, Vec<NewJob>), QueueError> {
    let keys = point_keys_for_group(request.group);
    let coverage = point_coverage_for_group(request.group);
    let binding = ensure_binding_row(
        pool,
        EnsureBindingInput {
            key: &request.key,
            planning_range_start: request.range_start,
            now: request.now,
        },
    )
    .await?;
    let stored = stored_hour_starts_for_device(
        pool,
        &request.key,
        &request.key.canonical_site,
        &coverage,
        request.range_start,
        request.range_end,
    )
    .await?;
    let last_stored = last_stored_ts_for_device(pool, &request.key.canonical_site, &keys).await?;
    let plan = plan_gap_windows(GapPlanInput {
        requested_start: request.range_start,
        requested_end: request.range_end,
        provider_data_start: binding.provider_data_start,
        binding_created_at: binding.binding_created_at,
        stored_hour_starts: &stored,
        last_stored_ts: last_stored,
        force: request.force,
        max_span: default_max_span(),
    })
    .map_err(QueueError::Invalid)?;
    let mut jobs = Vec::new();
    for span in &plan.planned {
        jobs.push(NewJob {
            tenant_id: request.key.tenant_id.clone(),
            canonical_site: request.key.canonical_site.clone(),
            provider_instance_id: request.key.provider_instance_id.clone(),
            device_id: request.key.device_id.clone(),
            model_revision: request.key.model_revision.clone(),
            logical_window_start: span.start,
            logical_window_end: span.end,
            shard: String::new(),
            not_before: request.now,
            estimated_cost: 1,
            requested_points_digest: None,
        });
    }
    Ok((plan, jobs))
}

pub async fn plan_explicit_windows(
    pool: &PgPool,
    request: ExplicitGapBackfillRequest,
) -> Result<(GapPlanResult, Vec<NewJob>), QueueError> {
    if request.windows.is_empty() {
        return Err(QueueError::Invalid("backfill windows are empty".into()));
    }
    let range_start = request.windows[0].0;
    let range_end = request.windows[request.windows.len() - 1].1;
    let binding = ensure_binding_row(
        pool,
        EnsureBindingInput {
            key: &request.key,
            planning_range_start: range_start,
            now: request.now,
        },
    )
    .await?;
    let coverage: Vec<DevicePointCoverage> = request
        .point_keys
        .iter()
        .map(|key| DevicePointCoverage {
            openfdd_key: key.clone(),
            coverage_point_id: key.clone(),
            history_mode: None,
            cadence_secs: None,
            heartbeat_secs: None,
        })
        .collect();
    let stored = stored_hour_starts_for_device(
        pool,
        &request.key,
        &request.key.canonical_site,
        &coverage,
        range_start,
        range_end,
    )
    .await?;
    let last_stored =
        last_stored_ts_for_device(pool, &request.key.canonical_site, &request.point_keys).await?;
    let plan = plan_gap_windows(GapPlanInput {
        requested_start: range_start,
        requested_end: range_end,
        provider_data_start: binding.provider_data_start,
        binding_created_at: binding.binding_created_at,
        stored_hour_starts: &stored,
        last_stored_ts: last_stored,
        force: request.force,
        max_span: default_max_span(),
    })
    .map_err(QueueError::Invalid)?;
    let mut jobs = Vec::new();
    for span in &plan.planned {
        let overlaps = request
            .windows
            .iter()
            .any(|(start, end)| span.start < *end && span.end > *start);
        if overlaps {
            jobs.push(NewJob {
                tenant_id: request.key.tenant_id.clone(),
                canonical_site: request.key.canonical_site.clone(),
                provider_instance_id: request.key.provider_instance_id.clone(),
                device_id: request.key.device_id.clone(),
                model_revision: request.key.model_revision.clone(),
                logical_window_start: span.start,
                logical_window_end: span.end,
                shard: String::new(),
                not_before: request.now,
                estimated_cost: 1,
                requested_points_digest: None,
            });
        }
    }
    Ok((plan, jobs))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::providers::committed_model::{IngestDeviceGroup, PlannedPoint};

    #[test]
    fn point_keys_for_plan_device_requires_matching_group() {
        let plan = IngestPlan {
            schema: "ofdd_portal_ingest_plan_v1".into(),
            revision_id: "rev".into(),
            tenant_id: "tenant".into(),
            site_id: "site".into(),
            groups: vec![IngestDeviceGroup {
                provider_instance_id: "nf:conn".into(),
                equipment_id: "AHU_1".into(),
                equip_type: "ahu".into(),
                points: vec![PlannedPoint {
                    semantic_point_id: "urn:openfdd:point:site:AHU_1:sat".into(),
                    source_point_id: "src".into(),
                    canonical_role: "sat".into(),
                    kind: None,
                    source_unit: None,
                    canonical_unit: None,
                    quantity: None,
                    history_mode: None,
                    cadence_secs: None,
                    heartbeat_secs: None,
                }],
            }],
            withheld: Vec::new(),
        };
        let keys = point_keys_for_plan_device(&plan, "nf:conn", "AHU_1").expect("group");
        assert_eq!(keys.len(), 1);
        assert!(point_keys_for_plan_device(&plan, "nf:conn", "missing").is_none());
        assert!(point_keys_for_plan_device(&plan, "nf:wrong", "AHU_1").is_none());
    }
}
