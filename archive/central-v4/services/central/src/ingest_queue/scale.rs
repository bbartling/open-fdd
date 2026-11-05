//! Stage-3 scale decisions as a pure function.
//!
//! This module does not call Railway, Kubernetes, or any deployment API.
//! Live replica control stays SoftOPEN-deferred until multi-worker proof and
//! an operator budget exist. Missing metrics never increase replicas.

use std::time::Duration;

use chrono::{DateTime, Utc};
use serde::Serialize;

#[derive(Debug, Clone)]
pub struct ScalePolicy {
    pub min_replicas: u32,
    pub max_replicas: u32,
    pub step_up: u32,
    pub slots_per_replica: u32,
    pub target_utilization: f64,
    pub queue_age_threshold: Duration,
    pub scale_up_sustain: Duration,
    pub scale_down_quiet: Duration,
    pub desired_drain: Duration,
}

impl Default for ScalePolicy {
    fn default() -> Self {
        Self {
            min_replicas: 1,
            max_replicas: 4,
            step_up: 1,
            slots_per_replica: 2,
            target_utilization: 0.6,
            queue_age_threshold: Duration::from_secs(15 * 60),
            scale_up_sustain: Duration::from_secs(5 * 60),
            scale_down_quiet: Duration::from_secs(30 * 60),
            desired_drain: Duration::from_secs(15 * 60),
        }
    }
}

#[derive(Debug, Clone)]
pub struct ScaleSample {
    pub now: DateTime<Utc>,
    pub current_replicas: u32,
    pub ready_backlog: u64,
    pub oldest_ready_age: Option<Duration>,
    pub mean_job_secs: Option<f64>,
    pub new_jobs_per_sec: f64,
    pub source_saturated: bool,
    pub db_saturated: bool,
    pub metrics_ok: bool,
    pub breach_since: Option<DateTime<Utc>>,
    pub quiet_since: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ScaleAction {
    Hold,
    ScaleUp,
    ScaleDown,
}

#[derive(Debug, Clone, Serialize)]
pub struct ScaleDecision {
    pub action: ScaleAction,
    pub replicas: u32,
    pub reason: String,
    pub expected_benefit: String,
    /// Always false. Stage 3 does not apply this number to a platform.
    pub live_control: bool,
    pub stage: &'static str,
}

pub fn stage3_status() -> &'static str {
    "softopen_defer"
}

pub fn decide(policy: &ScalePolicy, sample: &ScaleSample) -> ScaleDecision {
    let current = sample
        .current_replicas
        .clamp(policy.min_replicas, policy.max_replicas);
    let hold = |reason: &str, benefit: &str| ScaleDecision {
        action: ScaleAction::Hold,
        replicas: current,
        reason: reason.to_string(),
        expected_benefit: benefit.to_string(),
        live_control: false,
        stage: stage3_status(),
    };
    if !sample.metrics_ok || sample.mean_job_secs.is_none() {
        return hold(
            "metrics_unavailable",
            "keep the current replica count; missing metrics do not scale",
        );
    }
    if sample.source_saturated || sample.db_saturated {
        return hold(
            "admission_saturated",
            "slow the saturated portal or database instead of adding workers",
        );
    }
    let needed = needed_replicas(policy, sample).unwrap_or(current);
    let age_breach = sample
        .oldest_ready_age
        .is_some_and(|age| age >= policy.queue_age_threshold);
    let sustained = sample.breach_since.is_some_and(|since| {
        sample
            .now
            .signed_duration_since(since)
            .to_std()
            .ok()
            .unwrap_or_default()
            >= policy.scale_up_sustain
    });
    if age_breach && sustained && needed > current && current < policy.max_replicas {
        let step = policy.step_up.max(1);
        let replicas = current
            .saturating_add(step)
            .min(policy.max_replicas)
            .min(needed);
        return ScaleDecision {
            action: ScaleAction::ScaleUp,
            replicas,
            reason: "sustained_queue_age".into(),
            expected_benefit: format!(
                "move toward {needed} replica(s) by at most {step}, capped at {}",
                policy.max_replicas
            ),
            live_control: false,
            stage: stage3_status(),
        };
    }
    let quiet = sample.ready_backlog == 0
        && sample.oldest_ready_age.is_none()
        && sample.quiet_since.is_some_and(|since| {
            sample
                .now
                .signed_duration_since(since)
                .to_std()
                .ok()
                .unwrap_or_default()
                >= policy.scale_down_quiet
        });
    if quiet && current > policy.min_replicas {
        return ScaleDecision {
            action: ScaleAction::ScaleDown,
            replicas: current - 1,
            reason: "sustained_quiet".into(),
            expected_benefit:
                "drain one replica after the quiet period; in-flight leases expire on their own"
                    .into(),
            live_control: false,
            stage: stage3_status(),
        };
    }
    hold("within_policy", "no replica change")
}

/// Planning equation from the autoscaling note. Not a measured capacity claim.
pub fn needed_replicas(policy: &ScalePolicy, sample: &ScaleSample) -> Option<u32> {
    let mean = sample.mean_job_secs?;
    if mean <= 0.0 || policy.target_utilization <= 0.0 || policy.slots_per_replica == 0 {
        return None;
    }
    let drain = policy.desired_drain.as_secs_f64().max(1.0);
    let slots = ((sample.new_jobs_per_sec + sample.ready_backlog as f64 / drain) * mean
        / policy.target_utilization)
        .ceil();
    if !slots.is_finite() || slots < 0.0 {
        return None;
    }
    let slots = slots as u64;
    let replicas = slots.div_ceil(u64::from(policy.slots_per_replica));
    Some(
        u32::try_from(replicas)
            .unwrap_or(policy.max_replicas)
            .clamp(policy.min_replicas, policy.max_replicas),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Duration as ChronoDuration;

    fn sample(now: DateTime<Utc>) -> ScaleSample {
        ScaleSample {
            now,
            current_replicas: 1,
            ready_backlog: 1200,
            oldest_ready_age: Some(Duration::from_secs(20 * 60)),
            mean_job_secs: Some(2.0),
            new_jobs_per_sec: 0.3,
            source_saturated: false,
            db_saturated: false,
            metrics_ok: true,
            breach_since: Some(now - ChronoDuration::minutes(6)),
            quiet_since: None,
        }
    }

    #[test]
    fn worked_example_needs_three_replicas_but_steps_by_one() {
        let now = DateTime::parse_from_rfc3339("2026-10-19T13:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let policy = ScalePolicy::default();
        let sample = sample(now);
        assert_eq!(needed_replicas(&policy, &sample), Some(3));
        let decision = decide(&policy, &sample);
        assert_eq!(decision.action, ScaleAction::ScaleUp);
        assert_eq!(decision.replicas, 2);
        assert!(!decision.live_control);
        assert_eq!(decision.stage, "softopen_defer");
    }

    #[test]
    fn missing_metrics_and_saturation_do_not_scale_up() {
        let now = DateTime::parse_from_rfc3339("2026-10-19T13:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let policy = ScalePolicy::default();
        let mut missing = sample(now);
        missing.metrics_ok = false;
        let decision = decide(&policy, &missing);
        assert_eq!(decision.action, ScaleAction::Hold);
        assert_eq!(decision.replicas, 1);

        let mut saturated = sample(now);
        saturated.source_saturated = true;
        saturated.ready_backlog = 5_000;
        let decision = decide(&policy, &saturated);
        assert_eq!(decision.action, ScaleAction::Hold);
        assert_eq!(decision.reason, "admission_saturated");
    }

    #[test]
    fn formula_above_the_cap_never_exceeds_max_replicas() {
        let now = DateTime::parse_from_rfc3339("2026-10-19T13:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let policy = ScalePolicy::default();
        let mut sample = sample(now);
        sample.ready_backlog = 100_000;
        sample.current_replicas = 4;
        assert_eq!(needed_replicas(&policy, &sample), Some(4));
        let decision = decide(&policy, &sample);
        assert_eq!(decision.replicas, 4);
        assert_eq!(decision.action, ScaleAction::Hold);
    }

    #[test]
    fn quiet_period_scales_down_one_step() {
        let now = DateTime::parse_from_rfc3339("2026-10-19T13:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let policy = ScalePolicy::default();
        let sample = ScaleSample {
            now,
            current_replicas: 3,
            ready_backlog: 0,
            oldest_ready_age: None,
            mean_job_secs: Some(2.0),
            new_jobs_per_sec: 0.0,
            source_saturated: false,
            db_saturated: false,
            metrics_ok: true,
            breach_since: None,
            quiet_since: Some(now - ChronoDuration::minutes(31)),
        };
        let decision = decide(&policy, &sample);
        assert_eq!(decision.action, ScaleAction::ScaleDown);
        assert_eq!(decision.replicas, 2);
        assert!(!decision.live_control);
    }
}
