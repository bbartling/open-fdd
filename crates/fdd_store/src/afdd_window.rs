//! Lookback-scoped AFDD result upsert and bounded-backfill guards.
//!
//! Scheduled cycles write one analysis window. Rows that belong to a slice
//! outside that window stay unchanged. Unbounded "update all" is rejected.

use anyhow::{bail, Context, Result};
use chrono::{DateTime, Duration, Utc};
use serde_json::{json, Map, Value};

use crate::afdd::token_is_unbounded_str;
use crate::{AfddConfig, AfddLookbackUnit, AfddOperatorSchedule, AfddScheduleKind};

/// Explicit backfill may not span more than this. Epoch-to-now is not a range.
pub const MAX_AFDD_BACKFILL_DAYS: i64 = 366;
/// Chunk fan-out cap. Raise `chunk_hours` or narrow the range instead.
pub const MAX_AFDD_BACKFILL_CHUNKS: usize = 64;

/// True when a JSON flag asks the routine to rewrite retained history.
pub fn json_requests_full_rewrite(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => false,
        Some(Value::Bool(flag)) => *flag,
        Some(Value::Number(number)) => number.as_f64().unwrap_or(0.0) != 0.0,
        Some(Value::String(raw)) => {
            let token = raw.trim();
            !token.is_empty()
                && !matches!(
                    token.to_ascii_lowercase().as_str(),
                    "0" | "false" | "no" | "off"
                )
        }
        Some(_) => true,
    }
}

const REWRITE_KEYS: &[&str] = &[
    "update_all",
    "rescan_all",
    "refresh_all",
    "update_all_records",
    "full_rescan",
];

fn requests_rewrite(obj: &Map<String, Value>) -> bool {
    REWRITE_KEYS
        .iter()
        .any(|key| json_requests_full_rewrite(obj.get(*key)))
}

/// Operator schedule update. Full-history flags and `lookback=all` are rejected.
#[derive(Debug, Clone, Default)]
pub struct SchedulerConfigUpdate {
    pub interval_minutes: Option<u64>,
    pub lookback_days: Option<u64>,
    pub schedule_kind: Option<String>,
    pub wall_clock_hhmm: Option<String>,
    pub wall_clock_timezone: Option<String>,
    pub requests_full_rewrite: bool,
    pub lookback_token: Option<String>,
}

impl SchedulerConfigUpdate {
    pub fn from_json(body: &Value) -> Result<Self> {
        let obj = body
            .as_object()
            .context("AFDD config body must be a JSON object")?;
        let lookback_token = unbounded_field(obj.get("lookback"))
            .or_else(|| unbounded_field(obj.get("lookback_days")));
        Ok(Self {
            interval_minutes: obj.get("interval_minutes").and_then(Value::as_u64),
            lookback_days: obj.get("lookback_days").and_then(Value::as_u64),
            schedule_kind: obj
                .get("schedule_kind")
                .and_then(Value::as_str)
                .map(str::to_string),
            wall_clock_hhmm: obj
                .get("wall_clock_hhmm")
                .and_then(Value::as_str)
                .map(str::to_string),
            wall_clock_timezone: obj
                .get("wall_clock_timezone")
                .and_then(Value::as_str)
                .map(str::to_string),
            requests_full_rewrite: requests_rewrite(obj),
            lookback_token,
        })
    }
}

fn unbounded_field(value: Option<&Value>) -> Option<String> {
    match value {
        Some(Value::String(raw)) if token_is_unbounded_str(raw) => Some(raw.clone()),
        _ => None,
    }
}

pub fn apply_scheduler_config_update(
    current: &AfddConfig,
    update: &SchedulerConfigUpdate,
) -> Result<AfddOperatorSchedule> {
    if update.requests_full_rewrite {
        bail!(
            "scheduled AFDD does not update all retained results; use a bounded backfill with start_utc and end_utc"
        );
    }
    if update
        .lookback_token
        .as_deref()
        .is_some_and(token_is_unbounded_str)
    {
        bail!("lookback cannot be unbounded");
    }
    let schedule_kind = match update.schedule_kind.as_deref() {
        None => current.schedule_kind,
        Some(raw) => AfddScheduleKind::parse(raw)?,
    };
    let interval_minutes = update.interval_minutes.unwrap_or(current.interval_minutes);
    let (lookback_value, lookback_unit) = if let Some(days) = update.lookback_days {
        (days, AfddLookbackUnit::Days)
    } else {
        (current.lookback_value, current.lookback_unit)
    };
    let (wall_clock_hhmm, wall_clock_timezone) = if schedule_kind == AfddScheduleKind::WallClock {
        (
            update
                .wall_clock_hhmm
                .clone()
                .or_else(|| current.wall_clock_hhmm.clone()),
            update
                .wall_clock_timezone
                .clone()
                .or_else(|| current.wall_clock_timezone.clone()),
        )
    } else {
        (None, None)
    };
    let schedule = AfddOperatorSchedule {
        interval_minutes,
        lookback_value,
        lookback_unit,
        schedule_kind,
        wall_clock_hhmm,
        wall_clock_timezone,
    };
    schedule.validate_allowlist()?;
    Ok(schedule)
}

/// Parse an explicit backfill range. Missing bounds and "all" are rejected.
pub fn parse_explicit_backfill_bounds(
    start: Option<&str>,
    end: Option<&str>,
) -> Result<(DateTime<Utc>, DateTime<Utc>)> {
    let start_raw = start.unwrap_or("").trim();
    let end_raw = end.unwrap_or("").trim();
    if start_raw.is_empty()
        || end_raw.is_empty()
        || token_is_unbounded_str(start_raw)
        || token_is_unbounded_str(end_raw)
    {
        bail!(
            "AFDD backfill requires an explicit start_utc and end_utc; unbounded 'all' is rejected"
        );
    }
    let start_utc = DateTime::parse_from_rfc3339(start_raw)
        .context("start_utc")?
        .with_timezone(&Utc);
    let end_utc = DateTime::parse_from_rfc3339(end_raw)
        .context("end_utc")?
        .with_timezone(&Utc);
    if end_utc <= start_utc {
        bail!("AFDD backfill end must be after start");
    }
    if end_utc - start_utc > Duration::days(MAX_AFDD_BACKFILL_DAYS) {
        bail!(
            "AFDD backfill range exceeds {MAX_AFDD_BACKFILL_DAYS} days; narrow start_utc and end_utc"
        );
    }
    Ok((start_utc, end_utc))
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParsedBackfill {
    pub start_utc: DateTime<Utc>,
    pub end_utc: DateTime<Utc>,
    pub chunk_hours: u64,
    pub building_id: Option<String>,
}

pub fn parse_backfill_request(body: &Value) -> Result<ParsedBackfill> {
    let obj = body
        .as_object()
        .context("AFDD backfill body must be a JSON object")?;
    if requests_rewrite(obj) {
        bail!("AFDD backfill rejects update-all; pass start_utc and end_utc");
    }
    let (start_utc, end_utc) = parse_explicit_backfill_bounds(
        obj.get("start_utc").and_then(Value::as_str),
        obj.get("end_utc").and_then(Value::as_str),
    )?;
    let chunk_hours = obj.get("chunk_hours").and_then(Value::as_u64).unwrap_or(24);
    if chunk_hours == 0 {
        bail!("chunk_hours must be greater than zero");
    }
    let building_id = obj
        .get("building_id")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|scope| !scope.is_empty())
        .map(str::to_string);
    Ok(ParsedBackfill {
        start_utc,
        end_utc,
        chunk_hours,
        building_id,
    })
}

/// Routine triggers must carry a window and must not ask to rewrite all history.
pub fn enforce_routine_result_scope(payload: &Value, has_window: bool) -> Result<()> {
    let obj = payload.as_object();
    if obj.is_some_and(requests_rewrite) {
        bail!(
            "AFDD rejects update-all; scheduled runs upsert the lookback window only, and historical rebuilds need an explicit start_utc and end_utc"
        );
    }
    let trigger = payload
        .get("afdd_trigger")
        .and_then(Value::as_str)
        .unwrap_or("");
    if matches!(trigger, "scheduled" | "run_now" | "backfill") && !has_window {
        bail!("routine AFDD requires start_utc and end_utc; it cannot rescan retained history");
    }
    Ok(())
}

fn parse_utc(raw: &str) -> Result<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(raw.trim())
        .map(|dt| dt.with_timezone(&Utc))
        .context("AFDD window timestamp")
}

fn slice_bounds(slice: &Value) -> Option<(DateTime<Utc>, DateTime<Utc>)> {
    let start = slice.get("start_utc")?.as_str()?;
    let end = slice.get("end_utc")?.as_str()?;
    Some((parse_utc(start).ok()?, parse_utc(end).ok()?))
}

fn bound_absent(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => true,
        Some(Value::String(raw)) => raw.trim().is_empty(),
        _ => false,
    }
}

/// No usable window: missing, JSON null, or blank start and end together.
fn unscoped_bounds(slice: &Value) -> bool {
    bound_absent(slice.get("start_utc")) && bound_absent(slice.get("end_utc"))
}

/// One identity for rows-only files and null-bound slices.
///
/// A lookback upsert relabels legacy `rows` as `preserved_unscoped`. The
/// fingerprint must not change with that label, or gate 38 reports the slice
/// as rewritten.
fn fingerprint_slice(slice: &Value) -> Value {
    let rows_sha256 = sha256_json(slice.get("rows").unwrap_or(&json!([])));
    if unscoped_bounds(slice) {
        json!({
            "start_utc": Value::Null,
            "end_utc": Value::Null,
            "preserved_unscoped": true,
            "legacy_unscoped": false,
            "rows_sha256": rows_sha256,
        })
    } else {
        json!({
            "start_utc": slice.get("start_utc").cloned().unwrap_or(Value::Null),
            "end_utc": slice.get("end_utc").cloned().unwrap_or(Value::Null),
            "preserved_unscoped": false,
            "legacy_unscoped": false,
            "rows_sha256": rows_sha256,
        })
    }
}

/// Null-bound slices become the preserved form and stay that way.
///
/// Dropping explicit null bounds and setting `preserved_unscoped` once makes
/// a second merge a no-op on that slice, and gives the slice an epoch display
/// rank so an errored upsert cannot blank the previous rows.
fn canonicalize_unscoped_slice(slice: Value) -> Value {
    if !unscoped_bounds(&slice) {
        return slice;
    }
    let Value::Object(mut map) = slice else {
        return slice;
    };
    // Explicit null bounds and the legacy label are not part of the stable slice.
    let _ = map.remove("start_utc");
    let _ = map.remove("end_utc");
    let _ = map.remove("legacy_unscoped");
    map.insert("preserved_unscoped".into(), Value::Bool(true));
    Value::Object(map)
}

fn existing_windows(existing: Option<&Value>) -> Vec<Value> {
    let Some(existing) = existing else {
        return Vec::new();
    };
    if let Some(windows) = existing.get("windows").and_then(Value::as_array) {
        return windows.clone();
    }
    if let Some(rows) = existing.get("rows") {
        return vec![json!({
            "preserved_unscoped": true,
            "rows": rows,
        })];
    }
    Vec::new()
}

fn slice_fully_covered(slice: &Value, win_start: DateTime<Utc>, win_end: DateTime<Utc>) -> bool {
    match slice_bounds(slice) {
        Some((start, end)) => start >= win_start && end <= win_end,
        None => false,
    }
}

fn new_slice(start_utc: &str, end_utc: &str, incoming: &Value) -> Value {
    let mut slice = Map::new();
    slice.insert("start_utc".into(), json!(start_utc.trim()));
    slice.insert("end_utc".into(), json!(end_utc.trim()));
    let rows = incoming
        .get("rows")
        .cloned()
        .filter(Value::is_array)
        .unwrap_or_else(|| json!([]));
    slice.insert("rows".into(), rows);
    for key in ["error", "status", "skipped", "missing_roles"] {
        if let Some(value) = incoming.get(key) {
            if !value.is_null() {
                slice.insert(key.to_string(), value.clone());
            }
        }
    }
    Value::Object(slice)
}

fn display_rank(slice: &Value) -> Option<(DateTime<Utc>, DateTime<Utc>)> {
    if slice.get("error").is_some() {
        return None;
    }
    if let Some(bounds) = slice_bounds(slice) {
        return Some(bounds);
    }
    if slice
        .get("preserved_unscoped")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        let epoch = DateTime::UNIX_EPOCH;
        return Some((epoch, epoch));
    }
    None
}

fn display_rows(windows: &[Value]) -> Value {
    let mut best: Option<&Value> = None;
    let mut best_rank: Option<(DateTime<Utc>, DateTime<Utc>)> = None;
    for slice in windows {
        let Some(rank) = display_rank(slice) else {
            continue;
        };
        if best_rank.is_none_or(|current| rank >= current) {
            best = Some(slice);
            best_rank = Some(rank);
        }
    }
    best.and_then(|slice| slice.get("rows").cloned())
        .unwrap_or_else(|| json!([]))
}

fn sha256_json(value: &Value) -> String {
    use sha2::{Digest, Sha256};
    // `Value` map keys are strings, so encoding does not fail.
    let bytes = serde_json::to_vec(value).unwrap_or_else(|_| Vec::from(b"null"));
    format!("{:x}", Sha256::digest(bytes))
}

/// Window fingerprints for one rule-result document.
///
/// Each entry is a slice the lookback upsert must leave unchanged when that
/// slice is not fully inside the next cycle window. Rows-only files and
/// slices with no bounds share one unscoped identity: null bounds,
/// `preserved_unscoped`, and the rows hash. The merge keeps that hash.
pub fn rule_result_window_fingerprints(body: &Value) -> Vec<Value> {
    if let Some(windows) = body.get("windows").and_then(Value::as_array) {
        return windows.iter().map(fingerprint_slice).collect();
    }
    if body.get("rows").is_some() {
        return vec![fingerprint_slice(&json!({
            "rows": body.get("rows").cloned().unwrap_or(json!([])),
        }))];
    }
    Vec::new()
}

/// Upsert `incoming` rows for `[start_utc, end_utc)`.
///
/// Slices that extend outside the window, disjoint slices, and legacy unscoped
/// rows are kept by value. A slice fully inside the window is replaced.
pub fn merge_windowed_rule_result(
    existing: Option<&Value>,
    start_utc: &str,
    end_utc: &str,
    incoming: &Value,
) -> Result<Value> {
    if token_is_unbounded_str(start_utc) || token_is_unbounded_str(end_utc) {
        bail!("AFDD result upsert requires an explicit lookback window");
    }
    let win_start = parse_utc(start_utc)?;
    let win_end = parse_utc(end_utc)?;
    if win_end <= win_start {
        bail!("AFDD result window end must be after start");
    }
    let mut windows: Vec<Value> = existing_windows(existing)
        .into_iter()
        .filter(|slice| !slice_fully_covered(slice, win_start, win_end))
        .map(canonicalize_unscoped_slice)
        .collect();
    windows.push(new_slice(start_utc, end_utc, incoming));
    let rows = display_rows(&windows);
    Ok(json!({
        "rows": rows,
        "windows": windows,
        "result_scope": "lookback_window",
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn outside_slice() -> Value {
        json!({
            "start_utc": "2026-09-01T05:00:00Z",
            "end_utc": "2026-09-02T05:00:00Z",
            "rows": [{
                "equipment_id": "AHU_1",
                "fault_hours": 3.5,
                "marker": "keep-me"
            }]
        })
    }

    #[test]
    fn outside_window_slice_is_unchanged_after_upsert() {
        let kept = outside_slice();
        let existing = json!({
            "rows": kept["rows"],
            "windows": [kept],
        });
        let updated = merge_windowed_rule_result(
            Some(&existing),
            "2026-09-28T10:00:00Z",
            "2026-09-29T10:00:00Z",
            &json!({"rows": [{"equipment_id": "AHU_1", "fault_hours": 1.0}]}),
        )
        .unwrap();
        assert_eq!(updated["windows"][0], kept);
        assert_eq!(updated["windows"].as_array().unwrap().len(), 2);
        assert_eq!(updated["rows"][0]["fault_hours"], 1.0);
        assert_eq!(updated["result_scope"], "lookback_window");
        let parsed: Value =
            serde_json::from_str(&serde_json::to_string_pretty(&updated).unwrap()).unwrap();
        assert_eq!(parsed["windows"][0], kept);
    }

    #[test]
    fn same_window_replaces_only_that_slice() {
        let kept = outside_slice();
        let same = json!({
            "start_utc": "2026-09-28T10:00:00Z",
            "end_utc": "2026-09-29T10:00:00Z",
            "rows": [{"equipment_id": "AHU_1", "fault_hours": 9.0}]
        });
        let existing = json!({"windows": [kept, same]});
        let updated = merge_windowed_rule_result(
            Some(&existing),
            "2026-09-28T10:00:00Z",
            "2026-09-29T10:00:00Z",
            &json!({"rows": [{"equipment_id": "AHU_1", "fault_hours": 1.25}]}),
        )
        .unwrap();
        let windows = updated["windows"].as_array().unwrap();
        assert_eq!(windows.len(), 2);
        assert_eq!(windows[0], kept);
        assert_eq!(windows[1]["rows"][0]["fault_hours"], 1.25);
    }

    #[test]
    fn partial_overlap_keeps_slice_that_extends_outside() {
        let wide = json!({
            "start_utc": "2026-09-01T00:00:00Z",
            "end_utc": "2026-09-03T00:00:00Z",
            "rows": [{"equipment_id": "AHU_1", "fault_hours": 4.0, "marker": "outside-tail"}]
        });
        let existing = json!({"windows": [wide]});
        let updated = merge_windowed_rule_result(
            Some(&existing),
            "2026-09-02T00:00:00Z",
            "2026-09-04T00:00:00Z",
            &json!({"rows": [{"equipment_id": "AHU_1", "fault_hours": 1.0}]}),
        )
        .unwrap();
        assert_eq!(updated["windows"][0], wide);
        assert_eq!(updated["windows"].as_array().unwrap().len(), 2);
        assert_eq!(updated["rows"][0]["fault_hours"], 1.0);
    }

    #[test]
    fn fully_contained_slice_is_replaced() {
        let inner = json!({
            "start_utc": "2026-09-02T00:00:00Z",
            "end_utc": "2026-09-03T00:00:00Z",
            "rows": [{"equipment_id": "AHU_1", "fault_hours": 2.0}]
        });
        let existing = json!({"windows": [inner]});
        let updated = merge_windowed_rule_result(
            Some(&existing),
            "2026-09-01T00:00:00Z",
            "2026-09-04T00:00:00Z",
            &json!({"rows": [{"equipment_id": "AHU_1", "fault_hours": 0.5}]}),
        )
        .unwrap();
        let windows = updated["windows"].as_array().unwrap();
        assert_eq!(windows.len(), 1);
        assert_eq!(windows[0]["start_utc"], "2026-09-01T00:00:00Z");
        assert_eq!(windows[0]["rows"][0]["fault_hours"], 0.5);
    }

    #[test]
    fn legacy_unscoped_rows_are_preserved() {
        let existing = json!({
            "rows": [{"equipment_id": "AHU_1", "fault_hours": 8.0, "marker": "legacy"}]
        });
        let updated = merge_windowed_rule_result(
            Some(&existing),
            "2026-09-28T10:00:00Z",
            "2026-09-29T10:00:00Z",
            &json!({"rows": [{"equipment_id": "AHU_1", "fault_hours": 1.0}]}),
        )
        .unwrap();
        let preserved = updated["windows"]
            .as_array()
            .unwrap()
            .iter()
            .find(|slice| slice.get("preserved_unscoped") == Some(&json!(true)))
            .unwrap();
        assert_eq!(preserved["rows"], existing["rows"]);
        assert_eq!(updated["rows"][0]["fault_hours"], 1.0);
    }

    #[test]
    fn error_slice_does_not_replace_previous_display_rows() {
        let kept = outside_slice();
        let existing = json!({"windows": [kept]});
        let updated = merge_windowed_rule_result(
            Some(&existing),
            "2026-09-28T10:00:00Z",
            "2026-09-29T10:00:00Z",
            &json!({"rows": [], "error": "boom"}),
        )
        .unwrap();
        assert_eq!(updated["windows"][0], kept);
        assert_eq!(updated["rows"], kept["rows"]);
        assert_eq!(updated["windows"][1]["error"], "boom");
    }

    #[test]
    fn unbounded_window_upsert_is_rejected() {
        let err =
            merge_windowed_rule_result(None, "all", "2026-09-29T10:00:00Z", &json!({"rows": []}));
        assert!(err.is_err());
    }

    #[test]
    fn update_all_config_is_rejected() {
        let current = AfddConfig::default();
        let update = SchedulerConfigUpdate::from_json(&json!({
            "interval_minutes": 1440,
            "lookback_days": 1,
            "update_all": true
        }))
        .unwrap();
        assert!(apply_scheduler_config_update(&current, &update).is_err());
        let lookback_all = SchedulerConfigUpdate::from_json(&json!({
            "interval_minutes": 1440,
            "lookback_days": "all"
        }))
        .unwrap();
        assert!(apply_scheduler_config_update(&current, &lookback_all).is_err());
    }

    #[test]
    fn wall_clock_config_update_keeps_interval_fields_allowlisted() {
        let current = AfddConfig::default();
        let update = SchedulerConfigUpdate::from_json(&json!({
            "schedule_kind": "wall_clock",
            "interval_minutes": 1440,
            "lookback_days": 1,
            "wall_clock_hhmm": "05:00",
            "wall_clock_timezone": "America/Chicago"
        }))
        .unwrap();
        let schedule = apply_scheduler_config_update(&current, &update).unwrap();
        assert_eq!(schedule.schedule_kind, AfddScheduleKind::WallClock);
        assert_eq!(schedule.wall_clock_hhmm.as_deref(), Some("05:00"));
        assert_eq!(
            schedule.wall_clock_timezone.as_deref(),
            Some("America/Chicago")
        );
    }

    #[test]
    fn backfill_all_token_is_rejected() {
        assert!(parse_explicit_backfill_bounds(Some("all"), Some("2026-09-29T00:00:00Z")).is_err());
        assert!(parse_explicit_backfill_bounds(None, None).is_err());
        assert!(parse_backfill_request(&json!({
            "update_all": true,
            "start_utc": "2026-09-28T00:00:00Z",
            "end_utc": "2026-09-29T00:00:00Z"
        }))
        .is_err());
    }

    #[test]
    fn backfill_accepts_explicit_range_and_rejects_epoch_span() {
        let parsed = parse_backfill_request(&json!({
            "start_utc": "2026-09-27T00:00:00Z",
            "end_utc": "2026-09-29T00:00:00Z",
            "chunk_hours": 24
        }))
        .unwrap();
        assert_eq!(parsed.end_utc - parsed.start_utc, Duration::hours(48));
        assert!(parse_explicit_backfill_bounds(
            Some("1970-01-01T00:00:00Z"),
            Some("2026-09-29T00:00:00Z")
        )
        .is_err());
    }

    #[test]
    fn outside_slice_fingerprint_survives_upsert() {
        let kept = outside_slice();
        let existing = json!({
            "rows": [{
                "equipment_id": "AHU_1",
                "fault_hours": 3.5,
                "marker": "keep-me"
            }],
            "windows": [{
                "start_utc": "2026-09-01T05:00:00Z",
                "end_utc": "2026-09-02T05:00:00Z",
                "rows": [{
                    "equipment_id": "AHU_1",
                    "fault_hours": 3.5,
                    "marker": "keep-me"
                }]
            }]
        });
        assert_eq!(existing["windows"][0], kept);
        let before = rule_result_window_fingerprints(&existing);
        let updated = merge_windowed_rule_result(
            Some(&existing),
            "2026-09-28T10:00:00Z",
            "2026-09-29T10:00:00Z",
            &json!({"rows": [{"equipment_id": "AHU_1", "fault_hours": 1.0}]}),
        )
        .unwrap();
        let after = rule_result_window_fingerprints(&updated);
        assert_eq!(before[0]["rows_sha256"], after[0]["rows_sha256"]);
        assert_eq!(before[0]["start_utc"], after[0]["start_utc"]);
        assert_eq!(before[0]["end_utc"], after[0]["end_utc"]);
        assert_eq!(after.len(), 2);
        assert_ne!(after[1]["rows_sha256"], before[0]["rows_sha256"]);
    }

    #[test]
    fn legacy_and_null_bound_unscoped_fingerprints_match_after_upsert() {
        let legacy_rows = json!([{
            "equipment_id": "AHU_1",
            "fault_hours": 8.0,
            "marker": "legacy"
        }]);
        let legacy = json!({"rows": legacy_rows});
        let before_legacy = rule_result_window_fingerprints(&legacy);
        let from_legacy = merge_windowed_rule_result(
            Some(&legacy),
            "2026-09-28T10:00:00Z",
            "2026-09-29T10:00:00Z",
            &json!({"rows": [{"equipment_id": "AHU_1", "fault_hours": 1.0}]}),
        )
        .unwrap();
        let after_legacy = rule_result_window_fingerprints(&from_legacy);
        let preserved = after_legacy
            .iter()
            .find(|slice| slice.get("start_utc").is_none_or(Value::is_null))
            .unwrap();
        assert_eq!(&before_legacy[0], preserved);

        let null_rows = json!([{
            "equipment_id": "AHU_1",
            "fault_hours": 4.0,
            "marker": "null-bound"
        }]);
        let null_bound = json!({
            "rows": null_rows,
            "windows": [{
                "start_utc": Value::Null,
                "end_utc": Value::Null,
                "rows": null_rows,
            }]
        });
        let before_null = rule_result_window_fingerprints(&null_bound);
        assert_eq!(before_null[0]["preserved_unscoped"], true);
        assert_eq!(before_null[0]["legacy_unscoped"], false);
        let once = merge_windowed_rule_result(
            Some(&null_bound),
            "2026-09-28T10:00:00Z",
            "2026-09-29T10:00:00Z",
            &json!({"rows": [{"equipment_id": "AHU_1", "fault_hours": 1.0}]}),
        )
        .unwrap();
        let after_null = rule_result_window_fingerprints(&once);
        let unscoped: Vec<_> = after_null
            .iter()
            .filter(|slice| slice.get("start_utc").is_none_or(Value::is_null))
            .collect();
        assert_eq!(unscoped.len(), 1);
        assert_eq!(&before_null[0], unscoped[0]);
        let stored = once["windows"]
            .as_array()
            .unwrap()
            .iter()
            .find(|slice| slice.get("preserved_unscoped") == Some(&json!(true)))
            .unwrap();
        assert!(stored.get("start_utc").is_none());
        assert_eq!(stored["rows"], null_rows);
        let twice = merge_windowed_rule_result(
            Some(&once),
            "2026-09-29T10:00:00Z",
            "2026-09-30T10:00:00Z",
            &json!({"rows": [{"equipment_id": "AHU_1", "fault_hours": 2.0}]}),
        )
        .unwrap();
        let stored_again = twice["windows"]
            .as_array()
            .unwrap()
            .iter()
            .find(|slice| slice.get("preserved_unscoped") == Some(&json!(true)))
            .unwrap();
        assert_eq!(stored, stored_again);
        assert_eq!(once["rows"][0]["fault_hours"], 1.0);
    }

    #[test]
    fn null_bound_rows_remain_on_display_when_upsert_errors() {
        let existing = json!({
            "rows": [{"fault_hours": 4.0, "marker": "null-bound"}],
            "windows": [{
                "start_utc": Value::Null,
                "end_utc": Value::Null,
                "rows": [{"fault_hours": 4.0, "marker": "null-bound"}]
            }]
        });
        let updated = merge_windowed_rule_result(
            Some(&existing),
            "2026-09-28T10:00:00Z",
            "2026-09-29T10:00:00Z",
            &json!({"rows": [], "error": "boom"}),
        )
        .unwrap();
        assert_eq!(updated["rows"][0]["marker"], "null-bound");
        assert_eq!(updated["windows"][1]["error"], "boom");
    }

    #[test]
    fn legacy_row_hash_is_kept_on_the_preserved_slice() {
        let existing = json!({
            "rows": [{"equipment_id": "AHU_1", "fault_hours": 8.0, "marker": "legacy"}]
        });
        let before = rule_result_window_fingerprints(&existing);
        assert_eq!(before[0]["preserved_unscoped"], true);
        assert_eq!(before[0]["legacy_unscoped"], false);
        let updated = merge_windowed_rule_result(
            Some(&existing),
            "2026-09-28T10:00:00Z",
            "2026-09-29T10:00:00Z",
            &json!({"rows": [{"equipment_id": "AHU_1", "fault_hours": 1.0}]}),
        )
        .unwrap();
        let after = rule_result_window_fingerprints(&updated);
        let preserved = after
            .iter()
            .find(|slice| slice.get("preserved_unscoped") == Some(&json!(true)))
            .unwrap();
        assert_eq!(preserved["rows_sha256"], before[0]["rows_sha256"]);
    }

    #[test]
    fn routine_trigger_without_window_is_rejected() {
        let scheduled = json!({"afdd_trigger": "scheduled"});
        assert!(enforce_routine_result_scope(&scheduled, false).is_err());
        assert!(enforce_routine_result_scope(&scheduled, true).is_ok());
        let bulk = json!({"mode": "registry"});
        assert!(enforce_routine_result_scope(&bulk, false).is_ok());
        let flagged = json!({"update_all": true, "mode": "registry"});
        assert!(enforce_routine_result_scope(&flagged, true).is_err());
    }
}
