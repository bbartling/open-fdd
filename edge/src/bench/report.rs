//! Report generation for bench 5007 smoke runs.

use crate::bench::config::SmokeConfig;
use crate::bench::poll::{PollCadenceSummary, PollProof};
use crate::bench::smoke::PhaseResult;
use crate::fdd::datafusion_engine::DataFusionRunMeta;
use chrono::{DateTime, Utc};
use std::collections::HashMap;
use std::fs;
use std::path::Path;

#[derive(Clone, Debug)]
pub struct SmokeReport {
    pub started_at: DateTime<Utc>,
    pub ended_at: DateTime<Utc>,
    pub config: SmokeConfig,
    pub cadence: PollCadenceSummary,
    pub sample_counts: HashMap<String, u64>,
    pub total_samples: usize,
    pub bacnet_proof: PollProof,
    pub datafusion_meta: Option<DataFusionRunMeta>,
    pub phase_results: Vec<PhaseResult>,
    pub events: Vec<String>,
    pub pass: bool,
    pub failure_reasons: Vec<String>,
}

pub fn write_reports(report: &SmokeReport) -> Result<(), String> {
    let dir = Path::new(&report.config.report_dir);
    fs::create_dir_all(dir).map_err(|e| e.to_string())?;

    let json = serde_json::to_string_pretty(report).map_err(|e| e.to_string())?;
    fs::write(dir.join("final_report.json"), json).map_err(|e| e.to_string())?;
    fs::write(dir.join("final_report.md"), render_markdown(report)).map_err(|e| e.to_string())?;

    let mut events = String::from("timestamp,cycle_id,event,detail\n");
    for line in &report.events {
        events.push_str(line);
        events.push('\n');
    }
    fs::write(dir.join("events.csv"), events).map_err(|e| e.to_string())?;

    let mut samples = String::from("column,sample_count\n");
    for (k, v) in &report.sample_counts {
        samples.push_str(&format!("{k},{v}\n"));
    }
    fs::write(dir.join("samples_summary.csv"), samples).map_err(|e| e.to_string())?;

    let mut phases = String::from(
        "phase_index,label,expected_raw,actual_raw,expected_confirmed,actual_confirmed,confirmation_lag_s,pass,notes\n",
    );
    for p in &report.phase_results {
        phases.push_str(&format!(
            "{},{},{},{},{},{},{:?},{},{}\n",
            p.phase_index,
            p.label,
            p.expected_raw_fault,
            p.actual_raw_fault,
            p.expected_confirmed_fault,
            p.actual_confirmed_fault,
            p.confirmation_lag_seconds,
            p.pass,
            p.notes.join("|")
        ));
    }
    fs::write(dir.join("rule_phase_results.csv"), phases).map_err(|e| e.to_string())?;
    Ok(())
}

fn render_markdown(report: &SmokeReport) -> String {
    let mut md = String::new();
    md.push_str("# Bench 5007 DataFusion Smoke Report\n\n");
    md.push_str(&format!(
        "**Result:** {}\n\n",
        if report.pass { "PASS" } else { "FAIL" }
    ));
    md.push_str(&format!(
        "- Start: {}\n- End: {}\n- Device: {}\n- Mode: {}\n",
        report.started_at.to_rfc3339(),
        report.ended_at.to_rfc3339(),
        report.config.device_instance,
        if report.bacnet_proof.simulated {
            "simulated (labeled)"
        } else {
            "live/real"
        }
    ));
    md.push_str(&format!(
        "- Poll expected: {}s ± {}s\n- Total samples: {}\n",
        report.cadence.expected_interval_seconds,
        report.cadence.tolerance_seconds,
        report.total_samples
    ));
    if let Some(meta) = &report.datafusion_meta {
        md.push_str("\n## DataFusion / Arrow\n\n");
        md.push_str(&format!(
            "- Engine: {}\n- Path: {}\n- Target partitions: {}\n- Input batch rows: {}\n- SQL: `{}`\n",
            meta.engine, meta.execution_path, meta.target_partitions, meta.batch_rows, meta.sql
        ));
    }
    md.push_str("\n## BACnet proof\n\n");
    md.push_str(&format!(
        "- requests_sent: {}\n- responses_received: {}\n- source: {}\n- generated_from_demo_fixture: {}\n",
        report.bacnet_proof.requests_sent,
        report.bacnet_proof.responses_received,
        report.bacnet_proof.source,
        report.bacnet_proof.generated_from_demo_fixture
    ));
    if !report.failure_reasons.is_empty() {
        md.push_str("\n## Failure reasons\n\n");
        for r in &report.failure_reasons {
            md.push_str(&format!("- {r}\n"));
        }
    }
    md
}

impl serde::Serialize for SmokeReport {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        use serde::ser::SerializeStruct;
        let mut s = serializer.serialize_struct("SmokeReport", 12)?;
        s.serialize_field("started_at", &self.started_at.to_rfc3339())?;
        s.serialize_field("ended_at", &self.ended_at.to_rfc3339())?;
        s.serialize_field("pass", &self.pass)?;
        s.serialize_field("failure_reasons", &self.failure_reasons)?;
        s.serialize_field("device_instance", &self.config.device_instance)?;
        s.serialize_field("bacnet_proof", &self.bacnet_proof_json())?;
        s.serialize_field("poll_cadence", &self.cadence_json())?;
        s.serialize_field("sample_counts", &self.sample_counts)?;
        s.serialize_field("total_samples", &self.total_samples)?;
        s.serialize_field("datafusion", &self.datafusion_meta)?;
        s.serialize_field("phase_results", &self.phase_results_json())?;
        s.serialize_field("report_dir", &self.config.report_dir)?;
        s.end()
    }
}

impl SmokeReport {
    fn bacnet_proof_json(&self) -> serde_json::Value {
        serde_json::json!({
            "requests_sent": self.bacnet_proof.requests_sent,
            "responses_received": self.bacnet_proof.responses_received,
            "last_response_at": self.bacnet_proof.last_response_at.map(|t| t.to_rfc3339()),
            "source": self.bacnet_proof.source,
            "generated_from_demo_fixture": self.bacnet_proof.generated_from_demo_fixture,
            "simulated": self.bacnet_proof.simulated,
        })
    }

    fn cadence_json(&self) -> serde_json::Value {
        serde_json::json!({
            "expected_interval_seconds": self.cadence.expected_interval_seconds,
            "tolerance_seconds": self.cadence.tolerance_seconds,
            "observed_intervals": self.cadence.observed_intervals,
            "min_interval_seconds": self.cadence.min_interval_seconds,
            "max_interval_seconds": self.cadence.max_interval_seconds,
            "avg_interval_seconds": self.cadence.avg_interval_seconds,
            "missing_intervals": self.cadence.missing_intervals,
            "duplicate_timestamps": self.cadence.duplicate_timestamps,
            "stale_samples": self.cadence.stale_samples,
        })
    }

    fn phase_results_json(&self) -> Vec<serde_json::Value> {
        self.phase_results
            .iter()
            .map(|p| {
                serde_json::json!({
                    "phase_index": p.phase_index,
                    "label": p.label,
                    "expected_raw_fault": p.expected_raw_fault,
                    "actual_raw_fault": p.actual_raw_fault,
                    "expected_confirmed_fault": p.expected_confirmed_fault,
                    "actual_confirmed_fault": p.actual_confirmed_fault,
                    "first_raw_fault_at": p.first_raw_fault_at.map(|t| t.to_rfc3339()),
                    "first_confirmed_fault_at": p.first_confirmed_fault_at.map(|t| t.to_rfc3339()),
                    "confirmation_lag_seconds": p.confirmation_lag_seconds,
                    "clear_at": p.clear_at.map(|t| t.to_rfc3339()),
                    "pass": p.pass,
                    "notes": p.notes,
                })
            })
            .collect()
    }
}

impl serde::Serialize for PollProof {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(&format!(
            "requests_sent={},responses_received={},source={}",
            self.requests_sent, self.responses_received, self.source
        ))
    }
}

impl serde::Serialize for PollCadenceSummary {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str("poll_cadence")
    }
}

impl serde::Serialize for PhaseResult {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(self.label)
    }
}

impl serde::Serialize for DataFusionRunMeta {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        use serde::ser::SerializeStruct;
        let mut s = serializer.serialize_struct("DataFusionRunMeta", 6)?;
        s.serialize_field("engine", &self.engine)?;
        s.serialize_field("execution_path", &self.execution_path)?;
        s.serialize_field("target_partitions", &self.target_partitions)?;
        s.serialize_field("batch_rows", &self.batch_rows)?;
        s.serialize_field("batch_columns", &self.batch_columns)?;
        s.serialize_field("sql", &self.sql)?;
        s.end()
    }
}

impl serde::Serialize for SmokeConfig {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        use serde::ser::SerializeStruct;
        let mut s = serializer.serialize_struct("SmokeConfig", 8)?;
        s.serialize_field("duration_minutes", &self.duration_minutes)?;
        s.serialize_field("phase_minutes", &self.phase_minutes)?;
        s.serialize_field("poll_interval_seconds", &self.poll_interval_seconds)?;
        s.serialize_field("confirmation_seconds", &self.confirmation_seconds)?;
        s.serialize_field("fault_high_f", &self.fault_high_f)?;
        s.serialize_field("normal_high_f", &self.normal_high_f)?;
        s.serialize_field("live_required", &self.live_required)?;
        s.serialize_field("allow_simulated", &self.allow_simulated)?;
        s.end()
    }
}
