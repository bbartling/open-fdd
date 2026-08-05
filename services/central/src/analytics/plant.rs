//! Plant RCx — chiller / boiler descriptive evidence (minimal C8).

use serde_json::json;

use super::{
    envelope, finalize_historian, historian, resolve_query_version, AnalyticsEnvelope,
    AnalyticsRequest,
};

pub const QV_RCX_CHILLER: &str = "rcx-chiller-v1";
pub const QV_RCX_BOILER: &str = "rcx-boiler-v1";

/// Evidence rows: equipment_id, kind (chiller|boiler), run_hours, oat_at_run_mean (optional),
/// short_cycle_count (optional). Never invents kW/ton without power+flow inputs.
pub fn handle_chiller(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    handle_plant(req, QV_RCX_CHILLER, "chiller")
}

pub fn handle_boiler(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    handle_plant(req, QV_RCX_BOILER, "boiler")
}

/// Async chiller handler: prefer historian descriptive counts via DataFusion
/// when no inline series is provided (never invents kW/ton); else inline.
pub async fn handle_chiller_async(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    if let Some(env) = plant_from_history(req, QV_RCX_CHILLER, "chiller").await {
        return env;
    }
    handle_chiller(req)
}

/// Async boiler handler: prefer historian descriptive counts via DataFusion
/// when no inline series is provided; else inline.
pub async fn handle_boiler_async(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    if let Some(env) = plant_from_history(req, QV_RCX_BOILER, "boiler").await {
        return env;
    }
    handle_boiler(req)
}

/// Historian descriptive-count bridge shared by chiller/boiler async handlers.
/// Returns `None` when inline series is present or historian is unavailable, so
/// the caller falls back to the inline descriptive-RCx path.
async fn plant_from_history(
    req: &AnalyticsRequest,
    expected_qv: &str,
    kind: &str,
) -> Option<AnalyticsEnvelope> {
    if req.series.is_some() {
        return None;
    }
    let note =
        format!("{kind} plant: run_hours / kW-ton evidence requires inline series.equipment[]");
    match historian::descriptive_counts_from_history(
        expected_qv,
        req.query.equipment_ids.as_deref(),
        &note,
        req.query.building_id.as_deref(),
    )
    .await
    {
        Ok(Some(env)) => Some(finalize_historian(req, env, expected_qv)),
        Ok(None) => None,
        Err(e) => {
            tracing::warn!(error = %e, "historian plant path failed; using inline/empty fallback");
            None
        }
    }
}

fn handle_plant(req: &AnalyticsRequest, expected_qv: &str, kind: &str) -> AnalyticsEnvelope {
    let (qv, mut warnings) = resolve_query_version(req, expected_qv);
    let mut env = envelope(&qv, &req.query, warnings.clone());
    let Some(series) = req.series.as_ref() else {
        warnings.push(format!(
            "{kind} plant: provide series.equipment[] with run_hours; kW/ton omitted without power+flow"
        ));
        env.warnings = warnings;
        return env;
    };
    let rows = series
        .get("equipment")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    for row in rows {
        let eq = row
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let run_hours = row.get("run_hours").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let oat = row.get("oat_at_run_mean_f").and_then(|v| v.as_f64());
        let short_cycles = row
            .get("short_cycle_count")
            .and_then(|v| v.as_u64())
            .unwrap_or(0);
        let has_power = row.get("power_kw").and_then(|v| v.as_f64()).is_some();
        let has_flow = row.get("flow_gpm").and_then(|v| v.as_f64()).is_some();
        let kw_ton = if has_power && has_flow {
            row.get("kw_per_ton").cloned()
        } else {
            None
        };
        if !has_power || !has_flow {
            warnings.push(format!(
                "{eq}: kW/ton not computed (requires power_kw and flow_gpm)"
            ));
        }
        env.equipment.push(json!({
            "equipment_id": eq,
            "plant_kind": kind,
            "run_hours": run_hours,
            "oat_at_run_mean_f": oat,
            "short_cycle_count": short_cycles,
            "kw_per_ton": kw_ton,
            "evidence_class": "descriptive_rcx",
        }));
    }
    env.coverage = Some(json!({"equipment_count": env.equipment.len()}));
    env.warnings = warnings;
    env
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analytics::AnalyticsQuery;
    use serde_json::json;

    #[test]
    fn chiller_does_not_invent_kw_ton() {
        let req = AnalyticsRequest {
            query: AnalyticsQuery::default(),
            series: Some(json!({
                "equipment": [{"equipment_id": "CH-1", "run_hours": 10.0}]
            })),
            ..Default::default()
        };
        let env = handle_chiller(&req);
        assert_eq!(env.query_version, QV_RCX_CHILLER);
        assert!(env.equipment[0].get("kw_per_ton").unwrap().is_null());
        assert!(env.warnings.iter().any(|w| w.contains("kW/ton")));
    }
}
