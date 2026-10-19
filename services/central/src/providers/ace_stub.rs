//! Ace IoT driver placeholder (Wave-NF stub).

use super::map::RawProviderPoint;

#[derive(Debug, Clone)]
pub struct AceIotStubDriver;

impl AceIotStubDriver {
    pub fn new(_building_id: &str) -> Self {
        Self
    }

    pub async fn authenticate(&mut self) -> Result<(), String> {
        Err("ace_iot driver not implemented".into())
    }

    pub async fn query_points(&self) -> Result<Vec<RawProviderPoint>, String> {
        Ok(Vec::new())
    }
}
