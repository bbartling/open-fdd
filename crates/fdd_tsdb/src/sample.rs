use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SampleRow {
    pub ts: DateTime<Utc>,
    pub site_id: String,
    pub openfdd_key: String,
    pub haystack_id: Option<String>,
    pub val: Option<f64>,
    pub unit: Option<String>,
    pub quality: Option<String>,
    pub equipment_id: Option<String>,
    pub role: Option<String>,
    /// Stable source point id from a portal inventory. When set, the series key
    /// comes from `point_map (site_id, portal_point_id)` and `openfdd_key` is
    /// only the key minted for a point seen for the first time.
    #[serde(default)]
    pub portal_point_id: Option<String>,
    #[serde(default)]
    pub provider_instance_id: Option<String>,
}

#[derive(Debug, Clone, Default)]
pub struct UpsertBatch {
    pub rows: Vec<SampleRow>,
}

impl UpsertBatch {
    pub fn push(&mut self, row: SampleRow) {
        self.rows.push(row);
    }

    pub fn len(&self) -> usize {
        self.rows.len()
    }

    pub fn is_empty(&self) -> bool {
        self.rows.is_empty()
    }
}
