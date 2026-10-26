//! Checkpointed incremental FDD planning (W4b).
//!
//! A rule result for bucket `[s, e)` reads inputs in `[s - lookback, e)`.
//! So a sample change at `c` can move results in `[c, c + lookback]`, and only
//! the buckets that overlap that span are recomputed. Buckets are fixed UTC
//! hours, or local days or ISO weeks (Monday start) in an IANA time zone, so a
//! local day is 23, 24, or 25 hours across DST.
//!
//! This module plans. [`crate::incremental_store`] claims, publishes, and runs.

use std::collections::BTreeSet;

use chrono::{DateTime, Datelike, Days, Duration, NaiveDate, NaiveTime, TimeZone, Utc};
use chrono_tz::Tz;
use thiserror::Error;

use crate::revision::{quote, AnalysisWindow, ChangedRange, FddResultIdentity, IdentityError};

/// Fixed result buckets.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BucketGrid {
    /// `[HH:00, HH+1:00)` UTC.
    UtcHour,
    /// Local midnight to local midnight in the zone.
    LocalDay(Tz),
    /// Local Monday midnight to the next local Monday midnight.
    LocalWeek(Tz),
}

impl BucketGrid {
    pub fn canonical(&self) -> String {
        match self {
            Self::UtcHour => "utc-hour".to_string(),
            Self::LocalDay(tz) => format!("local-day:{}", tz.name()),
            Self::LocalWeek(tz) => format!("local-week:{}", tz.name()),
        }
    }

    /// The bucket that holds `at`.
    pub fn bucket_containing(&self, at: DateTime<Utc>) -> Result<AnalysisWindow, IncrementalError> {
        let (start, end) = match self {
            Self::UtcHour => {
                let secs = at.timestamp().div_euclid(3600) * 3600;
                let start =
                    DateTime::from_timestamp(secs, 0).ok_or(IncrementalError::TimeOutOfRange)?;
                let end = start
                    .checked_add_signed(Duration::hours(1))
                    .ok_or(IncrementalError::TimeOutOfRange)?;
                (start, end)
            }
            Self::LocalDay(tz) => {
                let day = at.with_timezone(tz).date_naive();
                let next = day
                    .checked_add_days(Days::new(1))
                    .ok_or(IncrementalError::TimeOutOfRange)?;
                (local_day_start(tz, day)?, local_day_start(tz, next)?)
            }
            Self::LocalWeek(tz) => {
                let day = at.with_timezone(tz).date_naive();
                let monday = day
                    .checked_sub_days(Days::new(u64::from(day.weekday().num_days_from_monday())))
                    .ok_or(IncrementalError::TimeOutOfRange)?;
                let next = monday
                    .checked_add_days(Days::new(7))
                    .ok_or(IncrementalError::TimeOutOfRange)?;
                (local_day_start(tz, monday)?, local_day_start(tz, next)?)
            }
        };
        Ok(AnalysisWindow::half_open(start, end)?)
    }

    /// Buckets that share an instant with `[start, end)`, in time order.
    pub fn buckets_overlapping(
        &self,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
    ) -> Result<Vec<AnalysisWindow>, IncrementalError> {
        let mut out = Vec::new();
        if end <= start {
            return Ok(out);
        }
        let mut bucket = self.bucket_containing(start)?;
        loop {
            out.push(bucket);
            if bucket.end() >= end {
                return Ok(out);
            }
            bucket = self.bucket_containing(bucket.end())?;
        }
    }

    /// The smallest bucket-aligned window that holds `window`.
    pub fn align_outward(
        &self,
        window: AnalysisWindow,
    ) -> Result<AnalysisWindow, IncrementalError> {
        let buckets = self.buckets_overlapping(window.start(), window.end())?;
        match (buckets.first(), buckets.last()) {
            (Some(first), Some(last)) => Ok(AnalysisWindow::half_open(first.start(), last.end())?),
            _ => Err(IncrementalError::Identity(IdentityError::EmptyWindow)),
        }
    }

    fn is_aligned(&self, window: AnalysisWindow) -> Result<bool, IncrementalError> {
        Ok(self.align_outward(window)? == window)
    }
}

/// First instant of a local calendar day. When local midnight does not exist
/// (a DST jump at 00:00), the day starts at the first local time that does.
fn local_day_start(tz: &Tz, day: NaiveDate) -> Result<DateTime<Utc>, IncrementalError> {
    let mut naive = day.and_time(NaiveTime::MIN);
    for _ in 0..=96 {
        if let Some(found) = tz.from_local_datetime(&naive).earliest() {
            return Ok(found.with_timezone(&Utc));
        }
        naive = naive
            .checked_add_signed(Duration::minutes(15))
            .ok_or(IncrementalError::TimeOutOfRange)?;
    }
    Err(IncrementalError::NoLocalDayStart)
}

/// How far back from an instant a rule reads: warm-up plus confirmation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RuleHorizon {
    lookback: Duration,
}

impl RuleHorizon {
    pub fn new(warmup: Duration, confirmation: Duration) -> Result<Self, IncrementalError> {
        if warmup < Duration::zero() || confirmation < Duration::zero() {
            return Err(IncrementalError::NegativeHorizon);
        }
        let lookback = warmup
            .checked_add(&confirmation)
            .ok_or(IncrementalError::TimeOutOfRange)?;
        Ok(Self { lookback })
    }

    pub fn lookback(self) -> Duration {
        self.lookback
    }
}

/// Which results one checkpoint owns. Every identity field except the data
/// revision and the window, plus the grid and the horizon. A tune changes the
/// rule parameters, so it lands in a new scope and leaves the others alone.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResultScope {
    site_id: String,
    rule_id: String,
    equipment_id: String,
    grid: BucketGrid,
    horizon: RuleHorizon,
    canonical: String,
}

impl ResultScope {
    pub fn new(
        site_id: impl Into<String>,
        rule_id: impl Into<String>,
        equipment_id: impl Into<String>,
        identity: &FddResultIdentity,
        grid: BucketGrid,
        horizon: RuleHorizon,
    ) -> Result<Self, IncrementalError> {
        let site_id = site_id.into();
        let rule_id = rule_id.into();
        let equipment_id = equipment_id.into();
        if site_id.is_empty() || rule_id.is_empty() || equipment_id.is_empty() {
            return Err(IncrementalError::EmptyScopeField);
        }
        let mut canonical = String::from("openfdd-fdd-incremental-scope-v1\n");
        for (name, value) in [
            ("site_id", site_id.as_str()),
            ("rule_id", rule_id.as_str()),
            ("equipment_id", equipment_id.as_str()),
            ("model_revision", identity.model_revision()),
            ("pack_version", identity.pack_version()),
            ("quality_policy", identity.quality_policy().as_str()),
            ("schedule_policy", identity.schedule_policy().as_str()),
            ("grid", grid.canonical().as_str()),
        ] {
            canonical.push_str(name);
            canonical.push('=');
            canonical.push_str(&quote(value));
            canonical.push('\n');
        }
        canonical.push_str("lookback_ms=");
        canonical.push_str(&horizon.lookback().num_milliseconds().to_string());
        canonical.push('\n');
        for (name, value) in identity.rule_parameters().iter() {
            canonical.push_str("rule_parameter ");
            canonical.push_str(&quote(name));
            canonical.push('=');
            canonical.push_str(&quote(value));
            canonical.push('\n');
        }
        Ok(Self {
            site_id,
            rule_id,
            equipment_id,
            grid,
            horizon,
            canonical,
        })
    }

    pub fn site_id(&self) -> &str {
        &self.site_id
    }

    pub fn rule_id(&self) -> &str {
        &self.rule_id
    }

    pub fn equipment_id(&self) -> &str {
        &self.equipment_id
    }

    pub fn grid(&self) -> BucketGrid {
        self.grid
    }

    pub fn horizon(&self) -> RuleHorizon {
        self.horizon
    }

    pub fn canonical(&self) -> &str {
        &self.canonical
    }
}

/// One bucket's rule output.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct BucketResult {
    bucket: AnalysisWindow,
    fault_seconds: f64,
    covered_seconds: f64,
    sample_count: u64,
}

impl BucketResult {
    /// Seconds must be finite, non-negative, and fault time cannot exceed covered time.
    pub fn new(
        bucket: AnalysisWindow,
        fault_seconds: f64,
        covered_seconds: f64,
        sample_count: u64,
    ) -> Result<Self, IncrementalError> {
        let valid = fault_seconds.is_finite()
            && covered_seconds.is_finite()
            && fault_seconds >= 0.0
            && covered_seconds >= 0.0
            && fault_seconds <= covered_seconds;
        if !valid {
            return Err(IncrementalError::InvalidResult);
        }
        Ok(Self {
            bucket,
            fault_seconds,
            covered_seconds,
            sample_count,
        })
    }

    pub fn bucket(&self) -> AnalysisWindow {
        self.bucket
    }

    pub fn fault_seconds(&self) -> f64 {
        self.fault_seconds
    }

    pub fn covered_seconds(&self) -> f64 {
        self.covered_seconds
    }

    pub fn sample_count(&self) -> u64 {
        self.sample_count
    }
}

/// What a planner run reads.
#[derive(Debug, Clone, Copy)]
pub struct PlanInput<'a> {
    pub grid: BucketGrid,
    pub horizon: RuleHorizon,
    /// Must be bucket aligned. See [`BucketGrid::align_outward`].
    pub window: AnalysisWindow,
    /// Series keys the rule reads. A change to any other key is ignored.
    pub input_keys: &'a BTreeSet<String>,
    /// Revision the checkpoint already covers. `None` before the first publish.
    pub processed_revision: Option<u64>,
    /// Revision this run will publish. Ranges above it wait for the next run.
    pub through_revision: u64,
    pub ranges: &'a [ChangedRange],
    /// Bucket starts that already have a stored result.
    pub stored_buckets: &'a BTreeSet<DateTime<Utc>>,
}

/// Buckets to recompute, in time order.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IncrementalPlan {
    pub buckets: Vec<AnalysisWindow>,
    pub through_revision: u64,
    /// Every bucket in the window is recomputed (first run).
    pub full: bool,
}

/// Map changed ranges plus the rule horizon to the buckets that must be recomputed.
pub fn plan_dirty_buckets(input: PlanInput<'_>) -> Result<IncrementalPlan, IncrementalError> {
    if input.input_keys.is_empty() {
        return Err(IncrementalError::NoInputKeys);
    }
    if let Some(processed) = input.processed_revision {
        if input.through_revision < processed {
            return Err(IncrementalError::RevisionRegressed {
                processed,
                requested: input.through_revision,
            });
        }
    }
    if !input.grid.is_aligned(input.window)? {
        return Err(IncrementalError::UnalignedWindow);
    }
    let all = input
        .grid
        .buckets_overlapping(input.window.start(), input.window.end())?;
    let Some(processed) = input.processed_revision else {
        return Ok(IncrementalPlan {
            buckets: all,
            through_revision: input.through_revision,
            full: true,
        });
    };
    let mut dirty: BTreeSet<DateTime<Utc>> = all
        .iter()
        .map(|bucket| bucket.start())
        .filter(|start| !input.stored_buckets.contains(start))
        .collect();
    let lookback = input.horizon.lookback();
    for range in input.ranges {
        if range.revision <= processed || range.revision > input.through_revision {
            continue;
        }
        if !input.input_keys.contains(&range.openfdd_key) {
            continue;
        }
        let affected_end = range
            .end
            .checked_add_signed(lookback)
            .and_then(|end| end.checked_add_signed(Duration::nanoseconds(1)))
            .ok_or(IncrementalError::TimeOutOfRange)?;
        let start = range.start.max(input.window.start());
        let end = affected_end.min(input.window.end());
        for bucket in input.grid.buckets_overlapping(start, end)? {
            dirty.insert(bucket.start());
        }
    }
    let buckets = all
        .into_iter()
        .filter(|bucket| dirty.contains(&bucket.start()))
        .collect();
    Ok(IncrementalPlan {
        buckets,
        through_revision: input.through_revision,
        full: false,
    })
}

#[derive(Debug, Error)]
pub enum IncrementalError {
    #[error(transparent)]
    Identity(#[from] IdentityError),
    #[error(transparent)]
    Database(#[from] sqlx::Error),
    #[error("time is outside the supported range")]
    TimeOutOfRange,
    #[error("revision, fence, or sample count does not fit")]
    CounterOutOfRange,
    #[error("lease must be longer than zero")]
    NonPositiveLease,
    #[error("local day has no start instant")]
    NoLocalDayStart,
    #[error("rule horizon is negative")]
    NegativeHorizon,
    #[error("site, rule, or equipment id is empty")]
    EmptyScopeField,
    #[error("rule reads no series keys")]
    NoInputKeys,
    #[error("analysis window is not aligned to the bucket grid")]
    UnalignedWindow,
    #[error("bucket result seconds are invalid")]
    InvalidResult,
    #[error("checkpoint is at revision {processed}; cannot publish {requested}")]
    RevisionRegressed { processed: u64, requested: u64 },
    #[error("another run holds this checkpoint")]
    Busy,
    #[error("checkpoint fence moved from {claimed} to {current}; this run is stale")]
    StaleFence { claimed: u64, current: u64 },
    #[error("this run's checkpoint lease expired")]
    LeaseExpired,
    #[error("bucket {0} is outside the run window or not on the grid")]
    ForeignBucket(DateTime<Utc>),
    #[error("rule evaluation failed: {0}")]
    Evaluate(String),
}

/// Deterministic confirmed-fault rule and series edits used by the parity tests.
#[cfg(test)]
pub(crate) mod reference {
    use std::collections::BTreeMap;

    use chrono::{DateTime, Duration, Utc};

    use super::{BucketResult, IncrementalError};
    use crate::revision::{AnalysisWindow, ChangeKind, ChangedRange};

    pub const KEY: &str = "zone-temp";
    pub const POLL_SECS: i64 = 300;
    /// A sample is a confirmed fault when it and the previous `CONFIRM_STEPS`
    /// poll samples all exceed the limit. A missing sample breaks the streak.
    pub const CONFIRM_STEPS: i64 = 3;
    pub const LIMIT: f64 = 0.5;

    pub type Series = BTreeMap<DateTime<Utc>, f64>;

    pub fn confirmation() -> Duration {
        Duration::seconds(POLL_SECS * CONFIRM_STEPS)
    }

    fn confirmed(series: &Series, at: DateTime<Utc>) -> bool {
        (0..=CONFIRM_STEPS).all(|step| {
            series
                .get(&(at - Duration::seconds(POLL_SECS * step)))
                .is_some_and(|value| *value > LIMIT)
        })
    }

    /// Evaluate one bucket from only the samples in `[read_from, bucket.end)`.
    pub fn evaluate(
        series: &Series,
        bucket: AnalysisWindow,
        read_from: DateTime<Utc>,
    ) -> Result<BucketResult, IncrementalError> {
        let view: Series = series
            .range(read_from..bucket.end())
            .map(|(ts, value)| (*ts, *value))
            .collect();
        let mut faults = 0_i64;
        let mut samples = 0_u64;
        for ts in view.range(bucket.start()..bucket.end()).map(|(ts, _)| *ts) {
            samples += 1;
            if confirmed(&view, ts) {
                faults += 1;
            }
        }
        let poll = POLL_SECS as f64;
        BucketResult::new(bucket, faults as f64 * poll, samples as f64 * poll, samples)
    }

    /// Whole-window answer with the full series in view. Independent of buckets.
    pub fn window_fault_seconds(series: &Series, window: AnalysisWindow) -> f64 {
        let faults = series
            .range(window.start()..window.end())
            .filter(|(ts, _)| confirmed(series, **ts))
            .count();
        faults as f64 * POLL_SECS as f64
    }

    /// Small LCG so the tests are deterministic without a rand dependency.
    pub struct Lcg(u64);

    impl Lcg {
        pub fn new(seed: u64) -> Self {
            Self(seed)
        }

        pub fn next(&mut self) -> u64 {
            self.0 = self
                .0
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            self.0 >> 33
        }

        pub fn below(&mut self, n: u64) -> u64 {
            self.next() % n.max(1)
        }
    }

    /// Runs of high and low values on the poll grid.
    pub fn seed_series(window: AnalysisWindow, rng: &mut Lcg) -> Series {
        let mut series = Series::new();
        let mut ts = window.start();
        let mut high = false;
        let mut left = 0_u64;
        while ts < window.end() {
            if left == 0 {
                high = !high;
                left = 1 + rng.below(12);
            }
            series.insert(ts, if high { 1.0 } else { 0.0 });
            left -= 1;
            ts += Duration::seconds(POLL_SECS);
        }
        series
    }

    /// One revision of edits: flips, removals, and late inserts near one instant.
    pub fn edit(
        series: &mut Series,
        window: AnalysisWindow,
        revision: u64,
        rng: &mut Lcg,
    ) -> Vec<ChangedRange> {
        let span_steps = (window.end() - window.start()).num_seconds() / POLL_SECS;
        let base = rng.below(span_steps.unsigned_abs());
        let mut upserts: Vec<DateTime<Utc>> = Vec::new();
        let mut removals: Vec<DateTime<Utc>> = Vec::new();
        for offset in 0..(1 + rng.below(4)) {
            let step = i64::try_from(base + offset)
                .unwrap_or(0)
                .min(span_steps - 1);
            let ts = window.start() + Duration::seconds(step * POLL_SECS);
            match (series.get(&ts).copied(), rng.below(3)) {
                (Some(_), 0) => {
                    series.remove(&ts);
                    removals.push(ts);
                }
                (Some(value), _) => {
                    series.insert(ts, 1.0 - value);
                    upserts.push(ts);
                }
                (None, _) => {
                    series.insert(ts, 1.0);
                    upserts.push(ts);
                }
            }
        }
        let mut out = Vec::new();
        for (kind, stamps) in [
            (ChangeKind::Upsert, upserts),
            (ChangeKind::Delete, removals),
        ] {
            if let (Some(start), Some(end)) = (stamps.iter().min(), stamps.iter().max()) {
                out.push(ChangedRange {
                    site_id: "site".into(),
                    openfdd_key: KEY.into(),
                    revision,
                    start: *start,
                    end: *end,
                    kind,
                });
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use std::collections::{BTreeMap, BTreeSet};

    use chrono::{Duration, TimeZone, Utc};
    use chrono_tz::America::Chicago;

    use super::reference::{self, Lcg, Series};
    use super::*;
    use crate::revision::{ChangeKind, QualityPolicy, RuleParameters, SchedulePolicy};

    fn utc(y: i32, mo: u32, d: u32, h: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(y, mo, d, h, 0, 0).unwrap()
    }

    fn keys() -> BTreeSet<String> {
        BTreeSet::from([reference::KEY.to_string()])
    }

    fn horizon() -> RuleHorizon {
        RuleHorizon::new(Duration::zero(), reference::confirmation()).unwrap()
    }

    #[test]
    fn local_days_follow_dst_and_weeks_start_monday() {
        let spring = BucketGrid::LocalDay(Chicago)
            .bucket_containing(utc(2026, 3, 8, 12))
            .unwrap();
        assert_eq!(spring.end() - spring.start(), Duration::hours(23));
        assert_eq!(spring.start(), utc(2026, 3, 8, 6));
        let fall = BucketGrid::LocalDay(Chicago)
            .bucket_containing(utc(2026, 11, 1, 12))
            .unwrap();
        assert_eq!(fall.end() - fall.start(), Duration::hours(25));
        assert_eq!(fall.start(), utc(2026, 11, 1, 5));
        let plain = BucketGrid::LocalDay(Chicago)
            .bucket_containing(utc(2026, 11, 3, 12))
            .unwrap();
        assert_eq!(plain.end() - plain.start(), Duration::hours(24));

        let week = BucketGrid::LocalWeek(Chicago)
            .bucket_containing(utc(2026, 11, 1, 12))
            .unwrap();
        // 2026-10-26 is a Monday; that week holds the fall-back Sunday.
        assert_eq!(week.start(), utc(2026, 10, 26, 5));
        assert_eq!(week.end(), utc(2026, 11, 2, 6));
        assert_eq!(week.end() - week.start(), Duration::hours(7 * 24 + 1));

        let hour = BucketGrid::UtcHour
            .bucket_containing(Utc.with_ymd_and_hms(2026, 11, 1, 6, 59, 59).unwrap())
            .unwrap();
        assert_eq!(
            (hour.start(), hour.end()),
            (utc(2026, 11, 1, 6), utc(2026, 11, 1, 7))
        );
    }

    #[test]
    fn buckets_tile_the_window_without_gaps() {
        let window = AnalysisWindow::half_open(utc(2026, 3, 1, 3), utc(2026, 3, 20, 3)).unwrap();
        for grid in [
            BucketGrid::UtcHour,
            BucketGrid::LocalDay(Chicago),
            BucketGrid::LocalWeek(Chicago),
        ] {
            let aligned = grid.align_outward(window).unwrap();
            let buckets = grid
                .buckets_overlapping(aligned.start(), aligned.end())
                .unwrap();
            assert!(buckets.len() > 1);
            assert_eq!(buckets.first().unwrap().start(), aligned.start());
            assert_eq!(buckets.last().unwrap().end(), aligned.end());
            assert!(buckets
                .windows(2)
                .all(|pair| pair[0].end() == pair[1].start()));
            assert!(aligned.start() <= window.start() && aligned.end() >= window.end());
        }
    }

    #[test]
    fn planner_marks_the_change_and_its_lookback_only() {
        let grid = BucketGrid::UtcHour;
        let window = AnalysisWindow::half_open(utc(2026, 5, 1, 0), utc(2026, 5, 1, 6)).unwrap();
        let stored: BTreeSet<_> = grid
            .buckets_overlapping(window.start(), window.end())
            .unwrap()
            .iter()
            .map(|bucket| bucket.start())
            .collect();
        // 01:50 plus 15 minutes of confirmation reaches 02:05: buckets 01 and 02.
        let range = ChangedRange {
            site_id: "site".into(),
            openfdd_key: reference::KEY.into(),
            revision: 3,
            start: Utc.with_ymd_and_hms(2026, 5, 1, 1, 50, 0).unwrap(),
            end: Utc.with_ymd_and_hms(2026, 5, 1, 1, 50, 0).unwrap(),
            kind: ChangeKind::Upsert,
        };
        let other_key = ChangedRange {
            openfdd_key: "unused".into(),
            start: utc(2026, 5, 1, 4),
            end: utc(2026, 5, 1, 4),
            ..range.clone()
        };
        let later = ChangedRange {
            revision: 9,
            start: utc(2026, 5, 1, 5),
            end: utc(2026, 5, 1, 5),
            ..range.clone()
        };
        let ranges = [range, other_key, later];
        let input_keys = keys();
        let plan = plan_dirty_buckets(PlanInput {
            grid,
            horizon: horizon(),
            window,
            input_keys: &input_keys,
            processed_revision: Some(2),
            through_revision: 5,
            ranges: &ranges,
            stored_buckets: &stored,
        })
        .unwrap();
        let starts: Vec<_> = plan.buckets.iter().map(|bucket| bucket.start()).collect();
        assert_eq!(starts, vec![utc(2026, 5, 1, 1), utc(2026, 5, 1, 2)]);
        assert!(!plan.full);
        assert_eq!(plan.through_revision, 5);

        // A missing stored bucket is recomputed even without a change.
        let mut partial = stored;
        partial.remove(&utc(2026, 5, 1, 4));
        let plan = plan_dirty_buckets(PlanInput {
            grid,
            horizon: horizon(),
            window,
            input_keys: &input_keys,
            processed_revision: Some(2),
            through_revision: 2,
            ranges: &[],
            stored_buckets: &partial,
        })
        .unwrap();
        assert_eq!(plan.buckets.len(), 1);
        assert_eq!(plan.buckets[0].start(), utc(2026, 5, 1, 4));
    }

    #[test]
    fn planner_rejects_regressions_unaligned_windows_and_empty_inputs() {
        let grid = BucketGrid::UtcHour;
        let window = AnalysisWindow::half_open(utc(2026, 5, 1, 0), utc(2026, 5, 1, 6)).unwrap();
        let input_keys = keys();
        let stored = BTreeSet::new();
        let base = PlanInput {
            grid,
            horizon: horizon(),
            window,
            input_keys: &input_keys,
            processed_revision: Some(4),
            through_revision: 4,
            ranges: &[],
            stored_buckets: &stored,
        };
        assert!(matches!(
            plan_dirty_buckets(PlanInput {
                through_revision: 3,
                ..base
            }),
            Err(IncrementalError::RevisionRegressed { .. })
        ));
        let unaligned = AnalysisWindow::half_open(
            Utc.with_ymd_and_hms(2026, 5, 1, 0, 30, 0).unwrap(),
            utc(2026, 5, 1, 6),
        )
        .unwrap();
        assert!(matches!(
            plan_dirty_buckets(PlanInput {
                window: unaligned,
                ..base
            }),
            Err(IncrementalError::UnalignedWindow)
        ));
        let empty = BTreeSet::new();
        assert!(matches!(
            plan_dirty_buckets(PlanInput {
                input_keys: &empty,
                ..base
            }),
            Err(IncrementalError::NoInputKeys)
        ));
        assert!(matches!(
            RuleHorizon::new(Duration::seconds(-1), Duration::zero()),
            Err(IncrementalError::NegativeHorizon)
        ));
        assert!(BucketResult::new(window, 2.0, 1.0, 1).is_err());
        assert!(BucketResult::new(window, f64::NAN, 1.0, 1).is_err());
    }

    #[test]
    fn scope_changes_with_parameters_and_grid_but_not_revision_or_window() {
        let window = AnalysisWindow::half_open(utc(2026, 5, 1, 0), utc(2026, 5, 2, 0)).unwrap();
        let other_window =
            AnalysisWindow::half_open(utc(2026, 5, 1, 0), utc(2026, 5, 3, 0)).unwrap();
        let identity = |revision, window, limit: &str| {
            FddResultIdentity::new(
                revision,
                "model-a",
                RuleParameters::try_from_pairs([("limit", limit)]).unwrap(),
                "pack-1",
                window,
                QualityPolicy::DropBad,
                SchedulePolicy::Sched1,
            )
        };
        let scope = |id: &FddResultIdentity, grid| {
            ResultScope::new("site", "rule", "ahu-1", id, grid, horizon()).unwrap()
        };
        let base = scope(&identity(1, window, "0.5"), BucketGrid::UtcHour);
        assert_eq!(
            base,
            scope(&identity(9, other_window, "0.5"), BucketGrid::UtcHour)
        );
        assert_ne!(
            base,
            scope(&identity(1, window, "0.6"), BucketGrid::UtcHour)
        );
        assert_ne!(
            base,
            scope(&identity(1, window, "0.5"), BucketGrid::LocalDay(Chicago))
        );
        assert!(ResultScope::new(
            "",
            "rule",
            "ahu-1",
            &identity(1, window, "0.5"),
            BucketGrid::UtcHour,
            horizon()
        )
        .is_err());
    }

    fn evaluate_all(
        grid: BucketGrid,
        series: &Series,
        window: AnalysisWindow,
    ) -> BTreeMap<DateTime<Utc>, BucketResult> {
        grid.buckets_overlapping(window.start(), window.end())
            .unwrap()
            .into_iter()
            .map(|bucket| {
                let read_from = bucket.start() - horizon().lookback();
                (
                    bucket.start(),
                    reference::evaluate(series, bucket, read_from).unwrap(),
                )
            })
            .collect()
    }

    /// Returns the number of rounds where the incremental store matched a full
    /// recompute, and the number of buckets it recomputed in total.
    fn replay(
        grid: BucketGrid,
        window: AnalysisWindow,
        planner_horizon: RuleHorizon,
        seed: u64,
        rounds: u64,
    ) -> (u64, usize, usize) {
        let mut rng = Lcg::new(seed);
        let mut series = reference::seed_series(window, &mut rng);
        let mut stored = evaluate_all(grid, &series, window);
        let input_keys = keys();
        let mut processed = 1_u64;
        let mut matched = 0;
        let mut recomputed = 0;
        let total = stored.len();
        for round in 0..rounds {
            let revision = processed + 1 + round % 2;
            let ranges = reference::edit(&mut series, window, revision, &mut rng);
            let stored_starts: BTreeSet<_> = stored.keys().copied().collect();
            let plan = plan_dirty_buckets(PlanInput {
                grid,
                horizon: planner_horizon,
                window,
                input_keys: &input_keys,
                processed_revision: Some(processed),
                through_revision: revision,
                ranges: &ranges,
                stored_buckets: &stored_starts,
            })
            .unwrap();
            for bucket in &plan.buckets {
                let read_from = bucket.start() - horizon().lookback();
                stored.insert(
                    bucket.start(),
                    reference::evaluate(&series, *bucket, read_from).unwrap(),
                );
            }
            recomputed += plan.buckets.len();
            processed = revision;
            let full = evaluate_all(grid, &series, window);
            if full == stored {
                matched += 1;
            }
            let summed: f64 = stored.values().map(BucketResult::fault_seconds).sum();
            if planner_horizon == horizon() {
                assert_eq!(summed, reference::window_fault_seconds(&series, window));
            }
        }
        (matched, recomputed, total)
    }

    fn parity_windows() -> Vec<(BucketGrid, AnalysisWindow)> {
        vec![
            (
                BucketGrid::UtcHour,
                AnalysisWindow::half_open(utc(2026, 10, 31, 0), utc(2026, 11, 2, 0)).unwrap(),
            ),
            (
                BucketGrid::LocalDay(Chicago),
                BucketGrid::LocalDay(Chicago)
                    .align_outward(
                        AnalysisWindow::half_open(utc(2026, 3, 5, 12), utc(2026, 3, 11, 12))
                            .unwrap(),
                    )
                    .unwrap(),
            ),
            (
                BucketGrid::LocalDay(Chicago),
                BucketGrid::LocalDay(Chicago)
                    .align_outward(
                        AnalysisWindow::half_open(utc(2026, 10, 29, 12), utc(2026, 11, 4, 12))
                            .unwrap(),
                    )
                    .unwrap(),
            ),
            (
                BucketGrid::LocalWeek(Chicago),
                BucketGrid::LocalWeek(Chicago)
                    .align_outward(
                        AnalysisWindow::half_open(utc(2026, 10, 12, 12), utc(2026, 11, 20, 12))
                            .unwrap(),
                    )
                    .unwrap(),
            ),
        ]
    }

    #[test]
    fn incremental_equals_full_recompute_across_utc_day_week_and_dst() {
        for (index, (grid, window)) in parity_windows().into_iter().enumerate() {
            let rounds = 40;
            let seed = 17 + index as u64;
            let (matched, recomputed, total) = replay(grid, window, horizon(), seed, rounds);
            assert_eq!(matched, rounds, "{grid:?}");
            // Each round touches a few samples; most buckets are reused.
            assert!(recomputed < total * rounds as usize, "{grid:?}");
            let mut rng = Lcg::new(seed);
            let series = reference::seed_series(window, &mut rng);
            assert!(reference::window_fault_seconds(&series, window) > 0.0);
        }
    }

    #[test]
    fn negative_control_dropping_the_lookback_breaks_parity() {
        let (grid, window) = (
            BucketGrid::UtcHour,
            AnalysisWindow::half_open(utc(2026, 10, 31, 0), utc(2026, 11, 2, 0)).unwrap(),
        );
        let no_lookback = RuleHorizon::new(Duration::zero(), Duration::zero()).unwrap();
        let rounds = 200;
        let (matched, _, _) = replay(grid, window, no_lookback, 5, rounds);
        assert!(
            matched < rounds,
            "planner without lookback should miss a bucket"
        );
    }

    #[test]
    fn late_replacement_is_idempotent() {
        let grid = BucketGrid::UtcHour;
        let window = AnalysisWindow::half_open(utc(2026, 5, 1, 0), utc(2026, 5, 1, 4)).unwrap();
        let mut rng = Lcg::new(3);
        let mut series = reference::seed_series(window, &mut rng);
        let ranges = reference::edit(&mut series, window, 2, &mut rng);
        let input_keys = keys();
        let stored: BTreeSet<_> = grid
            .buckets_overlapping(window.start(), window.end())
            .unwrap()
            .iter()
            .map(|bucket| bucket.start())
            .collect();
        let plan = |processed| {
            plan_dirty_buckets(PlanInput {
                grid,
                horizon: horizon(),
                window,
                input_keys: &input_keys,
                processed_revision: Some(processed),
                through_revision: 2,
                ranges: &ranges,
                stored_buckets: &stored,
            })
            .unwrap()
        };
        let first = plan(1);
        assert!(!first.buckets.is_empty());
        let mut once = evaluate_all(grid, &series, window);
        for bucket in &first.buckets {
            once.insert(
                bucket.start(),
                reference::evaluate(&series, *bucket, bucket.start() - horizon().lookback())
                    .unwrap(),
            );
        }
        let mut twice = once.clone();
        for bucket in &first.buckets {
            twice.insert(
                bucket.start(),
                reference::evaluate(&series, *bucket, bucket.start() - horizon().lookback())
                    .unwrap(),
            );
        }
        assert_eq!(once, twice);
        // Once processed, the same ranges plan nothing.
        assert!(plan(2).buckets.is_empty());
    }
}
