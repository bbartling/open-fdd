//! Plant health matrices (AHU / chiller / boiler / HP) — three named FDD flags.
//! Missing evidence is unknown, not PASS. Score `n/3` like VAV.

use std::collections::HashMap;

use anyhow::Result;
use datafusion::prelude::SessionContext;
use fdd_sql::run_sql;
use serde_json::{json, Value};

use super::historian::{plant_group_for, try_register_history_scoped};
use super::{envelope_with_engine, AnalyticsEnvelope, AnalyticsQuery, AnalyticsRequest, DF_ENGINE};

pub const QV_AHU_HEALTH: &str = "ahu-health-v1";
pub const QV_CHILLER_HEALTH: &str = "chiller-health-v1";
pub const QV_BOILER_HEALTH: &str = "boiler-health-v1";
pub const QV_HP_HEALTH: &str = "hp-health-v1";

pub const SCHEMA_AHU_HEALTH: &str = "ahu_health_matrix_v1";
pub const SCHEMA_CHILLER_HEALTH: &str = "chiller_health_matrix_v1";
pub const SCHEMA_BOILER_HEALTH: &str = "boiler_health_matrix_v1";
pub const SCHEMA_HP_HEALTH: &str = "hp_health_matrix_v1";

/// Same style as VAV `BROKEN_RULE_IDS` (VAV-3/4/5/7). Missing evidence = unknown, not PASS.
pub const AHU_BROKEN_RULE_IDS: &[&str] = &["AHU-SATDEV", "AHU-DUCTHI", "ECON-1"];
pub const CHILLER_BROKEN_RULE_IDS: &[&str] = &["CHW-1", "CHW-2", "CHW-3"];
/// No HW-* SQL today — heating cookbook flags. Skip `NOT_APPLICABLE_EQUIPMENT_TYPE`.
pub const BOILER_BROKEN_RULE_IDS: &[&str] = &["FC5", "FC6", "FC8"];
pub const HP_BROKEN_RULE_IDS: &[&str] = &["HP-1", "AHU-SATDEV", "ECON-1"];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PlantFamily {
    Ahu,
    Chiller,
    Boiler,
    HeatPump,
}

struct FamilySpec {
    family: PlantFamily,
    query_version: &'static str,
    schema: &'static str,
    /// (row key, header label, primary rule, optional fallback rule)
    flags: [(
        &'static str,
        &'static str,
        &'static str,
        Option<&'static str>,
    ); 3],
    broken: &'static [&'static str],
    notes: &'static str,
}

const AHU_SPEC: FamilySpec = FamilySpec {
    family: PlantFamily::Ahu,
    query_version: QV_AHU_HEALTH,
    schema: SCHEMA_AHU_HEALTH,
    flags: [
        ("sat_dev", "SAT", "AHU-SATDEV", None),
        ("duct_high", "Duct", "AHU-DUCTHI", None),
        ("economizer", "Econ", "ECON-1", Some("ECON-2")),
    ],
    broken: AHU_BROKEN_RULE_IDS,
    notes: "AHU-SATDEV / AHU-DUCTHI / ECON-1 (ECON-2 if ECON-1 is N/A)",
};

const CHILLER_SPEC: FamilySpec = FamilySpec {
    family: PlantFamily::Chiller,
    query_version: QV_CHILLER_HEALTH,
    schema: SCHEMA_CHILLER_HEALTH,
    flags: [
        ("chw_1", "CHW-1", "CHW-1", None),
        ("chw_2", "CHW-2", "CHW-2", None),
        ("chw_3", "CHW-3", "CHW-3", None),
    ],
    broken: CHILLER_BROKEN_RULE_IDS,
    notes: "CHW-1 / CHW-2 / CHW-3 compressor-plant flags",
};

const BOILER_SPEC: FamilySpec = FamilySpec {
    family: PlantFamily::Boiler,
    query_version: QV_BOILER_HEALTH,
    schema: SCHEMA_BOILER_HEALTH,
    flags: [
        ("fc5", "FC5", "FC5", None),
        ("fc6", "FC6", "FC6", None),
        ("fc8", "FC8", "FC8", None),
    ],
    broken: BOILER_BROKEN_RULE_IDS,
    notes: "FC5 / FC6 / FC8 heating cookbook (no HW-* SQL). N/A skipped.",
};

const HP_SPEC: FamilySpec = FamilySpec {
    family: PlantFamily::HeatPump,
    query_version: QV_HP_HEALTH,
    schema: SCHEMA_HP_HEALTH,
    flags: [
        ("hp_1", "HP-1", "HP-1", None),
        ("sat_dev", "SAT", "AHU-SATDEV", None),
        ("economizer", "Econ", "ECON-1", Some("ECON-2")),
    ],
    broken: HP_BROKEN_RULE_IDS,
    notes: "HP-1 plus AHU-SATDEV / ECON-1 when id is HP_*",
};

pub async fn handle_ahu(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    handle_family(req, &AHU_SPEC).await
}
pub async fn handle_chiller(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    handle_family(req, &CHILLER_SPEC).await
}
pub async fn handle_boiler(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    handle_family(req, &BOILER_SPEC).await
}
pub async fn handle_hp(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    handle_family(req, &HP_SPEC).await
}

async fn handle_family(req: &AnalyticsRequest, spec: &FamilySpec) -> AnalyticsEnvelope {
    match plant_health_from_history(req.query.building_id.as_deref(), spec).await {
        Ok(Some(env)) => env,
        Ok(None) => {
            let mut env = envelope_with_engine(
                spec.query_version,
                &req.query,
                vec!["plant-health unavailable".into()],
                DF_ENGINE,
            );
            env.coverage = Some(json!({"schema_version": spec.schema}));
            env
        }
        Err(e) => {
            let mut env = envelope_with_engine(
                spec.query_version,
                &req.query,
                vec![format!("plant-health failed: {e}")],
                DF_ENGINE,
            );
            env.coverage = Some(json!({"schema_version": spec.schema}));
            env
        }
    }
}

/// Heat-pump ids stay out of the chiller matrix (`plant_group_for("HP_3")` is `"chiller"`).
pub fn is_heat_pump_id(equipment_id: &str) -> bool {
    let u = equipment_id
        .to_ascii_uppercase()
        .replace('\\', "/")
        .replace('-', "_");
    u.starts_with("HP_") || u.contains("/HP_") || u.contains("HEAT_PUMP") || u.contains("HEATPUMP")
}

pub fn matches_family(family: PlantFamily, equipment_id: &str) -> bool {
    match family {
        PlantFamily::Ahu => plant_group_for(equipment_id) == Some("air"),
        PlantFamily::Chiller => {
            plant_group_for(equipment_id) == Some("chiller") && !is_heat_pump_id(equipment_id)
        }
        PlantFamily::Boiler => plant_group_for(equipment_id) == Some("boiler"),
        PlantFamily::HeatPump => is_heat_pump_id(equipment_id),
    }
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
    if up.eq("FAULT") || hours > 0.0 {
        return Flag::True;
    }
    if up.eq("PASS") {
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
        if rid.is_empty() {
            continue;
        }
        let eq = row
            .get("equipment_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        if eq.is_empty() {
            continue;
        }
        let st = row
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let hours = row
            .get("fault_hours")
            .and_then(Value::as_f64)
            .unwrap_or(0.0);
        map.entry(eq)
            .or_default()
            .insert(rid.to_string(), (st, hours));
    }
    (true, map)
}

fn lookup_flag_with_hours(
    has_fdd: bool,
    index: &FddIndex,
    eq: &str,
    primary: &str,
    fallback: Option<&str>,
) -> (Flag, f64) {
    if !has_fdd {
        return (Flag::Unknown, 0.0);
    }
    let Some(rules) = index.get(eq) else {
        return (Flag::Unknown, 0.0);
    };
    if let Some((st, hours)) = rules.get(primary) {
        if st.eq_ignore_ascii_case("NOT_APPLICABLE_EQUIPMENT_TYPE") {
            if let Some(fb) = fallback {
                if let Some((fst, fh)) = rules.get(fb) {
                    let flag = interpret_status(fst, *fh);
                    return (flag, if flag == Flag::Unknown { 0.0 } else { *fh });
                }
            }
            return (Flag::Unknown, 0.0);
        }
        let flag = interpret_status(st, *hours);
        return (flag, if flag == Flag::Unknown { 0.0 } else { *hours });
    }
    if let Some(fb) = fallback {
        if let Some((fst, fh)) = rules.get(fb) {
            let flag = interpret_status(fst, *fh);
            return (flag, if flag == Flag::Unknown { 0.0 } else { *fh });
        }
    }
    (Flag::Unknown, 0.0)
}

fn score_label(
    flags: [Flag; 3],
    n3: &mut u32,
    n2: &mut u32,
    n1: &mut u32,
    n0: &mut u32,
    nq: &mut u32,
) -> (String, usize, usize) {
    let evaluable = flags.iter().filter(|f| **f != Flag::Unknown).count();
    let hit = flags.iter().filter(|f| **f == Flag::True).count();
    let label = if evaluable < 3 {
        *nq += 1;
        "?/3"
    } else if hit == 3 {
        *n3 += 1;
        "3/3"
    } else if hit == 2 {
        *n2 += 1;
        "2/3"
    } else if hit == 1 {
        *n1 += 1;
        "1/3"
    } else {
        *n0 += 1;
        "0/3"
    };
    (label.to_string(), hit, evaluable)
}

async fn plant_health_from_history(
    building_id: Option<&str>,
    spec: &FamilySpec,
) -> Result<Option<AnalyticsEnvelope>> {
    let Some(bid) = building_id.map(str::trim).filter(|s| !s.is_empty()) else {
        let q = AnalyticsQuery {
            building_id: None,
            ..Default::default()
        };
        let mut env = envelope_with_engine(
            spec.query_version,
            &q,
            vec!["building_id is required — refusing mixed-site query".into()],
            DF_ENGINE,
        );
        env.coverage = Some(json!({"schema_version": spec.schema}));
        return Ok(Some(env));
    };
    let ctx = SessionContext::new();
    if !try_register_history_scoped(&ctx, Some(bid)).await? {
        let q = AnalyticsQuery {
            building_id: Some(bid.to_string()),
            ..Default::default()
        };
        let mut env = envelope_with_engine(
            spec.query_version,
            &q,
            vec![
                "no historian parquet for this building — run ingest then Update analytics".into(),
            ],
            DF_ENGINE,
        );
        env.coverage = Some(json!({"schema_version": spec.schema, "building_id": bid}));
        return Ok(Some(env));
    }
    let sql = "SELECT equipment_id FROM history GROUP BY equipment_id ORDER BY equipment_id";
    let result = match run_sql(&ctx, sql).await {
        Ok(r) => r,
        Err(e) => {
            let q = AnalyticsQuery {
                building_id: Some(bid.to_string()),
                ..Default::default()
            };
            let mut env = envelope_with_engine(
                spec.query_version,
                &q,
                vec![format!("plant-health query failed: {e}")],
                DF_ENGINE,
            );
            env.coverage = Some(json!({"schema_version": spec.schema}));
            return Ok(Some(env));
        }
    };
    let q = AnalyticsQuery {
        building_id: Some(bid.to_string()),
        ..Default::default()
    };
    let mut env = envelope_with_engine(spec.query_version, &q, vec![], DF_ENGINE);
    let mut n3 = 0u32;
    let mut n2 = 0u32;
    let mut n1 = 0u32;
    let mut n0 = 0u32;
    let mut nq = 0u32;
    let (has_fdd, index) = fdd_index(bid);
    let mut seen = 0u32;
    for row in result.rows {
        let eq = row
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if eq.is_empty() || !matches_family(spec.family, eq) {
            continue;
        }
        seen += 1;
        let (f0, h0) =
            lookup_flag_with_hours(has_fdd, &index, eq, spec.flags[0].2, spec.flags[0].3);
        let (f1, h1) =
            lookup_flag_with_hours(has_fdd, &index, eq, spec.flags[1].2, spec.flags[1].3);
        let (f2, h2) =
            lookup_flag_with_hours(has_fdd, &index, eq, spec.flags[2].2, spec.flags[2].3);
        let flags = [f0, f1, f2];
        let hours = [h0, h1, h2];
        let (label, hit, evaluable) =
            score_label(flags, &mut n3, &mut n2, &mut n1, &mut n0, &mut nq);
        let mut broken_ids: Vec<String> = Vec::new();
        for (i, f) in flags.iter().enumerate() {
            if *f == Flag::True {
                broken_ids.push(spec.flags[i].2.to_string());
            }
        }
        let eq_type = match spec.family {
            PlantFamily::Ahu => "AHU",
            PlantFamily::Chiller => "CHILLER",
            PlantFamily::Boiler => "BOILER",
            PlantFamily::HeatPump => "HEAT_PUMP",
        };
        let mut obj = serde_json::Map::new();
        obj.insert("building_id".into(), json!(bid));
        obj.insert("equipment_id".into(), json!(eq));
        obj.insert("equipment_type".into(), json!(eq_type));
        obj.insert(spec.flags[0].0.to_string(), flags[0].to_json());
        obj.insert(spec.flags[1].0.to_string(), flags[1].to_json());
        obj.insert(spec.flags[2].0.to_string(), flags[2].to_json());
        obj.insert(
            format!("{}_fault_h", spec.flags[0].0),
            json!(if flags[0] == Flag::Unknown {
                Value::Null
            } else {
                json!(hours[0])
            }),
        );
        obj.insert(
            format!("{}_fault_h", spec.flags[1].0),
            json!(if flags[1] == Flag::Unknown {
                Value::Null
            } else {
                json!(hours[1])
            }),
        );
        obj.insert(
            format!("{}_fault_h", spec.flags[2].0),
            json!(if flags[2] == Flag::Unknown {
                Value::Null
            } else {
                json!(hours[2])
            }),
        );
        let total_fault_h: f64 = flags
            .iter()
            .zip(hours.iter())
            .filter(|(f, _)| **f == Flag::True)
            .map(|(_, h)| *h)
            .sum();
        obj.insert("total_fault_h".into(), json!(total_fault_h));
        obj.insert("flag_a_rule".into(), json!(spec.flags[0].2));
        obj.insert("flag_b_rule".into(), json!(spec.flags[1].2));
        obj.insert("flag_c_rule".into(), json!(spec.flags[2].2));
        obj.insert("dimensions_hit".into(), json!(hit));
        obj.insert("dimensions_evaluable".into(), json!(evaluable));
        obj.insert("score_label".into(), json!(label));
        obj.insert("broken_rule_ids".into(), json!(broken_ids.join(";")));
        obj.insert(
            "confidence".into(),
            json!(if evaluable < 3 {
                "insufficient"
            } else {
                "medium"
            }),
        );
        obj.insert("engine".into(), json!(DF_ENGINE));
        obj.insert("schema_version".into(), json!(spec.schema));
        obj.insert(
            "notes".into(),
            json!(if has_fdd {
                spec.notes
            } else {
                "flags unknown until Run all rules joins FDD results"
            }),
        );
        env.rows.push(Value::Object(obj));
    }
    env.coverage = Some(json!({
        "schema_version": spec.schema,
        "building_id": bid,
        "family": format!("{:?}", spec.family).to_ascii_lowercase(),
        "broken_rule_ids": spec.broken,
        "groups": {
            "3/3": n3, "2/3": n2, "1/3": n1, "0/3": n0, "?/3": nq
        }
    }));
    if seen == 0 {
        env.warnings.push(format!(
            "no {:?} equipment_id rows in historian",
            spec.family
        ));
    }
    if !has_fdd {
        env.warnings
            .push("Run all rules to populate plant health flags from FDD results".into());
    }
    Ok(Some(env))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn broken_rule_ids_match_family_specs() {
        assert_eq!(
            AHU_SPEC.flags.map(|f| f.2).to_vec(),
            AHU_BROKEN_RULE_IDS.to_vec()
        );
        assert_eq!(
            CHILLER_SPEC.flags.map(|f| f.2).to_vec(),
            CHILLER_BROKEN_RULE_IDS.to_vec()
        );
        assert_eq!(
            BOILER_SPEC.flags.map(|f| f.2).to_vec(),
            BOILER_BROKEN_RULE_IDS.to_vec()
        );
        assert_eq!(
            HP_SPEC.flags.map(|f| f.2).to_vec(),
            HP_BROKEN_RULE_IDS.to_vec()
        );
    }

    #[test]
    fn heat_pump_ids_are_not_chillers() {
        assert!(is_heat_pump_id("HP_3"));
        assert!(is_heat_pump_id("HP-1"));
        assert!(matches_family(PlantFamily::HeatPump, "HP_3"));
        assert!(!matches_family(PlantFamily::Chiller, "HP_3"));
        assert!(matches_family(PlantFamily::Chiller, "CH-1"));
        assert!(matches_family(PlantFamily::Chiller, "CHLR_1"));
        assert!(matches_family(PlantFamily::Ahu, "AHU_1"));
        assert!(matches_family(PlantFamily::Ahu, "RTU_2"));
        assert!(!matches_family(PlantFamily::Ahu, "VAV_12"));
        assert!(matches_family(PlantFamily::Boiler, "BOILER_1"));
    }

    #[test]
    fn interpret_unknown_not_pass() {
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
    fn econ1_na_falls_back_to_econ2() {
        let mut index: FddIndex = HashMap::new();
        let mut rules = HashMap::new();
        rules.insert(
            "ECON-1".into(),
            ("NOT_APPLICABLE_EQUIPMENT_TYPE".into(), 0.0),
        );
        rules.insert("ECON-2".into(), ("FAULT".into(), 2.0));
        index.insert("AHU_1".into(), rules);
        assert_eq!(
            lookup_flag(true, &index, "AHU_1", "ECON-1", Some("ECON-2")),
            Flag::True
        );
    }

    #[test]
    fn missing_rule_is_unknown() {
        let mut index: FddIndex = HashMap::new();
        index.insert("AHU_1".into(), HashMap::new());
        assert_eq!(
            lookup_flag(true, &index, "AHU_1", "AHU-SATDEV", None),
            Flag::Unknown
        );
        assert_eq!(
            lookup_flag(false, &index, "AHU_1", "AHU-SATDEV", None),
            Flag::Unknown
        );
    }

    #[test]
    fn three_unknown_is_question() {
        let mut n3 = 0;
        let mut n2 = 0;
        let mut n1 = 0;
        let mut n0 = 0;
        let mut nq = 0;
        let (label, hit, evaluable) = score_label(
            [Flag::Unknown, Flag::Unknown, Flag::Unknown],
            &mut n3,
            &mut n2,
            &mut n1,
            &mut n0,
            &mut nq,
        );
        assert_eq!(label, "?/3");
        assert_eq!(hit, 0);
        assert_eq!(evaluable, 0);
        assert_eq!(nq, 1);
    }

    #[test]
    fn three_true_is_darkest() {
        let mut n3 = 0;
        let mut n2 = 0;
        let mut n1 = 0;
        let mut n0 = 0;
        let mut nq = 0;
        let (label, hit, evaluable) = score_label(
            [Flag::True, Flag::True, Flag::True],
            &mut n3,
            &mut n2,
            &mut n1,
            &mut n0,
            &mut nq,
        );
        assert_eq!(label, "3/3");
        assert_eq!(hit, 3);
        assert_eq!(evaluable, 3);
        assert_eq!(n3, 1);
    }

    #[tokio::test]
    async fn refuses_missing_building_id() {
        let env = plant_health_from_history(None, &AHU_SPEC)
            .await
            .unwrap()
            .unwrap();
        assert!(env.warnings.iter().any(|w| w.contains("building_id")));
        assert!(env.rows.is_empty());
        assert_eq!(env.query_version, QV_AHU_HEALTH);
    }
}
