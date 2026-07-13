//! Inject operational proof (+ startup delay) into rule SQL before confirmation.
//!
//! Matches Vibe19 `finalize_result(..., active_mask=...)`: raw faults only count
//! while equipment is proven operating. Rules that already embed fan/pump checks
//! remain correct under a redundant AND.

use std::collections::HashSet;

use crate::registry::RuleSpec;

/// SQL boolean/numeric expression that is > 0 when equipment is proven on.
/// Uses only columns present in `history`. Returns `None` when no proof roles
/// exist (Vibe19 ungated behavior).
pub fn operational_proof_expr(columns: &HashSet<String>, predicate: &str) -> Option<String> {
    let pred = predicate.to_ascii_lowercase();
    let mut parts: Vec<String> = Vec::new();

    let want_fan = pred.is_empty()
        || pred.contains("fan")
        || pred.contains("flow_proof")
        || pred.contains("equipment_energized")
        || pred.contains("control_loop")
        || pred == "conditional"
        || pred.contains("fan_or_flow");
    let want_hydronic = pred.contains("hydronic")
        || pred.contains("pump")
        || pred.contains("flow_proof")
        || pred.contains("fan_or_flow")
        || pred.contains("equipment_energized");
    let want_zone_flow = pred.contains("fan") || pred.contains("conditional") || pred.is_empty();

    if want_fan {
        // Prefer proof/status over command (Vibe19 resolve_fan_running order).
        if columns.contains("fan_status") {
            parts.push(
                "(CASE WHEN history.fan_status IS NULL THEN 0 \
                 WHEN TRIM(CAST(history.fan_status AS VARCHAR)) \
                   IN ('1','1.0','true','TRUE','on','ON') THEN 1 ELSE 0 END)"
                    .into(),
            );
        } else if columns.contains("fan_cmd") {
            parts.push(norm_cmd_on("history.fan_cmd"));
        }
    }
    if parts.is_empty() && want_hydronic {
        let hydronic_order = [
            "pump_status",
            "chw_pump_status",
            "hw_pump_status",
            "chw_flow",
            "water_flow",
            "pump_speed_feedback",
            "pump_current",
            "chw_pump_cmd",
            "pump_cmd",
            "hw_pump_cmd",
        ];
        for role in hydronic_order {
            if !columns.contains(role) {
                continue;
            }
            if role.contains("status") {
                parts.push(format!(
                    "(CASE WHEN history.{role} IS NULL THEN 0 \
                     WHEN TRIM(CAST(history.{role} AS VARCHAR)) \
                       IN ('1','1.0','true','TRUE','on','ON') THEN 1 ELSE 0 END)"
                ));
            } else if role.ends_with("_flow") {
                parts.push(format!(
                    "(CASE WHEN history.{role} IS NULL THEN 0 WHEN history.{role} > 0.05 THEN 1 ELSE 0 END)"
                ));
            } else {
                parts.push(norm_cmd_on(&format!("history.{role}")));
            }
            break; // first present role only
        }
    }
    if parts.is_empty() && want_zone_flow && columns.contains("zone_flow") {
        parts.push(
            "(CASE WHEN history.zone_flow IS NULL THEN 0 WHEN history.zone_flow > 50.0 THEN 1 ELSE 0 END)"
                .into(),
        );
    }

    if parts.is_empty() {
        return None;
    }
    Some(format!("({})", parts.join(" + ")))
}

fn norm_cmd_on(col: &str) -> String {
    format!(
        "(CASE WHEN {col} IS NULL THEN 0 \
         WHEN {col} > 1.0 THEN CASE WHEN {col} >= 5.0 THEN 1 ELSE 0 END \
         ELSE CASE WHEN {col} >= 0.05 THEN 1 ELSE 0 END END)"
    )
}

/// Whether this rule should gate `raw_fault` with operational proof.
///
/// Only `RUN` gates get SQL injection here. `CONDITIONAL` / sensor-sweep rules
/// need rule-specific proof (Vibe19 `resolve_conditional`) and must not be
/// blindly ANDed with fan/pump — that zeroed SV-FLATLINE Building 100 hours.
pub fn should_inject_operational_gate(rule: &RuleSpec) -> bool {
    let mode = rule.gate_mode().to_ascii_uppercase();
    mode == "RUN"
}

pub fn startup_delay_rows(rule: &RuleSpec, poll_seconds: f64) -> u32 {
    let delay = rule
        .operational_gate
        .as_ref()
        .map(|g| g.startup_delay_seconds)
        .unwrap_or(0);
    if delay == 0 {
        return 1;
    }
    ((delay as f64 / poll_seconds.max(1.0)).ceil() as u32).max(1)
}

/// Insert `gated_operational` CTE and retarget the confirm streak from `base`.
pub fn inject_raw_fault_operational_gate(
    sql: &str,
    proof_sum_expr: &str,
    startup_rows: u32,
) -> String {
    if sql.contains("gated_operational AS") {
        return sql.to_string();
    }
    if !sql.contains("raw_fault") {
        return sql.to_string();
    }
    let marker = "lagged AS (";
    let Some(pos) = sql.find(marker) else {
        return sql.to_string();
    };

    let startup = startup_rows.max(1);
    // Materialize proof_on before LAG — DataFusion rejects LAG(complex CASE).
    let cte = format!(
        "gated_operational AS (\n  \
           SELECT\n    \
             g.equipment_id,\n    \
             g.timestamp_utc,\n    \
             CASE\n      \
               WHEN g.proof_on = 1 AND g.proof_streak >= {startup} THEN g.raw_fault\n      \
               ELSE 0\n    \
             END AS raw_fault\n  \
           FROM (\n    \
             SELECT\n      \
               p.equipment_id,\n      \
               p.timestamp_utc,\n      \
               p.raw_fault,\n      \
               p.proof_on,\n      \
               CASE\n        \
                 WHEN p.proof_on = 0 THEN 0\n        \
                 ELSE SUM(p.proof_on) OVER (\n          \
                   PARTITION BY p.equipment_id, p.proof_grp\n          \
                   ORDER BY p.timestamp_utc\n          \
                   ROWS UNBOUNDED PRECEDING\n        \
                 )\n      \
               END AS proof_streak\n    \
             FROM (\n      \
               SELECT\n        \
                 s.equipment_id,\n        \
                 s.timestamp_utc,\n        \
                 s.raw_fault,\n        \
                 s.proof_on,\n        \
                 SUM(s.is_new_proof) OVER (\n          \
                   PARTITION BY s.equipment_id\n          \
                   ORDER BY s.timestamp_utc\n          \
                   ROWS UNBOUNDED PRECEDING\n        \
                 ) AS proof_grp\n      \
               FROM (\n        \
                 SELECT\n          \
                   r.equipment_id,\n          \
                   r.timestamp_utc,\n          \
                   r.raw_fault,\n          \
                   r.proof_on,\n          \
                   CASE\n            \
                     WHEN COALESCE(\n              \
                       LAG(r.proof_on) OVER (\n                \
                         PARTITION BY r.equipment_id ORDER BY r.timestamp_utc\n              \
                       ),\n              \
                       -1\n            \
                     ) <> r.proof_on THEN 1 ELSE 0\n          \
                   END AS is_new_proof\n        \
                 FROM (\n          \
                   SELECT\n            \
                     base.equipment_id,\n            \
                     base.timestamp_utc,\n            \
                     base.raw_fault,\n            \
                     CASE WHEN ({proof_sum_expr}) > 0 THEN 1 ELSE 0 END AS proof_on\n          \
                   FROM base\n          \
                   INNER JOIN history\n            \
                     ON history.equipment_id = base.equipment_id\n           \
                    AND history.timestamp_utc = base.timestamp_utc\n        \
                 ) r\n      \
               ) s\n    \
             ) p\n  \
           ) g\n\
         ),\n"
    );

    let mut out = String::with_capacity(sql.len() + cte.len() + 32);
    out.push_str(&sql[..pos]);
    out.push_str(&cte);
    out.push_str(&sql[pos..]);

    // Retarget confirm streak input (first FROM base inside lagged CTE).
    let search_from = out.find(marker).map(|i| i + marker.len()).unwrap_or(0);
    if let Some(rel) = out[search_from..].find("FROM base") {
        let abs = search_from + rel;
        out.replace_range(abs..abs + "FROM base".len(), "FROM gated_operational");
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::registry::OperationalGate;

    #[test]
    fn injects_gate_before_lagged() {
        let sql = "WITH base AS (\n  SELECT equipment_id, timestamp_utc, 1 AS raw_fault FROM history\n),\nlagged AS (\n  SELECT * FROM base\n)\nSELECT 1;";
        let out = inject_raw_fault_operational_gate(sql, "history.fan_cmd", 2);
        assert!(out.contains("gated_operational AS"));
        assert!(out.contains("FROM gated_operational"));
        assert!(out.contains("proof_streak >= 2"));
    }

    #[test]
    fn proof_expr_requires_available_columns() {
        let mut cols = HashSet::new();
        assert!(operational_proof_expr(&cols, "fan_running").is_none());
        cols.insert("fan_cmd".into());
        let expr = operational_proof_expr(&cols, "fan_running").unwrap();
        assert!(expr.contains("history.fan_cmd"));
    }

    #[test]
    fn run_gate_should_inject() {
        let rule = RuleSpec {
            rule_id: "FC8".into(),
            sql_file: "fc8.sql".into(),
            description: "t".into(),
            required_roles: vec![],
            optional_roles: vec![],
            equipment_types: vec![],
            output_columns: vec![],
            confirm_seconds: 600,
            parameters: Default::default(),
            parity_status: String::new(),
            dashboard_wired: false,
            operational_gate: Some(OperationalGate {
                mode: "RUN".into(),
                predicate: "fan_running".into(),
                required: true,
                preferred_roles: vec![],
                command_fallback_allowed: true,
                startup_delay_seconds: 600,
                minimum_active_coverage_pct: 0.0,
            }),
        };
        assert!(should_inject_operational_gate(&rule));
        assert_eq!(startup_delay_rows(&rule, 300.0), 2);
    }
}
