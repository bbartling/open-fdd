//! T1423-5 ASAP catch-up acceptance (state machine + claim priority).

use chrono::{DateTime, Duration, Utc};

use super::asap_mode::{decide_mode, plan_backlog, CatchupMode};
use super::gap_planner::GapPlanInput;
use crate::providers::http_policy::MAX_HISTORY_WINDOW;

fn h(n: i64) -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-06-01T00:00:00Z")
        .unwrap()
        .with_timezone(&Utc)
        + Duration::hours(n)
}

#[test]
fn t1423_5_asap_mode_enters_on_backlog_and_exits_near_now() {
    let stored = [h(1)];
    let plan = plan_backlog(GapPlanInput {
        requested_start: h(1),
        requested_end: h(12),
        provider_data_start: Some(h(1)),
        binding_created_at: h(1),
        stored_hour_starts: &stored,
        last_stored_ts: Some(h(1)),
        force: false,
        max_span: MAX_HISTORY_WINDOW,
    })
    .expect("plan");
    let enter =
        decide_mode(&plan, Some(h(1)), h(12), Duration::seconds(300), 3600, 3).expect("decide");
    assert_eq!(enter.mode, CatchupMode::Asap);

    let now = h(10) + Duration::minutes(10);
    let last = h(9) + Duration::minutes(30);
    let caught_up = plan_backlog(GapPlanInput {
        requested_start: h(1),
        requested_end: h(10),
        provider_data_start: Some(h(1)),
        binding_created_at: h(1),
        stored_hour_starts: &stored,
        last_stored_ts: Some(last),
        force: false,
        max_span: MAX_HISTORY_WINDOW,
    })
    .expect("plan");
    let exit =
        decide_mode(&caught_up, Some(last), now, Duration::seconds(300), 3600, 1).expect("decide");
    assert_eq!(exit.mode, CatchupMode::Normal);
}
