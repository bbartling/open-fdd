//! Read models for `GET /api/ingest/catchup`.

use std::sync::Arc;

use chrono::{DateTime, Duration, Utc};
use serde_json::json;
use sqlx::PgPool;

use crate::providers::committed_model::IngestPlan;
use crate::providers::config::SiteConfig;
use crate::providers::hourly::{floor_to_window, validate_ingest_window_secs, HourlyPolicy};
use crate::providers::http_policy::provider_ids_equivalent;
use crate::state::AppState;

use super::asap_mode::{decide_mode, eta_seconds, AsapConfig};
use super::binding_state::{
    ensure_binding_row, last_stored_ts_for_device, stored_hour_starts_for_device, DeviceBindingKey,
    EnsureBindingInput,
};

use super::gap_backfill::point_keys_for_plan_device;
use super::gap_planner::{default_max_span, expected_start, plan_gap_windows, GapPlanInput};
use super::model::MAX_CATCHUP_HOURS;
use super::worker::publication_delay_secs;

pub async fn site_catchup_json(
    state: &Arc<AppState>,
    pool: &PgPool,
    site: &str,
    configs: &[&SiteConfig],
    now: DateTime<Utc>,
) -> Result<Vec<Value>, String> {
    let config = AsapConfig::from_env()?;
    let delay = Duration::seconds(publication_delay_secs() as i64);
    let step = validate_ingest_window_secs(HourlyPolicy::from_env().window_secs)?;
    let target_end = floor_to_window(now - delay, step);
    let mut providers = Vec::new();
    for site_cfg in configs {
        let tenant_id = site_cfg.tenant_id.as_str();
        let plan = {
            let models = state
                .providers
                .models
                .lock()
                .map_err(|_| "models lock poisoned".to_string())?;
            models.active_plan(tenant_id, site).cloned()
        };
        let Some(plan) = plan else {
            providers.push(json!({
                "provider_instance_id": site_cfg.provider_instance_id,
                "devices": [],
                "state": "not_configured",
            }));
            continue;
        };
        let mut devices = Vec::new();
        for group in plan.groups.iter().filter(|group| {
            provider_ids_equivalent(&group.provider_instance_id, &site_cfg.provider_instance_id)
        }) {
            let key = DeviceBindingKey {
                tenant_id: site_cfg.tenant_id.clone(),
                canonical_site: site_cfg.building_id.clone(),
                provider_instance_id: group.provider_instance_id.clone(),
                device_id: group.equipment_id.clone(),
                model_revision: plan.revision_id.clone(),
            };
            let rows_per_minute = state
                .ingest_queue
                .catchup_registry()
                .read()
                .map_err(|_| "catchup registry lock poisoned".to_string())?
                .rows_per_minute(&key);
            let row = device_row(DeviceCatchupRowInput {
                pool,
                state,
                plan: &plan,
                site_cfg,
                device_id: group.equipment_id.as_str(),
                provider_instance_id: &group.provider_instance_id,
                now,
                target_end,
                delay,
                step,
                config,
                rows_per_minute,
            })
            .await?;
            devices.push(row);
        }
        providers.push(json!({
            "provider_instance_id": site_cfg.provider_instance_id,
            "devices": devices,
        }));
    }
    Ok(providers)
}

struct DeviceCatchupRowInput<'a> {
    pool: &'a PgPool,
    state: &'a Arc<AppState>,
    plan: &'a IngestPlan,
    site_cfg: &'a SiteConfig,
    device_id: &'a str,
    provider_instance_id: &'a str,
    now: DateTime<Utc>,
    target_end: DateTime<Utc>,
    delay: Duration,
    step: i64,
    config: AsapConfig,
    rows_per_minute: Option<f64>,
}

async fn device_row(input: DeviceCatchupRowInput<'_>) -> Result<Value, String> {
    let DeviceCatchupRowInput {
        pool,
        state,
        plan,
        site_cfg,
        device_id,
        provider_instance_id,
        now,
        target_end,
        delay,
        step,
        config,
        rows_per_minute,
    } = input;
    let point_keys = point_keys_for_plan_device(plan, provider_instance_id, device_id)
        .ok_or_else(|| "device not in plan".to_string())?;
    let key = DeviceBindingKey {
        tenant_id: site_cfg.tenant_id.clone(),
        canonical_site: site_cfg.building_id.clone(),
        provider_instance_id: provider_instance_id.to_string(),
        device_id: device_id.to_string(),
        model_revision: plan.revision_id.clone(),
    };
    let range_start = target_end - Duration::hours(i64::from(MAX_CATCHUP_HOURS));
    let binding = ensure_binding_row(
        pool,
        EnsureBindingInput {
            key: &key,
            planning_range_start: range_start,
            now,
        },
    )
    .await
    .map_err(|err| err.to_string())?;
    let stored = stored_hour_starts_for_device(
        pool,
        &site_cfg.building_id,
        &point_keys,
        range_start,
        target_end,
    )
    .await
    .map_err(|err| err.to_string())?;
    let last_stored = last_stored_ts_for_device(pool, &site_cfg.building_id, &point_keys)
        .await
        .map_err(|err| err.to_string())?;
    let plan_start = expected_start(
        range_start,
        binding.provider_data_start,
        binding.binding_created_at,
    );
    let gap_plan = plan_gap_windows(GapPlanInput {
        requested_start: plan_start,
        requested_end: target_end,
        provider_data_start: binding.provider_data_start,
        binding_created_at: binding.binding_created_at,
        stored_hour_starts: &stored,
        last_stored_ts: last_stored,
        force: false,
        max_span: default_max_span(),
    })?;
    let decision = decide_mode(
        &gap_plan,
        last_stored,
        now,
        delay,
        step,
        config.threshold_windows,
    )?;
    let eta = eta_seconds(decision.missing_windows, step, rows_per_minute)?;
    let throttle = state
        .ingest_queue
        .portal_budget_status(provider_instance_id, now)
        .await
        .map_err(|err| err.to_string())?;
    let throttle_state = if throttle.paused_until.is_some_and(|until| until > now) {
        "paused"
    } else if throttle.tokens_remaining.is_some_and(|t| t <= 0) {
        "rate_limited"
    } else {
        "ready"
    };
    Ok(json!({
        "device_id": device_id,
        "mode": decision.mode.as_str(),
        "last_stored_ts": last_stored,
        "missing_windows": decision.missing_windows,
        "rows_per_minute": rows_per_minute,
        "eta_seconds": eta,
        "throttle": {
            "state": throttle_state,
            "paused_until": throttle.paused_until,
            "tokens_remaining": throttle.tokens_remaining,
        },
    }))
}
