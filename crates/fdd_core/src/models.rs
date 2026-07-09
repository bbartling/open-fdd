use serde::{Deserialize, Serialize};

/// Poll interval derived from manifest `grid_minutes` or detected median Δt.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct PollInterval {
    pub grid_minutes: u32,
    pub effective_poll_seconds: u32,
}

impl PollInterval {
    pub fn from_grid_minutes(grid_minutes: u32) -> Self {
        Self {
            grid_minutes,
            effective_poll_seconds: grid_minutes.saturating_mul(60),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HistoryManifest {
    pub grid_minutes: u32,
    #[serde(default)]
    pub export_metadata: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PointColumn {
    pub column: String,
    #[serde(default)]
    pub point_role: Option<String>,
    #[serde(default)]
    pub point_name: Option<String>,
    #[serde(default)]
    pub units: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PointRole {
    Oat,
    Sat,
    Rat,
    Mat,
    FanCmd,
    ZoneTemp,
    Other,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EquipmentHistory {
    pub equipment_id: String,
    pub history_path: String,
    pub columns_path: String,
    pub point_count: usize,
    pub estimated_rows: Option<u64>,
    pub poll_interval: PollInterval,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BuildingDataTree {
    pub building_id: String,
    pub building_root: String,
    pub manifest: HistoryManifest,
    pub equipment: Vec<EquipmentHistory>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuleDefinition {
    pub rule_id: String,
    pub sql_file: String,
    pub description: String,
    #[serde(default)]
    pub required_roles: Vec<String>,
    #[serde(default)]
    pub output_columns: Vec<String>,
    pub confirm_seconds: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FaultResult {
    pub rule_id: String,
    pub equipment_id: String,
    pub fault_hours: f64,
    pub fault_pct: f64,
    pub total_hours: f64,
    pub fault_samples: u64,
    pub total_samples: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnalyticsResult {
    pub metric: String,
    pub equipment_id: String,
    pub value: f64,
    #[serde(default)]
    pub unit: Option<String>,
}
