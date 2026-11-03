//! Operator overrides for provider model-sync cadence and history ingest schedule.
//!
//! Base values come from `OPENFDD_PROVIDER_SITES`; persisted overlays live under
//! `state/providers/operator-site-schedules.json` in the canonical state store.

use std::collections::BTreeMap;
use std::path::Path;
use std::sync::Mutex;

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

use crate::canonical_state::CanonicalStateStore;
use crate::ingest_queue::schedule::IngestSchedule;

pub const OPERATOR_SITE_SCHEDULES_PATH: &str = "state/providers/operator-site-schedules.json";

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct OperatorSiteScheduleEntry {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub poll_secs: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub schedule_mode: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub schedule_timezone: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct OperatorSiteScheduleStore {
    #[serde(default)]
    pub sites: BTreeMap<String, OperatorSiteScheduleEntry>,
}

impl OperatorSiteScheduleStore {
    pub fn load(store: &CanonicalStateStore) -> Result<Self> {
        let Some(bytes) = store.read_optional(Path::new(OPERATOR_SITE_SCHEDULES_PATH))? else {
            return Ok(Self::default());
        };
        serde_json::from_slice(&bytes).context("decode operator site schedules")
    }

    pub fn persist(&self, store: &CanonicalStateStore) -> Result<()> {
        let bytes = serde_json::to_vec_pretty(self).context("encode operator site schedules")?;
        store.write(Path::new(OPERATOR_SITE_SCHEDULES_PATH), &bytes)
    }

    pub fn entry(&self, building_id: &str) -> Option<&OperatorSiteScheduleEntry> {
        self.sites.get(building_id)
    }

    pub fn upsert(&mut self, building_id: &str, entry: OperatorSiteScheduleEntry) {
        if entry.poll_secs.is_none()
            && entry.schedule_mode.is_none()
            && entry.schedule_timezone.is_none()
        {
            self.sites.remove(building_id);
        } else {
            self.sites.insert(building_id.to_string(), entry);
        }
    }
}

pub fn effective_poll_secs(base: u64, entry: Option<&OperatorSiteScheduleEntry>) -> u64 {
    entry
        .and_then(|row| row.poll_secs)
        .unwrap_or(base)
        .clamp(15, 3600)
}

pub fn effective_ingest_schedule(
    base: IngestSchedule,
    entry: Option<&OperatorSiteScheduleEntry>,
) -> Result<IngestSchedule, String> {
    let Some(entry) = entry else {
        return Ok(base);
    };
    let mode = entry.schedule_mode.as_deref().or_else(|| {
        if entry.schedule_timezone.is_some() {
            Some("daily")
        } else {
            None
        }
    });
    if mode.is_none() && entry.schedule_timezone.is_none() {
        return Ok(base);
    }
    IngestSchedule::parse(mode, entry.schedule_timezone.as_deref())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn effective_poll_clamps_override() {
        let entry = OperatorSiteScheduleEntry {
            poll_secs: Some(10),
            ..OperatorSiteScheduleEntry::default()
        };
        assert_eq!(effective_poll_secs(300, Some(&entry)), 15);
    }

    #[test]
    fn effective_history_schedule_daily() {
        let entry = OperatorSiteScheduleEntry {
            schedule_mode: Some("daily".into()),
            schedule_timezone: Some("America/Chicago".into()),
            ..OperatorSiteScheduleEntry::default()
        };
        let parsed =
            effective_ingest_schedule(IngestSchedule::Periodic, Some(&entry)).expect("daily");
        assert_eq!(
            parsed,
            IngestSchedule::Daily {
                tz: "America/Chicago".parse().expect("tz"),
            }
        );
    }
}
