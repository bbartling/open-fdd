//! Bench 5007 smoke orchestration and phase validation.

use crate::bench::config::SmokeConfig;
use crate::bench::poll::{cadence_credible, poll_cycle, summarize_poll_cadence, PollProof};
use crate::bench::report::{write_reports, SmokeReport};
use crate::fdd::confirmation::{
    apply_confirmation, confirmation_lag_seconds, first_true_ts, last_true_ts, FaultField,
};
use crate::fdd::datafusion_engine::{
    evaluate_rule_on_samples, rows_from_fault_batch, run_fault_raw_sql, DataFusionRunMeta,
    RuleLimits,
};
use crate::historian::bench_telemetry::TelemetryStore;
use chrono::{DateTime, Duration, Utc};
use std::thread;
use std::time::Instant;

#[derive(Clone, Debug)]
pub struct PhaseResult {
    pub phase_index: u64,
    pub label: &'static str,
    pub started_at: DateTime<Utc>,
    pub ended_at: DateTime<Utc>,
    pub limits: RuleLimits,
    pub expected_raw_fault: bool,
    pub expected_confirmed_fault: bool,
    pub actual_raw_fault: bool,
    pub actual_confirmed_fault: bool,
    pub first_raw_fault_at: Option<DateTime<Utc>>,
    pub first_confirmed_fault_at: Option<DateTime<Utc>>,
    pub confirmation_lag_seconds: Option<i64>,
    pub clear_at: Option<DateTime<Utc>>,
    pub pass: bool,
    pub notes: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct SmokeOutcome {
    pub pass: bool,
    pub failure_reasons: Vec<String>,
    pub report: SmokeReport,
}

pub fn run_smoke(cfg: SmokeConfig) -> Result<SmokeOutcome, String> {
    let started = Utc::now();
    let start_instant = Instant::now();
    let mut store = TelemetryStore::new();
    let mut poll_times = Vec::new();
    let mut proofs: Vec<PollProof> = Vec::new();
    let mut phase_results = Vec::new();
    let mut events = Vec::new();
    let mut failure_reasons = Vec::new();
    let mut last_meta: Option<DataFusionRunMeta> = None;

    let total_seconds = cfg.duration_minutes * 60;
    let poll_interval = cfg.poll_interval_seconds;
    let column = cfg.point_column();

    let mut cycle_id = 0_u64;
    while start_instant.elapsed().as_secs() < total_seconds {
        cycle_id += 1;
        let cycle = poll_cycle(
            cfg.device_instance,
            cycle_id,
            cfg.allow_simulated,
            cfg.live_required,
        )?;
        poll_times.push(cycle.sample.ts);
        proofs.push(cycle.proof.clone());
        store.append(cycle.sample.clone());
        events.push(format!(
            "{},{},poll_ok,source={},oa_t={:?}",
            cycle.sample.ts.to_rfc3339(),
            cycle_id,
            cycle.proof.source,
            cycle.sample.oa_t
        ));

        if let Ok(batch) = store.record_batch() {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .map_err(|e| e.to_string())?;
            let limits = cfg.limits_for_phase_index(
                (start_instant.elapsed().as_secs() / cfg.phase_minutes.max(1) * 60).min(3),
            );
            if let Ok((_fault_batch, meta)) =
                runtime.block_on(run_fault_raw_sql(batch, &column, &limits))
            {
                last_meta = Some(meta);
            }
        }

        thread::sleep(std::time::Duration::from_secs(poll_interval));
    }

    let ended = Utc::now();
    phase_results = analyze_phases(&store, &cfg, started);
    let cadence = summarize_poll_cadence(
        &poll_times,
        cfg.poll_interval_seconds,
        cfg.poll_tolerance_seconds,
    );

    if !cadence_credible(&cadence) {
        failure_reasons.push(format!(
            "poll cadence not credible: missing_intervals={}, duplicates={}",
            cadence.missing_intervals, cadence.duplicate_timestamps
        ));
    }

    if cfg.live_required && proofs.iter().any(|p| p.simulated) {
        failure_reasons.push("live-required run contained simulated samples".to_string());
    }

    finalize_phase_results(&mut phase_results, &cfg);
    for phase in &phase_results {
        if !phase.pass {
            failure_reasons.push(format!(
                "phase {} failed: {:?}",
                phase.phase_index, phase.notes
            ));
        }
    }

    let report = SmokeReport {
        started_at: started,
        ended_at: ended,
        config: cfg.clone(),
        cadence,
        sample_counts: store.sample_counts_by_column(),
        total_samples: store.len(),
        bacnet_proof: aggregate_proof(&proofs),
        datafusion_meta: last_meta,
        phase_results: phase_results.clone(),
        events,
        pass: failure_reasons.is_empty(),
        failure_reasons: failure_reasons.clone(),
    };

    write_reports(&report)?;

    Ok(SmokeOutcome {
        pass: failure_reasons.is_empty(),
        failure_reasons,
        report,
    })
}

fn aggregate_proof(proofs: &[PollProof]) -> PollProof {
    let mut out = PollProof::default();
    for p in proofs {
        out.requests_sent += p.requests_sent;
        out.responses_received += p.responses_received;
        out.last_response_at = p.last_response_at.or(out.last_response_at);
        out.source = p.source.clone();
        out.generated_from_demo_fixture = p.generated_from_demo_fixture;
        out.simulated = p.simulated;
    }
    out
}

fn analyze_phases(
    store: &TelemetryStore,
    cfg: &SmokeConfig,
    started: DateTime<Utc>,
) -> Vec<PhaseResult> {
    let column = cfg.point_column();
    let phase_seconds = cfg.phase_minutes * 60;
    let phases = cfg.phase_count().min(4);
    let mut out = Vec::new();

    for phase_index in 0..phases {
        let phase_start =
            started + Duration::seconds((phase_index * phase_seconds) as i64);
        let phase_end =
            started + Duration::seconds(((phase_index + 1) * phase_seconds) as i64);
        let samples: Vec<_> = store
            .samples()
            .iter()
            .filter(|s| s.ts >= phase_start && s.ts < phase_end)
            .cloned()
            .collect();
        let limits = cfg.limits_for_phase_index(phase_index);
        let idx = phase_index % 4;
        let expected_raw = idx == 1 || idx == 3;

        if samples.is_empty() {
            out.push(PhaseResult {
                phase_index,
                label: SmokeConfig::phase_label(phase_index),
                started_at: phase_start,
                ended_at: phase_end,
                limits: limits.clone(),
                expected_raw_fault: expected_raw,
                expected_confirmed_fault: expected_raw,
                actual_raw_fault: false,
                actual_confirmed_fault: false,
                first_raw_fault_at: None,
                first_confirmed_fault_at: None,
                confirmation_lag_seconds: None,
                clear_at: None,
                pass: false,
                notes: vec!["no samples in phase window".to_string()],
            });
            continue;
        }

        let rows = evaluate_rule_on_samples(&samples, &column, &limits).unwrap_or_default();
        let raw_pairs: Vec<_> = rows.iter().map(|r| (r.ts, r.fault_raw)).collect();
        let confirmed = apply_confirmation(
            &raw_pairs,
            cfg.confirmation_seconds,
            cfg.poll_interval_seconds as i64 + cfg.poll_tolerance_seconds,
        );
        let last = confirmed.last();
        let actual_raw = last.map(|s| s.fault_raw).unwrap_or(false);
        let actual_confirmed = last.map(|s| s.fault_confirmed).unwrap_or(false);
        let first_raw = first_true_ts(&confirmed, FaultField::Raw);
        let first_confirmed = first_true_ts(&confirmed, FaultField::Confirmed);
        let lag = match (first_raw, first_confirmed) {
            (Some(a), Some(b)) => Some(confirmation_lag_seconds(a, b)),
            _ => None,
        };
        let clear_at = last.and_then(|s| if s.fault_raw { None } else { Some(s.ts) });

        out.push(PhaseResult {
            phase_index,
            label: SmokeConfig::phase_label(phase_index),
            started_at: phase_start,
            ended_at: phase_end,
            limits,
            expected_raw_fault: expected_raw,
            expected_confirmed_fault: expected_raw,
            actual_raw_fault: actual_raw,
            actual_confirmed_fault: actual_confirmed,
            first_raw_fault_at: first_raw,
            first_confirmed_fault_at: first_confirmed,
            confirmation_lag_seconds: lag,
            clear_at,
            pass: true,
            notes: Vec::new(),
        });
    }

    out
}

fn finalize_phase_results(phase_results: &mut [PhaseResult], cfg: &SmokeConfig) {
    for phase in phase_results.iter_mut() {
        let idx = phase.phase_index % 4;
        phase.expected_raw_fault = idx == 1 || idx == 3;
        phase.expected_confirmed_fault = phase.expected_raw_fault;
        let mut notes = Vec::new();

        if phase.expected_raw_fault && !phase.actual_raw_fault {
            notes.push("expected raw fault not observed".to_string());
        }
        if !phase.expected_raw_fault && phase.actual_raw_fault {
            notes.push("unexpected raw fault".to_string());
        }

        if phase.expected_raw_fault {
            if let Some(lag) = phase.confirmation_lag_seconds {
                if lag < cfg.confirmation_seconds {
                    notes.push(format!(
                        "confirmed fault too early: lag={lag}s < {}",
                        cfg.confirmation_seconds
                    ));
                }
            } else if phase.actual_raw_fault {
                notes.push("raw fault without confirmed fault timestamp".to_string());
            }
        } else if phase.actual_confirmed_fault {
            notes.push("confirmed fault during normal limits phase".to_string());
        }

        if !phase.expected_raw_fault && phase.actual_raw_fault {
            phase.pass = false;
        } else if phase.expected_raw_fault && !phase.actual_raw_fault {
            phase.pass = false;
        } else if phase.expected_raw_fault {
            phase.pass = phase
                .confirmation_lag_seconds
                .map(|lag| lag >= cfg.confirmation_seconds)
                .unwrap_or(!phase.actual_raw_fault);
        } else {
            phase.pass = !phase.actual_confirmed_fault;
        }

        phase.notes = notes;
        if !phase.pass {
            phase.pass = false;
        }
    }
}

pub fn run_simulated_ci_smoke() -> Result<SmokeOutcome, String> {
    let cfg = SmokeConfig {
        duration_minutes: 2,
        phase_minutes: 1,
        poll_interval_seconds: 1,
        confirmation_seconds: 20,
        fault_high_f: 50.0,
        normal_high_f: 150.0,
        low_f: -50.0,
        point_fdd_input: "oa-t".to_string(),
        device_instance: 5007,
        live_required: false,
        allow_simulated: true,
        poll_tolerance_seconds: 2,
        report_dir: std::env::temp_dir()
            .join("openfdd_bench5007_ci")
            .to_string_lossy()
            .to_string(),
    };
    run_smoke(cfg)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::historian::bench_telemetry::TelemetrySample;

    #[test]
    fn simulated_rule_evaluation_end_to_end() {
        let samples: Vec<_> = (0..8)
            .map(|i| TelemetrySample {
                ts: Utc::now() + Duration::seconds(i * 10),
                device_instance: 5007,
                oa_t: Some(72.0),
                oa_h: None,
                duct_t: None,
                stat_zn_t: None,
                source: "simulated".to_string(),
                poll_cycle_id: i as u64,
            })
            .collect();
        let fault_limits = RuleLimits {
            high_limit: 50.0,
            low_limit: -50.0,
        };
        let rows = evaluate_rule_on_samples(&samples, "oa_t", &fault_limits).unwrap();
        assert!(rows.iter().all(|r| r.fault_raw));
        let raw_pairs: Vec<_> = rows.iter().map(|r| (r.ts, r.fault_raw)).collect();
        let confirmed = apply_confirmation(&raw_pairs, 60, 30);
        assert!(!confirmed[4].fault_confirmed);
        assert!(confirmed[6].fault_confirmed);
    }
}
