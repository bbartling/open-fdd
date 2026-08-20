//! Overview health matrices backed by FDD result rows.
//!
//! Matrix specs are arbitrary-length flag slices. Missing evidence is unknown,
//! never PASS. Scores are reported as `n/m`, each flag preserves its own
//! `{key}_fault_h`, and typed equipment stamps win over id heuristics.

use std::collections::{BTreeMap, BTreeSet, HashMap};

use anyhow::Result;
use datafusion::prelude::SessionContext;
use fdd_sql::run_sql;
use serde_json::{json, Map, Value};

use super::historian::try_register_history_scoped;
use super::{envelope_with_engine, AnalyticsEnvelope, AnalyticsQuery, AnalyticsRequest, DF_ENGINE};

pub const QV_AHU_HEALTH: &str = "ahu-health-v1";
pub const QV_AHU_TEMPERATURE_HEALTH: &str = "ahu-temperature-health-v1";
pub const QV_AHU_PRESSURE_HEALTH: &str = "ahu-pressure-health-v1";
pub const QV_AHU_ECONOMIZER_HEALTH: &str = "ahu-economizer-health-v1";
pub const QV_CHILLER_HEALTH: &str = "chiller-health-v2";
pub const QV_COOLING_TOWER_HEALTH: &str = "cooling-tower-health-v1";
pub const QV_BOILER_HEALTH: &str = "boiler-health-v1";
pub const QV_HP_HEALTH: &str = "hp-health-v1";
pub const QV_SENSOR_FAULTS: &str = "sensor-faults-v1";
pub const QV_PID_HUNTING: &str = "pid-hunting-v1";

pub const SCHEMA_AHU_HEALTH: &str = "ahu_health_matrix_v1";
pub const SCHEMA_AHU_TEMPERATURE_HEALTH: &str = "ahu_temperature_health_matrix_v1";
pub const SCHEMA_AHU_PRESSURE_HEALTH: &str = "ahu_pressure_health_matrix_v1";
pub const SCHEMA_AHU_ECONOMIZER_HEALTH: &str = "ahu_economizer_health_matrix_v1";
pub const SCHEMA_CHILLER_HEALTH: &str = "chiller_health_matrix_v2";
pub const SCHEMA_COOLING_TOWER_HEALTH: &str = "cooling_tower_health_matrix_v1";
pub const SCHEMA_BOILER_HEALTH: &str = "boiler_health_matrix_v1";
pub const SCHEMA_HP_HEALTH: &str = "hp_health_matrix_v1";
pub const SCHEMA_SENSOR_FAULTS: &str = "sensor_fault_matrix_v1";
pub const SCHEMA_PID_HUNTING: &str = "pid_hunting_matrix_v1";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PlantFamily {
    Ahu,
    Chiller,
    CoolingTower,
    Boiler,
    HeatPump,
}

#[derive(Clone, Copy)]
struct FlagSpec {
    key: &'static str,
    label: &'static str,
    primary: &'static str,
    fallback: Option<&'static str>,
}

#[derive(Clone, Copy)]
enum EquipmentScope {
    Family(PlantFamily),
    AnyFdd,
}

struct MatrixSpec {
    scope: EquipmentScope,
    query_version: &'static str,
    schema: &'static str,
    flags: &'static [FlagSpec],
    notes: &'static str,
    faults_only: bool,
}

const AHU_LEGACY_FLAGS: &[FlagSpec] = &[
    FlagSpec {
        key: "sat_dev",
        label: "SAT",
        primary: "AHU-SATDEV",
        fallback: None,
    },
    FlagSpec {
        key: "duct_high",
        label: "Duct",
        primary: "AHU-DUCTHI",
        fallback: None,
    },
    FlagSpec {
        key: "economizer",
        label: "Econ",
        primary: "ECON-1",
        fallback: Some("ECON-2"),
    },
];
const AHU_TEMPERATURE_FLAGS: &[FlagSpec] = &[
    FlagSpec {
        key: "sat_dev",
        label: "SAT dev",
        primary: "AHU-SATDEV",
        fallback: None,
    },
    FlagSpec {
        key: "mat_low",
        label: "MAT low",
        primary: "FC2",
        fallback: None,
    },
    FlagSpec {
        key: "mat_high",
        label: "MAT high",
        primary: "FC3",
        fallback: None,
    },
    FlagSpec {
        key: "sat_low_heating",
        label: "SAT low heat",
        primary: "FC7",
        fallback: None,
    },
    FlagSpec {
        key: "sat_high_cooling",
        label: "SAT high cool",
        primary: "FC13-SAT-HIGH",
        fallback: None,
    },
];
const AHU_PRESSURE_FLAGS: &[FlagSpec] = &[
    FlagSpec {
        key: "duct_high",
        label: "Duct high",
        primary: "AHU-DUCTHI",
        fallback: None,
    },
    FlagSpec {
        key: "duct_low",
        label: "Duct low",
        primary: "FC1",
        fallback: None,
    },
    FlagSpec {
        key: "fan_mismatch",
        label: "Fan mismatch",
        primary: "CMD-1",
        fallback: None,
    },
    FlagSpec {
        key: "static_trim",
        label: "Static trim",
        primary: "TRIM-1",
        fallback: None,
    },
];
const AHU_ECONOMIZER_FLAGS: &[FlagSpec] = &[
    FlagSpec {
        key: "stuck_closed",
        label: "Stuck closed",
        primary: "ECON-1",
        fallback: None,
    },
    FlagSpec {
        key: "unfavorable",
        label: "Unfavorable OA",
        primary: "ECON-2",
        fallback: None,
    },
    FlagSpec {
        key: "mech_without_econ",
        label: "Mech w/o econ",
        primary: "ECON-3",
        fallback: None,
    },
    FlagSpec {
        key: "low_oa_fraction",
        label: "Low OA frac",
        primary: "ECON-4",
        fallback: None,
    },
    FlagSpec {
        key: "preheat_over",
        label: "Preheat",
        primary: "ECON-5",
        fallback: None,
    },
    FlagSpec {
        key: "freeze_risk",
        label: "Freeze",
        primary: "ECON-6",
        fallback: None,
    },
    FlagSpec {
        key: "not_economizing",
        label: "Not economizing",
        primary: "ECON-7",
        fallback: None,
    },
];
const CHILLER_FLAGS: &[FlagSpec] = &[
    FlagSpec {
        key: "low_delta_t",
        label: "Low ΔT",
        primary: "CHW-1",
        fallback: None,
    },
    FlagSpec {
        key: "dp_low",
        label: "DP low",
        primary: "CHW-2",
        fallback: None,
    },
    FlagSpec {
        key: "supply_band",
        label: "Supply band",
        primary: "CHW-3",
        fallback: None,
    },
    FlagSpec {
        key: "flow_high",
        label: "Flow high",
        primary: "CHW-4",
        fallback: None,
    },
    FlagSpec {
        key: "no_load",
        label: "No load",
        primary: "CHW-NOLOAD-1",
        fallback: None,
    },
    FlagSpec {
        key: "chw_reset",
        label: "CHW reset",
        primary: "TRIM-4",
        fallback: None,
    },
];
const COOLING_TOWER_FLAGS: &[FlagSpec] = &[
    FlagSpec {
        key: "approach_high",
        label: "Approach",
        primary: "CW-APR-1",
        fallback: None,
    },
    FlagSpec {
        key: "fan_energy",
        label: "Fan",
        primary: "CW-FAN-1",
        fallback: None,
    },
    FlagSpec {
        key: "cw_optimization",
        label: "CW opt",
        primary: "CW-OPT-1",
        fallback: None,
    },
];
const BOILER_FLAGS: &[FlagSpec] = &[
    FlagSpec {
        key: "fc5",
        label: "FC5",
        primary: "FC5",
        fallback: None,
    },
    FlagSpec {
        key: "fc6",
        label: "FC6",
        primary: "FC6",
        fallback: None,
    },
    FlagSpec {
        key: "fc8",
        label: "FC8",
        primary: "FC8",
        fallback: None,
    },
];
const HP_FLAGS: &[FlagSpec] = &[
    FlagSpec {
        key: "hp_1",
        label: "HP-1",
        primary: "HP-1",
        fallback: None,
    },
    FlagSpec {
        key: "sat_dev",
        label: "SAT",
        primary: "AHU-SATDEV",
        fallback: None,
    },
    FlagSpec {
        key: "economizer",
        label: "Econ",
        primary: "ECON-1",
        fallback: Some("ECON-2"),
    },
];
const SENSOR_FLAGS: &[FlagSpec] = &[
    FlagSpec {
        key: "flatline",
        label: "Flatline",
        primary: "SV-FLATLINE",
        fallback: None,
    },
    FlagSpec {
        key: "range",
        label: "Range",
        primary: "SV-RANGE",
        fallback: None,
    },
    FlagSpec {
        key: "rate",
        label: "Rate",
        primary: "SV-RATE",
        fallback: None,
    },
    FlagSpec {
        key: "spike",
        label: "Spike",
        primary: "SV-SPIKE",
        fallback: None,
    },
    FlagSpec {
        key: "stale",
        label: "Stale",
        primary: "SV-STALE",
        fallback: None,
    },
];
const PID_FLAGS: &[FlagSpec] = &[
    FlagSpec {
        key: "operating_state_hunt",
        label: "OS hunt",
        primary: "FC4",
        fallback: None,
    },
    FlagSpec {
        key: "control_output_hunt",
        label: "PID hunt",
        primary: "PID-HUNT-1",
        fallback: None,
    },
];

const AHU_LEGACY_SPEC: MatrixSpec = MatrixSpec { scope: EquipmentScope::Family(PlantFamily::Ahu), query_version: QV_AHU_HEALTH, schema: SCHEMA_AHU_HEALTH, flags: AHU_LEGACY_FLAGS, notes: "Compatibility AHU matrix; new Overview uses temperature, pressure/fan, and economizer endpoints.", faults_only: false };
const AHU_TEMPERATURE_SPEC: MatrixSpec = MatrixSpec {
    scope: EquipmentScope::Family(PlantFamily::Ahu),
    query_version: QV_AHU_TEMPERATURE_HEALTH,
    schema: SCHEMA_AHU_TEMPERATURE_HEALTH,
    flags: AHU_TEMPERATURE_FLAGS,
    notes: "AHU temperature diagnostics from canonical AHU/FC rules.",
    faults_only: false,
};
const AHU_PRESSURE_SPEC: MatrixSpec = MatrixSpec {
    scope: EquipmentScope::Family(PlantFamily::Ahu),
    query_version: QV_AHU_PRESSURE_HEALTH,
    schema: SCHEMA_AHU_PRESSURE_HEALTH,
    flags: AHU_PRESSURE_FLAGS,
    notes: "AHU duct pressure and fan-command diagnostics.",
    faults_only: false,
};
const AHU_ECONOMIZER_SPEC: MatrixSpec = MatrixSpec {
    scope: EquipmentScope::Family(PlantFamily::Ahu),
    query_version: QV_AHU_ECONOMIZER_HEALTH,
    schema: SCHEMA_AHU_ECONOMIZER_HEALTH,
    flags: AHU_ECONOMIZER_FLAGS,
    notes: "AHU economizer matrix from ECON-1 through ECON-7.",
    faults_only: false,
};
const CHILLER_SPEC: MatrixSpec = MatrixSpec {
    scope: EquipmentScope::Family(PlantFamily::Chiller),
    query_version: QV_CHILLER_HEALTH,
    schema: SCHEMA_CHILLER_HEALTH,
    flags: CHILLER_FLAGS,
    notes: "Expanded chilled-water plant matrix including flow, no-load, and reset diagnostics.",
    faults_only: false,
};
const COOLING_TOWER_SPEC: MatrixSpec = MatrixSpec {
    scope: EquipmentScope::Family(PlantFamily::CoolingTower),
    query_version: QV_COOLING_TOWER_HEALTH,
    schema: SCHEMA_COOLING_TOWER_HEALTH,
    flags: COOLING_TOWER_FLAGS,
    notes: "Cooling-tower condenser-water approach, fan, and optimization diagnostics.",
    faults_only: false,
};
const BOILER_SPEC: MatrixSpec = MatrixSpec {
    scope: EquipmentScope::Family(PlantFamily::Boiler),
    query_version: QV_BOILER_HEALTH,
    schema: SCHEMA_BOILER_HEALTH,
    flags: BOILER_FLAGS,
    notes: "Heating cookbook compatibility matrix.",
    faults_only: false,
};
const HP_SPEC: MatrixSpec = MatrixSpec {
    scope: EquipmentScope::Family(PlantFamily::HeatPump),
    query_version: QV_HP_HEALTH,
    schema: SCHEMA_HP_HEALTH,
    flags: HP_FLAGS,
    notes: "Heat-pump compatibility matrix.",
    faults_only: false,
};
const SENSOR_SPEC: MatrixSpec = MatrixSpec {
    scope: EquipmentScope::AnyFdd,
    query_version: QV_SENSOR_FAULTS,
    schema: SCHEMA_SENSOR_FAULTS,
    flags: SENSOR_FLAGS,
    notes: "Sensor validation faults only; clean results intentionally return rows: [].",
    faults_only: true,
};
const PID_SPEC: MatrixSpec = MatrixSpec {
    scope: EquipmentScope::AnyFdd,
    query_version: QV_PID_HUNTING,
    schema: SCHEMA_PID_HUNTING,
    flags: PID_FLAGS,
    notes: "PID/operating-state hunting evidence from FC4 and PID-HUNT-1.",
    faults_only: false,
};

pub async fn handle_ahu(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    handle_matrix(req, &AHU_LEGACY_SPEC).await
}
pub async fn handle_ahu_temperature(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    handle_matrix(req, &AHU_TEMPERATURE_SPEC).await
}
pub async fn handle_ahu_pressure(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    handle_matrix(req, &AHU_PRESSURE_SPEC).await
}
pub async fn handle_ahu_economizer(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    handle_matrix(req, &AHU_ECONOMIZER_SPEC).await
}
pub async fn handle_chiller(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    handle_matrix(req, &CHILLER_SPEC).await
}
pub async fn handle_cooling_tower(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    handle_matrix(req, &COOLING_TOWER_SPEC).await
}
pub async fn handle_boiler(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    handle_matrix(req, &BOILER_SPEC).await
}
pub async fn handle_hp(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    handle_matrix(req, &HP_SPEC).await
}
pub async fn handle_sensor_faults(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    handle_matrix(req, &SENSOR_SPEC).await
}
pub async fn handle_pid_hunting(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    handle_matrix(req, &PID_SPEC).await
}

async fn handle_matrix(req: &AnalyticsRequest, spec: &MatrixSpec) -> AnalyticsEnvelope {
    match matrix_from_history_or_fdd(req.query.building_id.as_deref(), spec).await {
        Ok(env) => env,
        Err(e) => {
            let mut env = envelope_with_engine(
                spec.query_version,
                &req.query,
                vec![format!("health matrix failed: {e}")],
                DF_ENGINE,
            );
            env.coverage =
                Some(json!({"schema_version": spec.schema, "flag_count": spec.flags.len()}));
            env
        }
    }
}

/// Heat-pump ids stay out of the chiller matrix.
pub fn is_heat_pump_id(equipment_id: &str) -> bool {
    let u = equipment_id
        .to_ascii_uppercase()
        .replace('\\', "/")
        .replace('-', "_");
    u.starts_with("HP_") || u.contains("/HP_") || u.contains("HEAT_PUMP") || u.contains("HEATPUMP")
}

pub fn matches_family_typed(
    family: PlantFamily,
    equipment_id: &str,
    stamped_type: Option<&str>,
) -> bool {
    let kind = open_fdd_edge_prototype::equipment_types::kind_for(equipment_id, stamped_type);
    match family {
        PlantFamily::Ahu => kind == "ahu",
        PlantFamily::Chiller => kind == "chiller" && !is_heat_pump_id(equipment_id),
        PlantFamily::CoolingTower => kind == "cooling_tower",
        PlantFamily::Boiler => kind == "boiler",
        PlantFamily::HeatPump => kind == "heatpump" || is_heat_pump_id(equipment_id),
    }
}

#[cfg(test)]
pub fn matches_family(family: PlantFamily, equipment_id: &str) -> bool {
    matches_family_typed(family, equipment_id, None)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Flag {
    True,
    False,
    Unknown,
}
impl Flag {
    fn to_json(self) -> Value {
        match self {
            Flag::True => json!(true),
            Flag::False => json!(false),
            Flag::Unknown => Value::Null,
        }
    }
}

fn interpret_status(status: &str, hours: f64) -> Flag {
    if status.eq_ignore_ascii_case("NOT_APPLICABLE_EQUIPMENT_TYPE") {
        return Flag::Unknown;
    }
    let up = status.to_ascii_uppercase();
    if up.contains("SKIPPED") {
        return Flag::Unknown;
    }
    if up == "FAULT" || hours > 0.0 {
        return Flag::True;
    }
    if up == "PASS" {
        return Flag::False;
    }
    Flag::Unknown
}

type FddIndex = HashMap<String, HashMap<String, (String, f64)>>;

fn fdd_index(building_id: &str) -> (bool, FddIndex) {
    let body = open_fdd_edge_prototype::fdd::registry_api::results_response(Some(building_id));
    let rows = body
        .get("results")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if rows.is_empty() {
        return (false, HashMap::new());
    }
    let mut map: FddIndex = HashMap::new();
    for row in rows {
        let rid = row.get("rule_id").and_then(Value::as_str).unwrap_or("");
        let eq = row
            .get("equipment_id")
            .and_then(Value::as_str)
            .unwrap_or("");
        if rid.is_empty() || eq.is_empty() {
            continue;
        }
        let status = row
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let hours = row
            .get("fault_hours")
            .and_then(Value::as_f64)
            .unwrap_or(0.0);
        map.entry(eq.to_string())
            .or_default()
            .insert(rid.to_string(), (status, hours));
    }
    (true, map)
}

fn lookup_flag_with_hours(
    has_fdd: bool,
    index: &FddIndex,
    eq: &str,
    flag: FlagSpec,
) -> (Flag, f64) {
    if !has_fdd {
        return (Flag::Unknown, 0.0);
    }
    let Some(rules) = index.get(eq) else {
        return (Flag::Unknown, 0.0);
    };
    if let Some((status, hours)) = rules.get(flag.primary) {
        if status.eq_ignore_ascii_case("NOT_APPLICABLE_EQUIPMENT_TYPE") {
            if let Some(fallback) = flag.fallback {
                if let Some((fallback_status, fallback_hours)) = rules.get(fallback) {
                    let interpreted = interpret_status(fallback_status, *fallback_hours);
                    return (
                        interpreted,
                        if interpreted == Flag::Unknown {
                            0.0
                        } else {
                            *fallback_hours
                        },
                    );
                }
            }
            return (Flag::Unknown, 0.0);
        }
        let interpreted = interpret_status(status, *hours);
        return (
            interpreted,
            if interpreted == Flag::Unknown {
                0.0
            } else {
                *hours
            },
        );
    }
    if let Some(fallback) = flag.fallback {
        if let Some((status, hours)) = rules.get(fallback) {
            let interpreted = interpret_status(status, *hours);
            return (
                interpreted,
                if interpreted == Flag::Unknown {
                    0.0
                } else {
                    *hours
                },
            );
        }
    }
    (Flag::Unknown, 0.0)
}

fn score_label(flags: &[Flag]) -> (String, usize, usize) {
    let total = flags.len();
    let evaluable = flags.iter().filter(|flag| **flag != Flag::Unknown).count();
    let hit = flags.iter().filter(|flag| **flag == Flag::True).count();
    let label = if evaluable < total {
        format!("?/{total}")
    } else {
        format!("{hit}/{total}")
    };
    (label, hit, evaluable)
}

fn spec_rule_ids(spec: &MatrixSpec) -> BTreeSet<&'static str> {
    let mut ids = BTreeSet::new();
    for flag in spec.flags {
        ids.insert(flag.primary);
        if let Some(fallback) = flag.fallback {
            ids.insert(fallback);
        }
    }
    ids
}

async fn equipment_ids_for_spec(
    bid: &str,
    spec: &MatrixSpec,
    index: &FddIndex,
) -> Result<Vec<String>> {
    match spec.scope {
        EquipmentScope::AnyFdd => {
            let rule_ids = spec_rule_ids(spec);
            let mut ids: Vec<String> = index
                .iter()
                .filter_map(|(eq, rules)| {
                    rules
                        .keys()
                        .any(|rule| rule_ids.contains(rule.as_str()))
                        .then(|| eq.clone())
                })
                .collect();
            ids.sort();
            ids.dedup();
            Ok(ids)
        }
        EquipmentScope::Family(_) => {
            let ctx = SessionContext::new();
            if !try_register_history_scoped(&ctx, Some(bid)).await? {
                return Ok(Vec::new());
            }
            let result = run_sql(
                &ctx,
                "SELECT equipment_id FROM history GROUP BY equipment_id ORDER BY equipment_id",
            )
            .await?;
            Ok(result
                .rows
                .into_iter()
                .filter_map(|row| {
                    row.get("equipment_id")
                        .and_then(Value::as_str)
                        .map(str::to_string)
                })
                .collect())
        }
    }
}

async fn matrix_from_history_or_fdd(
    building_id: Option<&str>,
    spec: &MatrixSpec,
) -> Result<AnalyticsEnvelope> {
    let Some(bid) = building_id.map(str::trim).filter(|s| !s.is_empty()) else {
        let q = AnalyticsQuery::default();
        let mut env = envelope_with_engine(
            spec.query_version,
            &q,
            vec!["building_id is required — refusing mixed-site query".into()],
            DF_ENGINE,
        );
        env.coverage = Some(json!({"schema_version": spec.schema, "flag_count": spec.flags.len()}));
        return Ok(env);
    };

    let query = AnalyticsQuery {
        building_id: Some(bid.to_string()),
        ..Default::default()
    };
    let mut env = envelope_with_engine(spec.query_version, &query, vec![], DF_ENGINE);
    let (has_fdd, index) = fdd_index(bid);
    let stamped_types = open_fdd_edge_prototype::equipment_types::load_type_map(
        &super::historian::parquet_root(),
        Some(bid),
    );
    let equipment_ids = equipment_ids_for_spec(bid, spec, &index).await?;
    let mut score_counts: BTreeMap<String, u32> = BTreeMap::new();
    let mut matched = 0usize;

    for eq in equipment_ids {
        let stamped_type = stamped_types.get(&eq).map(String::as_str);
        if let EquipmentScope::Family(family) = spec.scope {
            if !matches_family_typed(family, &eq, stamped_type) {
                continue;
            }
        }
        matched += 1;

        let mut flags = Vec::with_capacity(spec.flags.len());
        let mut hours = Vec::with_capacity(spec.flags.len());
        for flag_spec in spec.flags {
            let (flag, fault_h) = lookup_flag_with_hours(has_fdd, &index, &eq, *flag_spec);
            flags.push(flag);
            hours.push(fault_h);
        }
        let (score, hit, evaluable) = score_label(&flags);
        if spec.faults_only && hit == 0 {
            continue;
        }
        *score_counts.entry(score.clone()).or_default() += 1;

        let mut row = Map::new();
        row.insert("building_id".into(), json!(bid));
        row.insert("equipment_id".into(), json!(eq));
        row.insert(
            "equipment_type".into(),
            json!(
                open_fdd_edge_prototype::equipment_types::api_equipment_type_for(&eq, stamped_type)
            ),
        );
        row.insert("score_label".into(), json!(score));
        row.insert("dimensions_hit".into(), json!(hit));
        row.insert("dimensions_evaluable".into(), json!(evaluable));
        row.insert("dimensions_total".into(), json!(spec.flags.len()));
        row.insert(
            "confidence".into(),
            json!(if evaluable < spec.flags.len() {
                "insufficient"
            } else {
                "medium"
            }),
        );
        row.insert("engine".into(), json!(DF_ENGINE));
        row.insert("schema_version".into(), json!(spec.schema));
        row.insert(
            "notes".into(),
            json!(if has_fdd {
                spec.notes
            } else {
                "flags unknown until Run all rules joins FDD results"
            }),
        );

        let mut broken = Vec::new();
        let mut flag_rules = Map::new();
        let mut total_fault_h = 0.0;
        for (idx, flag_spec) in spec.flags.iter().enumerate() {
            row.insert(flag_spec.key.to_string(), flags[idx].to_json());
            row.insert(
                format!("{}_fault_h", flag_spec.key),
                if flags[idx] == Flag::Unknown {
                    Value::Null
                } else {
                    json!(hours[idx])
                },
            );
            flag_rules.insert(flag_spec.key.to_string(), json!({"label": flag_spec.label, "rule_id": flag_spec.primary, "fallback_rule_id": flag_spec.fallback}));
            if flags[idx] == Flag::True {
                broken.push(flag_spec.primary.to_string());
                total_fault_h += hours[idx];
            }
        }
        row.insert("total_fault_h".into(), json!(total_fault_h));
        row.insert("broken_rule_ids".into(), json!(broken.join(";")));
        row.insert("flag_rules".into(), Value::Object(flag_rules));
        if let Some(flag) = spec.flags.first() {
            row.insert("flag_a_rule".into(), json!(flag.primary));
        }
        if let Some(flag) = spec.flags.get(1) {
            row.insert("flag_b_rule".into(), json!(flag.primary));
        }
        if let Some(flag) = spec.flags.get(2) {
            row.insert("flag_c_rule".into(), json!(flag.primary));
        }
        env.rows.push(Value::Object(row));
    }

    env.coverage = Some(json!({
        "schema_version": spec.schema,
        "building_id": bid,
        "flag_count": spec.flags.len(),
        "matched_equipment_count": matched,
        "row_count": env.rows.len(),
        "score_counts": score_counts,
        "rule_ids": spec_rule_ids(spec).into_iter().collect::<Vec<_>>(),
        "faults_only": spec.faults_only,
    }));
    if !has_fdd {
        env.warnings
            .push("Run all rules to populate health flags from FDD results".into());
    }
    if matched == 0 && matches!(spec.scope, EquipmentScope::Family(_)) {
        env.warnings
            .push("no matching equipment rows in historian".into());
    }
    Ok(env)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn arbitrary_length_score_is_n_over_m() {
        let (label, hit, evaluable) =
            score_label(&[Flag::True, Flag::False, Flag::True, Flag::False, Flag::True]);
        assert_eq!(label, "3/5");
        assert_eq!(hit, 3);
        assert_eq!(evaluable, 5);
        let (label, _, evaluable) =
            score_label(&[Flag::True, Flag::Unknown, Flag::False, Flag::False]);
        assert_eq!(label, "?/4");
        assert_eq!(evaluable, 3);
    }

    #[test]
    fn matrix_specs_have_requested_cardinality() {
        assert_eq!(AHU_TEMPERATURE_SPEC.flags.len(), 5);
        assert_eq!(AHU_PRESSURE_SPEC.flags.len(), 4);
        assert_eq!(AHU_ECONOMIZER_SPEC.flags.len(), 7);
        assert_eq!(CHILLER_SPEC.flags.len(), 6);
        assert_eq!(COOLING_TOWER_SPEC.flags.len(), 3);
        assert_eq!(SENSOR_SPEC.flags.len(), 5);
        assert_eq!(PID_SPEC.flags.len(), 2);
    }

    #[test]
    fn heat_pump_ids_are_not_chillers_and_towers_are_separate() {
        assert!(matches_family(PlantFamily::HeatPump, "HP_3"));
        assert!(!matches_family(PlantFamily::Chiller, "HP_3"));
        assert!(matches_family(PlantFamily::Chiller, "CHLR_1"));
        assert!(matches_family(PlantFamily::CoolingTower, "TOWER_1"));
        assert!(!matches_family(PlantFamily::Chiller, "TOWER_1"));
        assert!(matches_family_typed(PlantFamily::Ahu, "AC_1", Some("ahu")));
        assert!(matches_family_typed(
            PlantFamily::CoolingTower,
            "CT_opaque",
            Some("coolingTower")
        ));
    }

    #[test]
    fn status_interpretation_preserves_fault_hours_semantics() {
        assert_eq!(
            interpret_status("NOT_APPLICABLE_EQUIPMENT_TYPE", 0.0),
            Flag::Unknown
        );
        assert_eq!(
            interpret_status("SKIPPED_MISSING_ROLES", 0.0),
            Flag::Unknown
        );
        assert_eq!(interpret_status("PASS", 0.0), Flag::False);
        assert_eq!(interpret_status("FAULT", 0.0), Flag::True);
        assert_eq!(interpret_status("PASS", 1.5), Flag::True);
    }

    #[test]
    fn fallback_rule_preserves_hours() {
        let mut index: FddIndex = HashMap::new();
        let mut rules = HashMap::new();
        rules.insert(
            "ECON-1".into(),
            ("NOT_APPLICABLE_EQUIPMENT_TYPE".into(), 0.0),
        );
        rules.insert("ECON-2".into(), ("FAULT".into(), 2.0));
        index.insert("AHU_1".into(), rules);
        let (flag, hours) = lookup_flag_with_hours(true, &index, "AHU_1", AHU_LEGACY_FLAGS[2]);
        assert_eq!(flag, Flag::True);
        assert_eq!(hours, 2.0);
    }

    #[test]
    fn sensor_spec_is_faults_only_for_clean_rows_empty_contract() {
        assert!(SENSOR_SPEC.faults_only);
    }
}
