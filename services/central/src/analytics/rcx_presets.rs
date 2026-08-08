//! RCx preset metadata + DataFusion series for vibe19 RCx Plots parity.
//!
//! Catalog mirrors `open_fdd/analytics/rcx_plots.py` PRESETS (20) including the
//! 18 frozen `REQUIRED_RCX_PRESET_IDS` plus AHU valve extras.

use anyhow::Result;
use serde_json::{json, Value};

use super::historian;
use super::{envelope_with_engine, AnalyticsEnvelope, AnalyticsQuery, DF_ENGINE};

#[derive(Clone, Copy)]
pub struct RcxPresetMeta {
    pub id: &'static str,
    pub title: &'static str,
    pub family: &'static str,
    pub chart: &'static str,
    pub role_col: &'static str,
    pub eq_kinds: &'static [&'static str],
    pub overlay_col: Option<&'static str>,
    pub pair_return_col: Option<&'static str>,
    pub filter_fan_on: bool,
    /// For scatter: use wet-bulb OAT when present (`cw_reset_scatter`).
    pub prefer_wetbulb: bool,
    /// Metering kind: "electric" | "gas" (chart == metering).
    pub meter_kind: Option<&'static str>,
}

/// Full vibe19 preset catalog (frozen 18 + valve extras).
pub const RCX_PRESETS: &[RcxPresetMeta] = &[
    RcxPresetMeta {
        id: "zone_comfort_rank",
        title: "Zones — comfort fail ranking (occupied hours)",
        family: "Zones / VAV",
        chart: "ranking",
        role_col: "zone_t",
        eq_kinds: &["VAV"],
        overlay_col: None,
        pair_return_col: None,
        filter_fan_on: false,
        prefer_wetbulb: false,
        meter_kind: None,
    },
    RcxPresetMeta {
        id: "zone_temps",
        title: "Zones — all space temps (timeseries)",
        family: "Zones / VAV",
        chart: "timeseries",
        role_col: "zone_t",
        eq_kinds: &["VAV"],
        overlay_col: None,
        pair_return_col: None,
        filter_fan_on: false,
        prefer_wetbulb: false,
        meter_kind: None,
    },
    RcxPresetMeta {
        id: "vav_flows",
        title: "Zones — all VAV airflow (timeseries)",
        family: "Zones / VAV",
        chart: "timeseries",
        role_col: "zone_flow",
        eq_kinds: &["VAV"],
        overlay_col: None,
        pair_return_col: None,
        filter_fan_on: false,
        prefer_wetbulb: false,
        meter_kind: None,
    },
    RcxPresetMeta {
        id: "ahu_sat_reset_scatter",
        title: "AHU — SAT vs web dry-bulb (scatter)",
        family: "AHU / air",
        chart: "scatter_oat",
        role_col: "sat",
        eq_kinds: &["AHU", "RTU", "MAU"],
        overlay_col: None,
        pair_return_col: None,
        filter_fan_on: false,
        prefer_wetbulb: false,
        meter_kind: None,
    },
    RcxPresetMeta {
        id: "ahu_dats",
        title: "AHU — all DATs / SAT (timeseries)",
        family: "AHU / air",
        chart: "timeseries",
        role_col: "sat",
        eq_kinds: &["AHU", "RTU", "MAU"],
        overlay_col: None,
        pair_return_col: None,
        filter_fan_on: false,
        prefer_wetbulb: false,
        meter_kind: None,
    },
    RcxPresetMeta {
        id: "ahu_mats",
        title: "AHU — all MATs (timeseries)",
        family: "AHU / air",
        chart: "timeseries",
        role_col: "mat",
        eq_kinds: &["AHU", "RTU", "MAU"],
        overlay_col: None,
        pair_return_col: None,
        filter_fan_on: false,
        prefer_wetbulb: false,
        meter_kind: None,
    },
    RcxPresetMeta {
        id: "ahu_rats",
        title: "AHU — all RATs (timeseries)",
        family: "AHU / air",
        chart: "timeseries",
        role_col: "rat",
        eq_kinds: &["AHU", "RTU", "MAU"],
        overlay_col: None,
        pair_return_col: None,
        filter_fan_on: false,
        prefer_wetbulb: false,
        meter_kind: None,
    },
    RcxPresetMeta {
        id: "ahu_dampers",
        title: "AHU — OA dampers (timeseries)",
        family: "AHU / air",
        chart: "timeseries",
        role_col: "oa_damper_pct",
        eq_kinds: &["AHU", "RTU", "MAU"],
        overlay_col: None,
        pair_return_col: None,
        filter_fan_on: false,
        prefer_wetbulb: false,
        meter_kind: None,
    },
    RcxPresetMeta {
        id: "ahu_cooling_valves",
        title: "AHU — cooling valves (timeseries)",
        family: "AHU / air",
        chart: "timeseries",
        role_col: "clg_valve_pct",
        eq_kinds: &["AHU", "RTU", "MAU"],
        overlay_col: None,
        pair_return_col: None,
        filter_fan_on: false,
        prefer_wetbulb: false,
        meter_kind: None,
    },
    RcxPresetMeta {
        id: "ahu_heating_valves",
        title: "AHU — heating valves (timeseries)",
        family: "AHU / air",
        chart: "timeseries",
        role_col: "htg_valve_pct",
        eq_kinds: &["AHU", "RTU", "MAU"],
        overlay_col: None,
        pair_return_col: None,
        filter_fan_on: false,
        prefer_wetbulb: false,
        meter_kind: None,
    },
    RcxPresetMeta {
        id: "fan_speeds",
        title: "AHU — fan speeds / cmds (timeseries)",
        family: "AHU / air",
        chart: "timeseries",
        role_col: "fan_cmd",
        eq_kinds: &["AHU", "RTU", "MAU"],
        overlay_col: None,
        pair_return_col: None,
        filter_fan_on: false,
        prefer_wetbulb: false,
        meter_kind: None,
    },
    RcxPresetMeta {
        id: "duct_static_box",
        title: "AHU — duct static fan-on (box)",
        family: "AHU / air",
        chart: "box",
        role_col: "duct_static",
        eq_kinds: &["AHU", "RTU", "MAU"],
        overlay_col: None,
        pair_return_col: None,
        filter_fan_on: true,
        prefer_wetbulb: false,
        meter_kind: None,
    },
    RcxPresetMeta {
        id: "duct_static_ts",
        title: "AHU — duct static + setpoint (timeseries)",
        family: "AHU / air",
        chart: "timeseries",
        role_col: "duct_static",
        eq_kinds: &["AHU", "RTU", "MAU"],
        overlay_col: Some("duct_static_sp"),
        pair_return_col: None,
        filter_fan_on: false,
        prefer_wetbulb: false,
        meter_kind: None,
    },
    RcxPresetMeta {
        id: "hw_reset_scatter",
        title: "Boiler — HWS vs web dry-bulb (scatter)",
        family: "Boiler / HW",
        chart: "scatter_oat",
        role_col: "hw_supply_t",
        eq_kinds: &["BOILER"],
        overlay_col: None,
        pair_return_col: None,
        filter_fan_on: false,
        prefer_wetbulb: false,
        meter_kind: None,
    },
    RcxPresetMeta {
        id: "chw_reset_scatter",
        title: "Chiller — CHWS vs web dry-bulb (scatter)",
        family: "Chiller / CHW / tower",
        chart: "scatter_oat",
        role_col: "chw_supply_t",
        eq_kinds: &["CHILLER", "CHW"],
        overlay_col: None,
        pair_return_col: None,
        filter_fan_on: false,
        prefer_wetbulb: false,
        meter_kind: None,
    },
    RcxPresetMeta {
        id: "cw_reset_scatter",
        title: "Tower / CW — leave temp vs wet-bulb + dry-bulb ref (scatter)",
        family: "Chiller / CHW / tower",
        chart: "scatter_oat",
        role_col: "cw_supply_t",
        eq_kinds: &["CHILLER", "CHW", "TOWER", "CT"],
        overlay_col: None,
        pair_return_col: None,
        filter_fan_on: false,
        prefer_wetbulb: true,
        meter_kind: None,
    },
    RcxPresetMeta {
        id: "chw_temps_ts",
        title: "Chiller — CHW supply/return/ΔT (timeseries)",
        family: "Chiller / CHW / tower",
        chart: "timeseries",
        role_col: "chw_supply_t",
        eq_kinds: &["CHILLER", "CHW"],
        overlay_col: None,
        pair_return_col: Some("chw_return_t"),
        filter_fan_on: false,
        prefer_wetbulb: false,
        meter_kind: None,
    },
    RcxPresetMeta {
        id: "cw_temps_ts",
        title: "Tower / CW — supply/return/ΔT (timeseries)",
        family: "Chiller / CHW / tower",
        chart: "timeseries",
        role_col: "cw_supply_t",
        eq_kinds: &["CHILLER", "CHW", "TOWER", "CT"],
        overlay_col: None,
        pair_return_col: Some("cw_return_t"),
        filter_fan_on: false,
        prefer_wetbulb: false,
        meter_kind: None,
    },
    RcxPresetMeta {
        id: "meter_elec_cdd",
        title: "Metering — electric kWh/month vs CDD (scatter + stats)",
        family: "Metering",
        chart: "metering",
        role_col: "elec_power",
        eq_kinds: &["METER", "CHILLER", "CHW"],
        overlay_col: None,
        pair_return_col: None,
        filter_fan_on: false,
        prefer_wetbulb: false,
        meter_kind: Some("electric"),
    },
    RcxPresetMeta {
        id: "meter_gas_hdd",
        title: "Metering — gas/month vs HDD (scatter + stats)",
        family: "Metering",
        chart: "metering",
        role_col: "gas_flow",
        eq_kinds: &["METER", "BOILER"],
        overlay_col: None,
        pair_return_col: None,
        filter_fan_on: false,
        prefer_wetbulb: false,
        meter_kind: Some("gas"),
    },
];

/// Frozen catalog ids (must stay listed even when columns are absent on a site).
pub const REQUIRED_RCX_PRESET_IDS: &[&str] = &[
    "zone_comfort_rank",
    "zone_temps",
    "ahu_dats",
    "ahu_mats",
    "ahu_rats",
    "ahu_dampers",
    "duct_static_box",
    "ahu_sat_reset_scatter",
    "hw_reset_scatter",
    "chw_reset_scatter",
    "cw_reset_scatter",
    "vav_flows",
    "fan_speeds",
    "meter_elec_cdd",
    "meter_gas_hdd",
    "duct_static_ts",
    "chw_temps_ts",
    "cw_temps_ts",
];

pub fn preset_by_id(id: &str) -> Option<&'static RcxPresetMeta> {
    RCX_PRESETS.iter().find(|p| p.id == id)
}

pub fn presets_json() -> Value {
    json!(RCX_PRESETS
        .iter()
        .map(|p| json!({
            "id": p.id,
            "title": p.title,
            "family": p.family,
            "chart": p.chart,
            "role_col": p.role_col,
            "filter_fan_on": p.filter_fan_on,
            "frozen": REQUIRED_RCX_PRESET_IDS.contains(&p.id),
        }))
        .collect::<Vec<_>>())
}

fn annotate(mut env: AnalyticsEnvelope, meta: &RcxPresetMeta) -> AnalyticsEnvelope {
    env.query_version = format!("rcx-preset-{}-v1", meta.id);
    let mut cov = env.coverage.unwrap_or_else(|| json!({}));
    if let Some(obj) = cov.as_object_mut() {
        obj.insert("preset_id".into(), json!(meta.id));
        obj.insert("chart_kind".into(), json!(meta.chart));
        obj.insert("title".into(), json!(meta.title));
        obj.insert("family".into(), json!(meta.family));
        obj.insert("role_col".into(), json!(meta.role_col));
        obj.insert("y_col".into(), json!(meta.role_col));
        obj.insert("prefer_wetbulb".into(), json!(meta.prefer_wetbulb));
        if let Some(mk) = meta.meter_kind {
            obj.insert("meter_kind".into(), json!(mk));
        }
    }
    env.coverage = Some(cov);
    env
}

fn empty_stub(meta: &RcxPresetMeta, reason: &str) -> AnalyticsEnvelope {
    let query = AnalyticsQuery::default();
    let mut env = envelope_with_engine(
        &format!("rcx-preset-{}-v1", meta.id),
        &query,
        vec![reason.to_string()],
        DF_ENGINE,
    );
    env.coverage = Some(json!({
        "preset_id": meta.id,
        "chart_kind": meta.chart,
        "title": meta.title,
        "family": meta.family,
        "role_col": meta.role_col,
        "y_col": meta.role_col,
        "empty": true,
    }));
    env
}

/// Run a named RCx preset against historian parquet.
pub async fn run_preset(
    building_id: Option<&str>,
    preset_id: &str,
    max_points: usize,
) -> Result<Option<AnalyticsEnvelope>> {
    let Some(meta) = preset_by_id(preset_id) else {
        return Ok(None);
    };
    let out = match meta.chart {
        "timeseries" => {
            historian::rcx_timeseries_from_history(
                building_id,
                meta.role_col,
                meta.overlay_col,
                meta.pair_return_col,
                meta.eq_kinds,
                meta.filter_fan_on,
                max_points,
            )
            .await?
        }
        "scatter_oat" => {
            historian::rcx_oat_scatter_from_history(
                building_id,
                meta.role_col,
                meta.eq_kinds,
                meta.prefer_wetbulb,
                max_points,
            )
            .await?
        }
        "box" => {
            historian::rcx_box_from_history(
                building_id,
                meta.role_col,
                meta.eq_kinds,
                meta.filter_fan_on,
                max_points,
            )
            .await?
        }
        "ranking" => {
            historian::rcx_zone_comfort_rank_from_history(building_id, meta.eq_kinds, 70.0, 75.0)
                .await?
        }
        "metering" => {
            historian::rcx_metering_from_history(
                building_id,
                meta.role_col,
                meta.eq_kinds,
                meta.meter_kind.unwrap_or("electric"),
            )
            .await?
        }
        other => {
            return Ok(Some(empty_stub(
                meta,
                &format!(
                    "RCx preset '{}' chart kind '{other}' not yet wired in DataFusion",
                    meta.id
                ),
            )));
        }
    };
    Ok(Some(match out {
        Some(env) => annotate(env, meta),
        None => empty_stub(
            meta,
            &format!(
                "RCx preset '{}' unavailable — missing historian column '{}' or no matching equipment",
                meta.id, meta.role_col
            ),
        ),
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frozen_presets_all_listed() {
        for id in REQUIRED_RCX_PRESET_IDS {
            assert!(
                preset_by_id(id).is_some(),
                "frozen preset {id} missing from RCX_PRESETS"
            );
        }
        assert!(RCX_PRESETS.len() >= 18);
        assert!(presets_json().as_array().unwrap().len() >= 18);
    }
}
