//! Ace IoT driver placeholder (Wave-NF stub).

use super::map::RawProviderPoint;

#[derive(Debug, Clone)]
pub struct AceIotStubDriver {
    building_id: String,
}

impl AceIotStubDriver {
    pub fn new(building_id: &str) -> Self {
        Self {
            building_id: building_id.to_string(),
        }
    }

    pub async fn authenticate(&mut self) -> Result<(), String> {
        Err(format!(
            "ace_iot driver not implemented ({})",
            self.building_id
        ))
    }

    pub async fn query_points(&self) -> Result<Vec<RawProviderPoint>, String> {
        Ok(Vec::new())
    }
}
