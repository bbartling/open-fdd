//! Canonical FDD result status contract (six statuses).

use serde::{Deserialize, Serialize};

/// Exact production status strings — keep in sync with API, UI, exports, and docs.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum RuleStatus {
    Pass,
    Fault,
    SkippedMissingRoles,
    SkippedEquipmentOff,
    NotApplicableEquipmentType,
    Error,
}

impl RuleStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Pass => "PASS",
            Self::Fault => "FAULT",
            Self::SkippedMissingRoles => "SKIPPED_MISSING_ROLES",
            Self::SkippedEquipmentOff => "SKIPPED_EQUIPMENT_OFF",
            Self::NotApplicableEquipmentType => "NOT_APPLICABLE_EQUIPMENT_TYPE",
            Self::Error => "ERROR",
        }
    }

    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "PASS" => Some(Self::Pass),
            "FAULT" => Some(Self::Fault),
            "SKIPPED_MISSING_ROLES" => Some(Self::SkippedMissingRoles),
            "SKIPPED_EQUIPMENT_OFF" => Some(Self::SkippedEquipmentOff),
            "NOT_APPLICABLE_EQUIPMENT_TYPE" => Some(Self::NotApplicableEquipmentType),
            "ERROR" => Some(Self::Error),
            _ => None,
        }
    }

    /// Aggregate equipment-level statuses into one rule-level summary.
    /// Priority: ERROR > FAULT > PASS > SKIPPED_EQUIPMENT_OFF > SKIPPED_MISSING_ROLES > N/A.
    pub fn aggregate(statuses: &[Self]) -> Self {
        if statuses.is_empty() {
            return Self::NotApplicableEquipmentType;
        }
        if statuses.contains(&Self::Error) {
            return Self::Error;
        }
        if statuses.contains(&Self::Fault) {
            return Self::Fault;
        }
        if statuses.contains(&Self::Pass) {
            return Self::Pass;
        }
        if statuses.contains(&Self::SkippedEquipmentOff) {
            return Self::SkippedEquipmentOff;
        }
        if statuses.contains(&Self::SkippedMissingRoles) {
            return Self::SkippedMissingRoles;
        }
        Self::NotApplicableEquipmentType
    }
}

impl std::fmt::Display for RuleStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Infer a coarse HVAC equipment class from historian `equipment_id`.
pub fn infer_equipment_type(equipment_id: &str) -> String {
    let id = equipment_id.to_ascii_uppercase();
    let id = id.trim();
    if id.starts_with("AHU") || id.contains("_AHU") {
        return "AHU".into();
    }
    if id.starts_with("VAV") || id.contains("_VAV") {
        return "VAV".into();
    }
    if id.starts_with("CHILLER") || id.starts_with("CHW") || id.contains("CHILLER") {
        return "CHW".into();
    }
    if id.starts_with("BOILER") || id.starts_with("HW") || id.contains("BOILER") {
        return "HW".into();
    }
    if id.starts_with("HP") || id.contains("HEAT_PUMP") || id.contains("HEATPUMP") {
        return "HP".into();
    }
    if id.starts_with("CT") || id.contains("COOLING_TOWER") {
        return "CT".into();
    }
    if id.starts_with("PUMP") || id.contains("PUMPS") {
        return "PUMP".into();
    }
    if id == "WEATHER" || id.starts_with("WX") || id.starts_with("OAT") {
        return "WEATHER".into();
    }
    if id.starts_with("METER") {
        return "METER".into();
    }
    "GENERIC".into()
}

/// Default equipment applicability when registry omits `equipment_types`.
pub fn default_equipment_types_for_rule(rule_id: &str) -> Vec<String> {
    let id = rule_id.to_ascii_uppercase();
    if id.starts_with("VAV-") || id == "VAV-REHEAT-STUCK" {
        return vec!["VAV".into()];
    }
    if id.starts_with("CHW-") {
        return vec!["CHW".into()];
    }
    if id.starts_with("HP-") {
        return vec!["HP".into()];
    }
    if id.starts_with("TRIM-3") {
        return vec!["HW".into(), "AHU".into(), "GENERIC".into()];
    }
    if id.starts_with("TRIM-4") {
        return vec!["CHW".into(), "AHU".into(), "GENERIC".into()];
    }
    if matches!(
        id.as_str(),
        "WX-1"
            | "WX-2"
            | "OAT-METEO"
            | "SV-RANGE"
            | "SV-FLATLINE"
            | "SV-SPIKE"
            | "SV-STALE"
            | "PID-HUNT-1"
            | "SCHED-1"
            | "CMD-1"
            | "FAN-RUNTIME-HOURS"
            | "AVG-ZONE-TEMP"
            | "ZONE-COMFORT-PCT"
            | "FAULT-ELAPSED-HOURS"
    ) {
        return vec!["ANY".into()];
    }
    // FC*, ECON*, OA-1, DMP-1, AHU-*, SV-4, TRIM-1, VLV-1 → AHU family
    if id.starts_with("FC")
        || id.starts_with("ECON")
        || id.starts_with("AHU-")
        || id == "OA-1"
        || id == "DMP-1"
        || id == "SV-4"
        || id == "TRIM-1"
        || id == "VLV-1"
    {
        return vec!["AHU".into()];
    }
    vec!["ANY".into()]
}

pub fn equipment_is_applicable(rule_types: &[String], equipment_type: &str) -> bool {
    if rule_types.is_empty() {
        return true;
    }
    rule_types.iter().any(|t| {
        let t = t.to_ascii_uppercase();
        t == "ANY" || t == equipment_type.to_ascii_uppercase()
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn status_strings_are_canonical() {
        assert_eq!(RuleStatus::Pass.as_str(), "PASS");
        assert_eq!(RuleStatus::Fault.as_str(), "FAULT");
        assert_eq!(
            RuleStatus::SkippedMissingRoles.as_str(),
            "SKIPPED_MISSING_ROLES"
        );
        assert_eq!(
            RuleStatus::SkippedEquipmentOff.as_str(),
            "SKIPPED_EQUIPMENT_OFF"
        );
        assert_eq!(
            RuleStatus::NotApplicableEquipmentType.as_str(),
            "NOT_APPLICABLE_EQUIPMENT_TYPE"
        );
        assert_eq!(RuleStatus::Error.as_str(), "ERROR");
    }

    #[test]
    fn aggregate_priority() {
        assert_eq!(
            RuleStatus::aggregate(&[RuleStatus::Pass, RuleStatus::Fault]),
            RuleStatus::Fault
        );
        assert_eq!(
            RuleStatus::aggregate(&[RuleStatus::SkippedEquipmentOff, RuleStatus::Pass]),
            RuleStatus::Pass
        );
        assert_eq!(
            RuleStatus::aggregate(&[
                RuleStatus::NotApplicableEquipmentType,
                RuleStatus::SkippedEquipmentOff
            ]),
            RuleStatus::SkippedEquipmentOff
        );
        assert_eq!(
            RuleStatus::aggregate(&[RuleStatus::NotApplicableEquipmentType]),
            RuleStatus::NotApplicableEquipmentType
        );
    }

    #[test]
    fn infer_types() {
        assert_eq!(infer_equipment_type("AHU_1"), "AHU");
        assert_eq!(infer_equipment_type("VAVFC_100"), "VAV");
        assert_eq!(infer_equipment_type("CHILLER_1"), "CHW");
        assert_eq!(infer_equipment_type("BOILERS_PUMPS"), "HW");
    }

    #[test]
    fn applicability() {
        assert!(equipment_is_applicable(&["ANY".into()], "VAV"));
        assert!(equipment_is_applicable(&["AHU".into()], "AHU"));
        assert!(!equipment_is_applicable(&["AHU".into()], "VAV"));
        assert!(equipment_is_applicable(
            &default_equipment_types_for_rule("FC8"),
            "AHU"
        ));
        assert!(!equipment_is_applicable(
            &default_equipment_types_for_rule("FC8"),
            "VAV"
        ));
        assert!(equipment_is_applicable(
            &default_equipment_types_for_rule("VAV-1"),
            "VAV"
        ));
    }
}
