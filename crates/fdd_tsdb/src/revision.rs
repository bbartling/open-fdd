//! Site data revision, changed sample ranges, and the FDD result identity.
//!
//! The sample writer calls [`record_bounds`] in the same transaction as the
//! sample change. A revision advances only when that change returns a row.
//! W4b (incremental FDD) reads [`current_data_revision`] and
//! [`changed_ranges_after`]. This module does not run rules.

use std::collections::BTreeMap;

use chrono::{DateTime, SecondsFormat, Utc};
use sqlx::{Postgres, Row, Transaction};
use thiserror::Error;

const REVISION_SCHEMA_SQL: &str = include_str!("../../../sql/schema/09_data_revision.sql");

/// How a stored sample moved.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ChangeKind {
    /// Insert, or an in-place correction at the same timestamp.
    Upsert,
    /// The sample row was removed.
    Delete,
}

impl ChangeKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Upsert => "upsert",
            Self::Delete => "removed",
        }
    }

    fn parse(value: &str) -> Result<Self, sqlx::Error> {
        match value {
            "upsert" => Ok(Self::Upsert),
            "removed" => Ok(Self::Delete),
            _ => Err(sqlx::Error::Protocol(
                "sample change kind is not upsert or removed".into(),
            )),
        }
    }
}

/// Inclusive timestamp span of one series at one data revision.
///
/// `start` and `end` are the earliest and latest timestamps the writer
/// changed for this series in this revision. A single sample has `start == end`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChangedRange {
    pub site_id: String,
    pub openfdd_key: String,
    pub revision: u64,
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
    pub kind: ChangeKind,
}

impl ChangedRange {
    /// Half-open analysis windows overlap this inclusive span when they share
    /// an instant. The window end itself is outside the window.
    pub fn overlaps_window(&self, window: &AnalysisWindow) -> bool {
        self.start < window.end && self.end >= window.start
    }
}

/// Which stored quality stamps are FDD inputs.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum QualityPolicy {
    /// Every stored sample is an input, including a bad stamp.
    KeepAll,
    /// A stamp of `bad` (trimmed, any case) is not an input. A missing stamp is kept.
    DropBad,
}

impl QualityPolicy {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::KeepAll => "keep-all",
            Self::DropBad => "drop-bad",
        }
    }
}

/// `true` when this policy keeps the sample as an FDD input.
pub fn quality_keeps_sample(policy: QualityPolicy, quality: Option<&str>) -> bool {
    let stamp = quality.map(str::trim).unwrap_or("");
    if stamp.eq_ignore_ascii_case(crate::ingest_si::QUALITY_UNIT_UNDECLARED) {
        return false;
    }
    match policy {
        QualityPolicy::KeepAll => true,
        QualityPolicy::DropBad => !stamp.eq_ignore_ascii_case("bad"),
    }
}

/// How an occupancy sample is read.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum SchedulePolicy {
    /// Numeric values at or below 0.05, and the unoccupied token family, are unoccupied.
    ///
    /// Tokens, compared after trim and ASCII lower-case: `unoccupied`, `unocc`,
    /// `off`, `false`, `night`, `standby`, `setback`, `no`. This is the SCHED-1
    /// occupancy reading. It does not decide fan-on fault time.
    Sched1,
}

impl SchedulePolicy {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Sched1 => "sched1",
        }
    }
}

const SCHED1_UNOCCUPIED_TOKENS: &[&str] = &[
    "unoccupied",
    "unocc",
    "off",
    "false",
    "night",
    "standby",
    "setback",
    "no",
];

/// SCHED-1 occupancy: unoccupied tokens, or a number at or below 0.05.
pub fn sched1_unoccupied(raw: &str) -> bool {
    let token = raw.trim();
    if token.is_empty() {
        return false;
    }
    let lower = token.to_ascii_lowercase();
    if SCHED1_UNOCCUPIED_TOKENS.contains(&lower.as_str()) {
        return true;
    }
    matches!(lower.parse::<f64>(), Ok(value) if value <= 0.05)
}

/// Half-open analysis window `[start, end)`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AnalysisWindow {
    start: DateTime<Utc>,
    end: DateTime<Utc>,
}

impl AnalysisWindow {
    pub fn half_open(start: DateTime<Utc>, end: DateTime<Utc>) -> Result<Self, IdentityError> {
        if end <= start {
            return Err(IdentityError::EmptyWindow);
        }
        Ok(Self { start, end })
    }

    pub fn start(self) -> DateTime<Utc> {
        self.start
    }

    pub fn end(self) -> DateTime<Utc> {
        self.end
    }
}

/// Inclusive start and end of changed timestamps for one series.
pub(crate) type SeriesSpan = (DateTime<Utc>, DateTime<Utc>);

/// Changed spans grouped by site, then by series key.
pub(crate) type ChangeBounds = BTreeMap<String, BTreeMap<String, SeriesSpan>>;

/// Rule parameters. Names are unique. Order does not change identity.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RuleParameters {
    pairs: BTreeMap<String, String>,
}

impl RuleParameters {
    pub fn try_from_pairs<I, K, V>(pairs: I) -> Result<Self, IdentityError>
    where
        I: IntoIterator<Item = (K, V)>,
        K: Into<String>,
        V: Into<String>,
    {
        let mut map = BTreeMap::new();
        for (name, value) in pairs {
            let name = name.into();
            if name.is_empty() {
                return Err(IdentityError::EmptyParameterName);
            }
            if map.insert(name, value.into()).is_some() {
                return Err(IdentityError::DuplicateParameter);
            }
        }
        Ok(Self { pairs: map })
    }

    pub fn get(&self, name: &str) -> Option<&str> {
        self.pairs.get(name).map(String::as_str)
    }

    pub fn iter(&self) -> impl Iterator<Item = (&str, &str)> {
        self.pairs
            .iter()
            .map(|(name, value)| (name.as_str(), value.as_str()))
    }
}

/// One FDD result. Two runs are the same computation when every field matches.
///
/// The fields are the data revision, the model revision, the rule parameters,
/// the pack version, the half-open window, and the quality and schedule
/// policies. [`Self::canonical`] is that identity in a stable order. It is not
/// a fingerprint of sample values.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FddResultIdentity {
    data_revision: u64,
    model_revision: String,
    rule_parameters: RuleParameters,
    pack_version: String,
    window: AnalysisWindow,
    quality_policy: QualityPolicy,
    schedule_policy: SchedulePolicy,
}

impl FddResultIdentity {
    pub fn new(
        data_revision: u64,
        model_revision: impl Into<String>,
        rule_parameters: RuleParameters,
        pack_version: impl Into<String>,
        window: AnalysisWindow,
        quality_policy: QualityPolicy,
        schedule_policy: SchedulePolicy,
    ) -> Self {
        Self {
            data_revision,
            model_revision: model_revision.into(),
            rule_parameters,
            pack_version: pack_version.into(),
            window,
            quality_policy,
            schedule_policy,
        }
    }

    pub fn data_revision(&self) -> u64 {
        self.data_revision
    }

    pub fn model_revision(&self) -> &str {
        &self.model_revision
    }

    pub fn rule_parameters(&self) -> &RuleParameters {
        &self.rule_parameters
    }

    pub fn pack_version(&self) -> &str {
        &self.pack_version
    }

    pub fn window(&self) -> AnalysisWindow {
        self.window
    }

    pub fn quality_policy(&self) -> QualityPolicy {
        self.quality_policy
    }

    pub fn schedule_policy(&self) -> SchedulePolicy {
        self.schedule_policy
    }

    pub fn canonical(&self) -> String {
        let mut out = String::from("openfdd-fdd-result-identity-v1\n");
        out.push_str("data_revision=");
        out.push_str(&self.data_revision.to_string());
        out.push('\n');
        push_field(&mut out, "model_revision", &self.model_revision);
        push_field(&mut out, "pack_version", &self.pack_version);
        push_field(
            &mut out,
            "window_start",
            &self
                .window
                .start
                .to_rfc3339_opts(SecondsFormat::AutoSi, true),
        );
        push_field(
            &mut out,
            "window_end",
            &self.window.end.to_rfc3339_opts(SecondsFormat::AutoSi, true),
        );
        push_field(&mut out, "quality_policy", self.quality_policy.as_str());
        push_field(&mut out, "schedule_policy", self.schedule_policy.as_str());
        for (name, value) in &self.rule_parameters.pairs {
            out.push_str("rule_parameter ");
            out.push_str(&quote(name));
            out.push('=');
            out.push_str(&quote(value));
            out.push('\n');
        }
        out
    }
}

fn push_field(out: &mut String, name: &str, value: &str) {
    out.push_str(name);
    out.push('=');
    out.push_str(&quote(value));
    out.push('\n');
}

pub(crate) fn quote(value: &str) -> String {
    let mut out = String::from("\"");
    for ch in value.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            _ => out.push(ch),
        }
    }
    out.push('"');
    out
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum IdentityError {
    #[error("analysis window end must be after start")]
    EmptyWindow,
    #[error("rule parameter name is empty")]
    EmptyParameterName,
    #[error("rule parameter name is repeated")]
    DuplicateParameter,
}

/// Latest committed data revision for `site_id`. Zero when the site has had no change.
pub async fn current_data_revision<'e, E>(executor: E, site_id: &str) -> Result<u64, sqlx::Error>
where
    E: sqlx::Executor<'e, Database = Postgres>,
{
    let value: Option<i64> =
        sqlx::query_scalar("SELECT revision FROM data_revision WHERE site_id = $1")
            .bind(site_id)
            .fetch_optional(executor)
            .await?;
    match value {
        None => Ok(0),
        Some(revision) => nonneg_revision(revision),
    }
}

/// Changed ranges with a revision strictly greater than `after_revision`.
pub async fn changed_ranges_after<'e, E>(
    executor: E,
    site_id: &str,
    after_revision: u64,
) -> Result<Vec<ChangedRange>, sqlx::Error>
where
    E: sqlx::Executor<'e, Database = Postgres>,
{
    let after = revision_to_db(after_revision)?;
    let rows = sqlx::query(
        "SELECT openfdd_key, revision, range_start, range_end, change_kind
         FROM sample_changed_range
         WHERE site_id = $1 AND revision > $2
         ORDER BY revision, openfdd_key, change_kind",
    )
    .bind(site_id)
    .bind(after)
    .fetch_all(executor)
    .await?;
    let mut ranges = Vec::with_capacity(rows.len());
    for row in &rows {
        let revision: i64 = row.try_get("revision")?;
        let kind: String = row.try_get("change_kind")?;
        ranges.push(ChangedRange {
            site_id: site_id.to_string(),
            openfdd_key: row.try_get("openfdd_key")?,
            revision: nonneg_revision(revision)?,
            start: row.try_get("range_start")?,
            end: row.try_get("range_end")?,
            kind: ChangeKind::parse(&kind)?,
        });
    }
    Ok(ranges)
}

/// Create the revision tables when this database has not applied startup SQL.
pub async fn ensure_revision_schema(pool: &sqlx::PgPool) -> Result<(), sqlx::Error> {
    let mut tx = pool.begin().await?;
    ensure_revision_schema_tx(&mut tx).await?;
    tx.commit().await?;
    Ok(())
}

pub(crate) fn fold_bound(
    bounds: &mut ChangeBounds,
    site_id: &str,
    openfdd_key: &str,
    ts: DateTime<Utc>,
) {
    if let Some(series) = bounds.get_mut(site_id) {
        if let Some((start, end)) = series.get_mut(openfdd_key) {
            if ts < *start {
                *start = ts;
            }
            if ts > *end {
                *end = ts;
            }
        } else {
            series.insert(openfdd_key.to_string(), (ts, ts));
        }
    } else {
        let mut series = BTreeMap::new();
        series.insert(openfdd_key.to_string(), (ts, ts));
        bounds.insert(site_id.to_string(), series);
    }
}

/// Advance one revision per site that has a span, and store those spans.
///
/// Call this in the same transaction as the sample write. An empty map does nothing.
pub(crate) async fn record_bounds(
    tx: &mut Transaction<'_, Postgres>,
    kind: ChangeKind,
    bounds: &ChangeBounds,
) -> Result<(), sqlx::Error> {
    if bounds.is_empty() {
        return Ok(());
    }
    ensure_revision_schema_tx(tx).await?;
    for (site_id, series) in bounds {
        let revision = advance_revision(tx, site_id).await?;
        insert_ranges(tx, site_id, revision, kind, series).await?;
    }
    Ok(())
}

pub fn schema_statements(sql: &'static str) -> impl Iterator<Item = &'static str> {
    sql.split(';').map(str::trim).filter(|statement| {
        statement.lines().any(|line| {
            let code = match line.split_once("--") {
                Some((code, _)) => code,
                None => line,
            };
            !code.trim().is_empty()
        })
    })
}

async fn ensure_revision_schema_tx(tx: &mut Transaction<'_, Postgres>) -> Result<(), sqlx::Error> {
    let ready: bool = sqlx::query_scalar(
        "SELECT to_regclass('public.data_revision') IS NOT NULL
            AND to_regclass('public.sample_changed_range') IS NOT NULL",
    )
    .fetch_one(&mut **tx)
    .await?;
    if ready {
        return Ok(());
    }
    for statement in schema_statements(REVISION_SCHEMA_SQL) {
        sqlx::query("SAVEPOINT openfdd_revision_ddl")
            .execute(&mut **tx)
            .await?;
        match sqlx::query(statement).execute(&mut **tx).await {
            Ok(_) => {
                sqlx::query("RELEASE SAVEPOINT openfdd_revision_ddl")
                    .execute(&mut **tx)
                    .await?;
            }
            Err(err) if ignorable_catalog_race(&err) => {
                sqlx::query("ROLLBACK TO SAVEPOINT openfdd_revision_ddl")
                    .execute(&mut **tx)
                    .await?;
                sqlx::query("RELEASE SAVEPOINT openfdd_revision_ddl")
                    .execute(&mut **tx)
                    .await?;
            }
            Err(err) => return Err(err),
        }
    }
    Ok(())
}

pub(crate) fn ignorable_catalog_race(err: &sqlx::Error) -> bool {
    err.as_database_error()
        .and_then(|db| db.code())
        .is_some_and(|code| code == "42P07" || code == "42710" || code == "23505")
}

async fn advance_revision(
    tx: &mut Transaction<'_, Postgres>,
    site_id: &str,
) -> Result<i64, sqlx::Error> {
    sqlx::query(
        "INSERT INTO data_revision (site_id, revision) VALUES ($1, 0)
         ON CONFLICT (site_id) DO NOTHING",
    )
    .bind(site_id)
    .execute(&mut **tx)
    .await?;
    let current: i64 =
        sqlx::query_scalar("SELECT revision FROM data_revision WHERE site_id = $1 FOR UPDATE")
            .bind(site_id)
            .fetch_one(&mut **tx)
            .await?;
    let next = current
        .checked_add(1)
        .ok_or_else(|| sqlx::Error::Protocol("data revision overflowed bigint".into()))?;
    sqlx::query("UPDATE data_revision SET revision = $2, updated_at = now() WHERE site_id = $1")
        .bind(site_id)
        .bind(next)
        .execute(&mut **tx)
        .await?;
    Ok(next)
}

async fn insert_ranges(
    tx: &mut Transaction<'_, Postgres>,
    site_id: &str,
    revision: i64,
    kind: ChangeKind,
    series: &BTreeMap<String, SeriesSpan>,
) -> Result<(), sqlx::Error> {
    let mut keys = Vec::with_capacity(series.len());
    let mut starts = Vec::with_capacity(series.len());
    let mut ends = Vec::with_capacity(series.len());
    for (key, (start, end)) in series {
        keys.push(key.as_str());
        starts.push(*start);
        ends.push(*end);
    }
    sqlx::query(
        "INSERT INTO sample_changed_range
           (site_id, openfdd_key, revision, range_start, range_end, change_kind)
         SELECT $1, key, $2, range_start, range_end, $3
         FROM UNNEST($4::text[], $5::timestamptz[], $6::timestamptz[])
           AS changed(key, range_start, range_end)",
    )
    .bind(site_id)
    .bind(revision)
    .bind(kind.as_str())
    .bind(&keys)
    .bind(&starts)
    .bind(&ends)
    .execute(&mut **tx)
    .await?;
    Ok(())
}

fn nonneg_revision(value: i64) -> Result<u64, sqlx::Error> {
    u64::try_from(value).map_err(|_| sqlx::Error::Protocol("data revision is negative".into()))
}

fn revision_to_db(value: u64) -> Result<i64, sqlx::Error> {
    i64::try_from(value)
        .map_err(|_| sqlx::Error::Protocol("data revision does not fit bigint".into()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn window() -> AnalysisWindow {
        AnalysisWindow::half_open(
            Utc.with_ymd_and_hms(2024, 3, 1, 0, 0, 0).unwrap(),
            Utc.with_ymd_and_hms(2024, 3, 8, 0, 0, 0).unwrap(),
        )
        .unwrap()
    }

    fn identity(data_revision: u64, model: &str) -> FddResultIdentity {
        FddResultIdentity::new(
            data_revision,
            model,
            RuleParameters::try_from_pairs([("confirm_min", "15"), ("zone_t_hi", "76")]).unwrap(),
            "openfdd-postgres-pack-1",
            window(),
            QualityPolicy::DropBad,
            SchedulePolicy::Sched1,
        )
    }

    #[test]
    fn identity_tracks_each_component_and_parameter_order() {
        let base = identity(4, "model-a");
        let reordered = FddResultIdentity::new(
            4,
            "model-a",
            RuleParameters::try_from_pairs([("zone_t_hi", "76"), ("confirm_min", "15")]).unwrap(),
            "openfdd-postgres-pack-1",
            window(),
            QualityPolicy::DropBad,
            SchedulePolicy::Sched1,
        );
        assert_eq!(base, reordered);
        assert_eq!(base.canonical(), reordered.canonical());
        assert!(base.canonical().contains("data_revision=4\n"));
        assert!(base.canonical().contains("quality_policy=\"drop-bad\"\n"));
        assert!(base.canonical().contains("schedule_policy=\"sched1\"\n"));

        assert_ne!(base, identity(5, "model-a"));
        assert_ne!(base, identity(4, "model-b"));
        let other_pack = FddResultIdentity::new(
            4,
            "model-a",
            base.rule_parameters().clone(),
            "openfdd-postgres-pack-2",
            window(),
            QualityPolicy::DropBad,
            SchedulePolicy::Sched1,
        );
        assert_ne!(base, other_pack);
        let other_quality = FddResultIdentity::new(
            4,
            "model-a",
            base.rule_parameters().clone(),
            "openfdd-postgres-pack-1",
            window(),
            QualityPolicy::KeepAll,
            SchedulePolicy::Sched1,
        );
        assert_ne!(base, other_quality);
        let later = AnalysisWindow::half_open(
            window().start(),
            Utc.with_ymd_and_hms(2024, 3, 9, 0, 0, 0).unwrap(),
        )
        .unwrap();
        let other_window = FddResultIdentity::new(
            4,
            "model-a",
            base.rule_parameters().clone(),
            "openfdd-postgres-pack-1",
            later,
            QualityPolicy::DropBad,
            SchedulePolicy::Sched1,
        );
        assert_ne!(base, other_window);
    }

    #[test]
    fn identity_rejects_an_empty_window_and_a_bad_parameter() {
        let start = Utc.with_ymd_and_hms(2024, 3, 1, 0, 0, 0).unwrap();
        assert_eq!(
            AnalysisWindow::half_open(start, start),
            Err(IdentityError::EmptyWindow)
        );
        assert_eq!(
            RuleParameters::try_from_pairs([("", "1")]).unwrap_err(),
            IdentityError::EmptyParameterName
        );
        assert_eq!(
            RuleParameters::try_from_pairs([("confirm_min", "1"), ("confirm_min", "2")])
                .unwrap_err(),
            IdentityError::DuplicateParameter
        );
    }

    #[test]
    fn canonical_escapes_model_text() {
        let id = identity(1, "line\n\"quote\"");
        let text = id.canonical();
        assert!(text.contains("model_revision=\"line\\n\\\"quote\\\"\"\n"));
    }

    #[test]
    fn schedule_and_quality_policies_match_the_stated_rules() {
        use crate::ingest_si::QUALITY_UNIT_UNDECLARED;
        assert!(!quality_keeps_sample(
            QualityPolicy::DropBad,
            Some(QUALITY_UNIT_UNDECLARED)
        ));
        assert!(!quality_keeps_sample(
            QualityPolicy::KeepAll,
            Some(QUALITY_UNIT_UNDECLARED)
        ));
        for token in [
            "unoccupied",
            " Unoccupied ",
            "0",
            "0.0",
            "false",
            "off",
            "0.05",
        ] {
            assert!(sched1_unoccupied(token), "{token}");
        }
        for token in ["", "occupied", "1", "0.06", "true"] {
            assert!(!sched1_unoccupied(token), "{token}");
        }
        assert!(quality_keeps_sample(QualityPolicy::DropBad, None));
        assert!(quality_keeps_sample(QualityPolicy::DropBad, Some("good")));
        assert!(!quality_keeps_sample(QualityPolicy::DropBad, Some(" bad ")));
        assert!(quality_keeps_sample(QualityPolicy::KeepAll, Some("bad")));
    }

    #[test]
    fn changed_range_overlap_uses_the_half_open_window() {
        let span = ChangedRange {
            site_id: "site".into(),
            openfdd_key: "series".into(),
            revision: 2,
            start: window().end(),
            end: window().end(),
            kind: ChangeKind::Upsert,
        };
        assert!(!span.overlaps_window(&window()));
        let inside = ChangedRange {
            start: window().start(),
            end: window().start(),
            ..span
        };
        assert!(inside.overlaps_window(&window()));
    }

    fn test_database_url() -> Option<String> {
        std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
    }

    async fn prepare(pool: &sqlx::PgPool) {
        for ddl in [
            "CREATE TABLE IF NOT EXISTS sample (
                ts timestamptz NOT NULL,
                site_id text NOT NULL,
                openfdd_key text NOT NULL,
                haystack_id text,
                val double precision,
                unit text,
                quality text,
                PRIMARY KEY (site_id, openfdd_key, ts)
            )",
            "ALTER TABLE sample ADD COLUMN IF NOT EXISTS haystack_id text",
            "ALTER TABLE sample ADD COLUMN IF NOT EXISTS unit text",
            "ALTER TABLE sample ADD COLUMN IF NOT EXISTS quality text",
            "CREATE TABLE IF NOT EXISTS sample_import_stage (
                import_id uuid NOT NULL,
                ts timestamptz NOT NULL,
                site_id text NOT NULL,
                openfdd_key text NOT NULL,
                haystack_id text,
                val double precision,
                PRIMARY KEY (import_id, site_id, openfdd_key, ts)
            )",
        ] {
            if let Err(err) = sqlx::query(ddl).execute(pool).await {
                assert!(ignorable_catalog_race(&err), "{ddl}: {err}");
            }
        }
        ensure_revision_schema(pool).await.unwrap();
    }

    async fn connect() -> Option<sqlx::PgPool> {
        let url = test_database_url()?;
        let pool = sqlx::postgres::PgPoolOptions::new()
            .max_connections(8)
            .connect(&url)
            .await
            .unwrap();
        prepare(&pool).await;
        Some(pool)
    }

    fn ts(hour: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2024, 6, 1, hour, 0, 0).unwrap()
    }

    fn row<'a>(site: &'a str, key: &'a str, hour: u32, val: f64) -> crate::writer::SampleWrite<'a> {
        crate::writer::SampleWrite {
            ts: ts(hour),
            site_id: site,
            openfdd_key: key,
            haystack_id: None,
            val: Some(val),
            unit: None,
            quality: None,
        }
    }

    async fn cleanup(pool: &sqlx::PgPool, site: &str) {
        for sql in [
            "DELETE FROM sample_changed_range WHERE site_id = $1",
            "DELETE FROM data_revision WHERE site_id = $1",
            "DELETE FROM sample WHERE site_id = $1",
            "DELETE FROM sample_import_stage WHERE site_id = $1",
        ] {
            sqlx::query(sql).bind(site).execute(pool).await.unwrap();
        }
    }

    async fn revision_of(pool: &sqlx::PgPool, site: &str) -> u64 {
        current_data_revision(pool, site).await.unwrap()
    }

    async fn ranges_of(pool: &sqlx::PgPool, site: &str) -> Vec<ChangedRange> {
        changed_ranges_after(pool, site, 0).await.unwrap()
    }

    #[tokio::test]
    async fn identical_replay_does_not_advance_revision() {
        let Some(pool) = connect().await else {
            return;
        };
        let site = format!("rev-{}", uuid::Uuid::new_v4().simple());
        let rows = [
            row(&site, "series-a", 0, 55.0),
            row(&site, "series-b", 1, 70.0),
        ];
        let mut tx = pool.begin().await.unwrap();
        let first = crate::writer::write_samples(&mut tx, &rows).await.unwrap();
        tx.commit().await.unwrap();
        assert_eq!((first.inserted, first.updated, first.unchanged), (2, 0, 0));
        assert_eq!(revision_of(&pool, &site).await, 1);
        let after_first = ranges_of(&pool, &site).await;
        assert_eq!(after_first.len(), 2);

        let mut tx = pool.begin().await.unwrap();
        let replay = crate::writer::write_samples(&mut tx, &rows).await.unwrap();
        tx.commit().await.unwrap();
        assert_eq!(
            (replay.inserted, replay.updated, replay.unchanged),
            (0, 0, 2)
        );
        assert_eq!(revision_of(&pool, &site).await, 1);
        assert_eq!(ranges_of(&pool, &site).await, after_first);
        cleanup(&pool, &site).await;
    }

    #[tokio::test]
    async fn same_timestamp_correction_advances_revision_and_records_the_range() {
        let Some(pool) = connect().await else {
            return;
        };
        let site = format!("rev-{}", uuid::Uuid::new_v4().simple());
        let original = [row(&site, "series-a", 0, 55.0)];
        let mut tx = pool.begin().await.unwrap();
        crate::writer::write_samples(&mut tx, &original)
            .await
            .unwrap();
        tx.commit().await.unwrap();

        let mut tx = pool.begin().await.unwrap();
        let replay = crate::writer::write_samples(&mut tx, &original)
            .await
            .unwrap();
        tx.commit().await.unwrap();
        assert_eq!(replay.unchanged, 1);

        let corrected = [row(&site, "series-a", 0, 56.0)];
        let mut tx = pool.begin().await.unwrap();
        let wrote = crate::writer::write_samples(&mut tx, &corrected)
            .await
            .unwrap();
        tx.commit().await.unwrap();
        assert_eq!((wrote.inserted, wrote.updated, wrote.unchanged), (0, 1, 0));

        let (count, max_ts): (i64, DateTime<Utc>) =
            sqlx::query_as("SELECT count(*)::bigint, max(ts) FROM sample WHERE site_id = $1")
                .bind(&site)
                .fetch_one(&pool)
                .await
                .unwrap();
        assert_eq!(count, 1, "a correction does not change the row count");
        assert_eq!(
            max_ts,
            ts(0),
            "a correction does not move the max timestamp"
        );
        assert_eq!(revision_of(&pool, &site).await, 2);

        let ranges = ranges_of(&pool, &site).await;
        assert_eq!(ranges.len(), 2);
        let correction = ranges.iter().find(|range| range.revision == 2).unwrap();
        assert_eq!(correction.openfdd_key, "series-a");
        assert_eq!(correction.start, ts(0));
        assert_eq!(correction.end, ts(0));
        assert_eq!(correction.kind, ChangeKind::Upsert);
        let stored: f64 = sqlx::query_scalar("SELECT val FROM sample WHERE site_id = $1")
            .bind(&site)
            .fetch_one(&pool)
            .await
            .unwrap();
        assert_eq!(stored, 56.0);
        cleanup(&pool, &site).await;
    }

    #[tokio::test]
    async fn delete_advances_revision_and_records_the_removed_timestamp() {
        let Some(pool) = connect().await else {
            return;
        };
        let site = format!("rev-{}", uuid::Uuid::new_v4().simple());
        let rows = [
            row(&site, "series-a", 0, 1.0),
            row(&site, "series-a", 3, 2.0),
        ];
        let mut tx = pool.begin().await.unwrap();
        crate::writer::write_samples(&mut tx, &rows).await.unwrap();
        tx.commit().await.unwrap();
        assert_eq!(revision_of(&pool, &site).await, 1);

        let mut tx = pool.begin().await.unwrap();
        let removed = crate::writer::delete_samples(
            &mut tx,
            crate::writer::DeleteScope::Samples(&[crate::writer::SampleDelete {
                site_id: &site,
                openfdd_key: "series-a",
                ts: ts(0),
            }]),
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();
        assert_eq!(removed, 1);

        let max_ts: DateTime<Utc> =
            sqlx::query_scalar("SELECT max(ts) FROM sample WHERE site_id = $1")
                .bind(&site)
                .fetch_one(&pool)
                .await
                .unwrap();
        assert_eq!(
            max_ts,
            ts(3),
            "removing the earlier sample leaves the max timestamp"
        );
        assert_eq!(revision_of(&pool, &site).await, 2);
        let deletion = ranges_of(&pool, &site)
            .await
            .into_iter()
            .find(|range| range.revision == 2)
            .unwrap();
        assert_eq!(deletion.kind, ChangeKind::Delete);
        assert_eq!(deletion.start, ts(0));
        assert_eq!(deletion.end, ts(0));
        assert_eq!(deletion.openfdd_key, "series-a");

        let mut tx = pool.begin().await.unwrap();
        let again = crate::writer::delete_samples(
            &mut tx,
            crate::writer::DeleteScope::Samples(&[crate::writer::SampleDelete {
                site_id: &site,
                openfdd_key: "series-a",
                ts: ts(0),
            }]),
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();
        assert_eq!(again, 0);
        assert_eq!(revision_of(&pool, &site).await, 2);

        let mut tx = pool.begin().await.unwrap();
        let by_key = crate::writer::delete_samples(
            &mut tx,
            crate::writer::DeleteScope::Keys {
                site_id: &site,
                openfdd_keys: &["series-a"],
            },
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();
        assert_eq!(by_key, 1);
        assert_eq!(revision_of(&pool, &site).await, 3);
        let key_range = ranges_of(&pool, &site)
            .await
            .into_iter()
            .find(|range| range.revision == 3)
            .unwrap();
        assert_eq!(key_range.kind, ChangeKind::Delete);
        assert_eq!(key_range.start, ts(3));
        assert_eq!(key_range.end, ts(3));
        cleanup(&pool, &site).await;
    }

    #[tokio::test]
    async fn package_replay_records_only_real_changes() {
        let Some(pool) = connect().await else {
            return;
        };
        let site = format!("rev-{}", uuid::Uuid::new_v4().simple());
        let rows = [
            row(&site, "series-a", 0, 10.0),
            row(&site, "series-b", 0, 20.0),
        ];
        let mut tx = pool.begin().await.unwrap();
        crate::writer::write_samples(&mut tx, &rows).await.unwrap();
        tx.commit().await.unwrap();

        let import_id = uuid::Uuid::new_v4();
        sqlx::query(
            "INSERT INTO sample_import_stage (import_id, ts, site_id, openfdd_key, val)
             VALUES ($1, $2, $3, 'series-a', 10.0), ($1, $2, $3, 'series-b', 20.0)",
        )
        .bind(import_id)
        .bind(ts(0))
        .bind(&site)
        .execute(&pool)
        .await
        .unwrap();
        let mut tx = pool.begin().await.unwrap();
        let deleted = crate::writer::delete_samples_outside_stage(&mut tx, import_id, &site)
            .await
            .unwrap();
        let promoted = crate::writer::promote_stage(&mut tx, import_id, &site)
            .await
            .unwrap();
        tx.commit().await.unwrap();
        assert_eq!(deleted, 0);
        assert_eq!(promoted, 0);
        assert_eq!(revision_of(&pool, &site).await, 1);

        let correction = uuid::Uuid::new_v4();
        sqlx::query(
            "INSERT INTO sample_import_stage (import_id, ts, site_id, openfdd_key, val)
             VALUES ($1, $2, $3, 'series-a', 11.0)",
        )
        .bind(correction)
        .bind(ts(0))
        .bind(&site)
        .execute(&pool)
        .await
        .unwrap();
        let mut tx = pool.begin().await.unwrap();
        let deleted = crate::writer::delete_samples_outside_stage(&mut tx, correction, &site)
            .await
            .unwrap();
        let promoted = crate::writer::promote_stage(&mut tx, correction, &site)
            .await
            .unwrap();
        tx.commit().await.unwrap();
        assert_eq!(deleted, 1, "the series left out of the stage is removed");
        assert_eq!(promoted, 1, "the corrected series is rewritten");
        assert_eq!(revision_of(&pool, &site).await, 3);
        let ranges = ranges_of(&pool, &site).await;
        assert!(ranges.iter().any(|range| {
            range.revision > 1
                && range.kind == ChangeKind::Delete
                && range.openfdd_key == "series-b"
        }));
        assert!(ranges.iter().any(|range| {
            range.revision > 1
                && range.kind == ChangeKind::Upsert
                && range.openfdd_key == "series-a"
                && range.start == ts(0)
        }));
        cleanup(&pool, &site).await;
    }

    #[tokio::test]
    async fn concurrent_writers_keep_gap_free_revisions() {
        let Some(pool) = connect().await else {
            return;
        };
        let site = format!("rev-{}", uuid::Uuid::new_v4().simple());
        let pool = std::sync::Arc::new(pool);

        let mut distinct = Vec::new();
        for index in 0..8 {
            let pool = std::sync::Arc::clone(&pool);
            let site = site.clone();
            distinct.push(tokio::spawn(async move {
                let key = format!("series-{index}");
                let rows = [row(&site, &key, 0, index as f64)];
                let mut tx = pool.begin().await.unwrap();
                crate::writer::write_samples(&mut tx, &rows).await.unwrap();
                tx.commit().await.unwrap();
            }));
        }
        for task in distinct {
            task.await.unwrap();
        }
        assert_eq!(revision_of(&pool, &site).await, 8);
        let mut revisions: Vec<u64> = ranges_of(&pool, &site)
            .await
            .into_iter()
            .map(|range| range.revision)
            .collect();
        revisions.sort_unstable();
        assert_eq!(revisions, (1..=8).collect::<Vec<_>>());

        let mut corrections = Vec::new();
        for value in 1..=6 {
            let pool = std::sync::Arc::clone(&pool);
            let site = site.clone();
            corrections.push(tokio::spawn(async move {
                let rows = [row(&site, "series-0", 0, value as f64)];
                let mut tx = pool.begin().await.unwrap();
                crate::writer::write_samples(&mut tx, &rows).await.unwrap();
                tx.commit().await.unwrap();
            }));
        }
        for task in corrections {
            task.await.unwrap();
        }
        let revision = revision_of(&pool, &site).await;
        assert_eq!(
            revision, 14,
            "each distinct correction takes the next revision"
        );
        let stored: f64 = sqlx::query_scalar(
            "SELECT val FROM sample WHERE site_id = $1 AND openfdd_key = 'series-0'",
        )
        .bind(&site)
        .fetch_one(&*pool)
        .await
        .unwrap();
        assert!((1.0..=6.0).contains(&stored), "{stored}");
        let ranges = ranges_of(&pool, &site).await;
        let mut seen: Vec<u64> = ranges.iter().map(|range| range.revision).collect();
        seen.sort_unstable();
        seen.dedup();
        assert_eq!(seen, (1..=revision).collect::<Vec<_>>());
        assert_eq!(ranges.len(), revision as usize);
        cleanup(&pool, &site).await;
    }
}
