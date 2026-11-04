//! T1423-5 ASAP catch-up acceptance (state machine + claim priority).

use chrono::{DateTime, Duration, Utc};

use super::asap_mode::{decide_mode, plan_backlog, CatchupMode};
use super::gap_planner::gap_plan_input;
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
    let plan = gap_plan_input(
        h(1),
        h(12),
        Some(h(1)),
        h(1),
        &stored,
        Some(h(1)),
        false,
        MAX_HISTORY_WINDOW,
    )
    .and_then(plan_backlog)
    .expect("plan");
    let enter =
        decide_mode(&plan, Some(h(1)), h(12), Duration::seconds(300), 3600, 3).expect("decide");
    assert_eq!(enter.mode, CatchupMode::Asap);

    let now = h(10) + Duration::minutes(10);
    let last = h(9) + Duration::minutes(30);
    let caught_up = gap_plan_input(
        h(1),
        h(10),
        Some(h(1)),
        h(1),
        &stored,
        Some(last),
        false,
        MAX_HISTORY_WINDOW,
    )
    .and_then(plan_backlog)
    .expect("plan");
    let exit =
        decide_mode(&caught_up, Some(last), now, Duration::seconds(300), 3600, 1).expect("decide");
    assert_eq!(exit.mode, CatchupMode::Normal);
}
