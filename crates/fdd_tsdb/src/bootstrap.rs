//! Forward-only Timescale schema bootstrap.
//!
//! Startup creates missing relations and never drops, truncates, deletes, or
//! reseeds. An initialized database (relations present, even with zero sample
//! rows) is an existing instance and is left intact. Destructive resets are a
//! separate decision and require `OPENFDD_ALLOW_DESTRUCTIVE_DB`.

use std::env;
use std::time::Duration;

use sqlx::postgres::PgPoolOptions;
use sqlx::{PgPool, Row};
use thiserror::Error;

pub const PROBE_RELATIONS_SQL: &str = "\
SELECT table_name \
FROM information_schema.tables \
WHERE table_schema = 'public' \
  AND table_name IN ('sample', 'site', 'building', 'equipment', 'seed_meta')";

pub const PROBE_SAMPLE_ROW_SQL: &str = "SELECT EXISTS (SELECT 1 FROM sample LIMIT 1)";

#[derive(Debug, Error)]
pub enum BootstrapError {
    #[error("timescale bootstrap could not connect; database was not modified")]
    Connect(#[source] sqlx::Error),
    #[error("timescale bootstrap probe failed; database was not modified")]
    Probe(#[source] sqlx::Error),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HistorianProbe {
    /// True when any product historian relation already exists.
    pub known_relations: bool,
    /// True when `sample` contains at least one row. Never a full table count.
    pub has_sample_row: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BootstrapDisposition {
    /// No product relations yet. Forward DDL may create them.
    NewDatabase,
    /// Schema is already present. Rows stay. Forward DDL may add objects only.
    ExistingPreserve { has_sample_row: bool },
}

impl BootstrapDisposition {
    pub fn label(self) -> &'static str {
        match self {
            Self::NewDatabase => "new",
            Self::ExistingPreserve { .. } => "existing",
        }
    }

    pub fn has_sample_row(self) -> bool {
        matches!(
            self,
            Self::ExistingPreserve {
                has_sample_row: true
            }
        )
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SqlClass {
    Forward,
    Destructive,
    Refused,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RefusedStatement {
    pub source: String,
    pub reason: &'static str,
    pub sql: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SchemaPlan {
    pub disposition: BootstrapDisposition,
    pub apply: Vec<String>,
    pub refused: Vec<RefusedStatement>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BootstrapReport {
    pub skipped: bool,
    pub disposition: Option<BootstrapDisposition>,
    pub applied: u32,
    pub failed: u32,
    pub refused: u32,
}

impl BootstrapReport {
    pub fn skipped() -> Self {
        Self {
            skipped: true,
            disposition: None,
            applied: 0,
            failed: 0,
            refused: 0,
        }
    }

    pub fn disposition_label(&self) -> &'static str {
        self.disposition
            .map(BootstrapDisposition::label)
            .unwrap_or("skipped")
    }

    pub fn has_sample_row(&self) -> bool {
        self.disposition
            .map(BootstrapDisposition::has_sample_row)
            .unwrap_or(false)
    }
}

pub fn bundled_schema() -> &'static [(&'static str, &'static str)] {
    &[
        (
            "00_extensions.sql",
            include_str!("../../../sql/schema/00_extensions.sql"),
        ),
        (
            "01_bps_core.sql",
            include_str!("../../../sql/schema/01_bps_core.sql"),
        ),
        (
            "02_openfdd_dims.sql",
            include_str!("../../../sql/schema/02_openfdd_dims.sql"),
        ),
        (
            "03_wide_history_helper.sql",
            include_str!("../../../sql/schema/03_wide_history_helper.sql"),
        ),
        (
            "04_provider_hourly_jobs.sql",
            include_str!("../../../sql/schema/04_provider_hourly_jobs.sql"),
        ),
        (
            "04_ingest_queue.sql",
            include_str!("../../../sql/schema/04_ingest_queue.sql"),
        ),
    ]
}

/// `1`, `true`, or `yes` (any case). Unset and every other value are off.
pub fn destructive_db_opt_in(raw: Option<&str>) -> bool {
    let Some(raw) = raw else {
        return false;
    };
    matches!(
        raw.trim().to_ascii_lowercase().as_str(),
        "1" | "true" | "yes"
    )
}

pub fn decide_bootstrap(probe: HistorianProbe) -> BootstrapDisposition {
    if probe.known_relations {
        BootstrapDisposition::ExistingPreserve {
            has_sample_row: probe.has_sample_row,
        }
    } else {
        BootstrapDisposition::NewDatabase
    }
}

/// Wipe/reseed permission. Startup does not call this.
pub fn reset_permitted(
    disposition: BootstrapDisposition,
    allow_destructive: bool,
) -> Result<(), &'static str> {
    match disposition {
        BootstrapDisposition::NewDatabase => Ok(()),
        BootstrapDisposition::ExistingPreserve { .. } if allow_destructive => Ok(()),
        BootstrapDisposition::ExistingPreserve { .. } => Err(
            "refusing destructive database reset: existing historian detected; set OPENFDD_ALLOW_DESTRUCTIVE_DB=1",
        ),
    }
}

pub fn classify_sql(sql: &str) -> SqlClass {
    let norm = normalize_sql(sql);
    if norm.is_empty() {
        return SqlClass::Forward;
    }
    if is_destructive(&norm) {
        return SqlClass::Destructive;
    }
    if is_forward(&norm) {
        return SqlClass::Forward;
    }
    SqlClass::Refused
}

pub fn plan_forward_schema(
    disposition: BootstrapDisposition,
    files: &[(&str, &str)],
) -> SchemaPlan {
    let mut apply = Vec::new();
    let mut refused = Vec::new();
    for (source, body) in files {
        for stmt in split_sql(body) {
            match classify_sql(&stmt) {
                SqlClass::Forward => apply.push(stmt),
                SqlClass::Destructive => refused.push(RefusedStatement {
                    source: (*source).to_string(),
                    reason: "destructive SQL is never applied on startup",
                    sql: stmt,
                }),
                SqlClass::Refused => refused.push(RefusedStatement {
                    source: (*source).to_string(),
                    reason: "statement is not forward-only DDL",
                    sql: stmt,
                }),
            }
        }
    }
    SchemaPlan {
        disposition,
        apply,
        refused,
    }
}

pub fn plan_bundled_schema(disposition: BootstrapDisposition) -> SchemaPlan {
    plan_forward_schema(disposition, bundled_schema())
}

pub async fn bootstrap_historian_from_env() -> Result<BootstrapReport, BootstrapError> {
    let Ok(url) = env::var("OPENFDD_DATABASE_URL") else {
        return Ok(BootstrapReport::skipped());
    };
    if url.trim().is_empty() {
        return Ok(BootstrapReport::skipped());
    }
    if destructive_db_opt_in(env::var("OPENFDD_ALLOW_DESTRUCTIVE_DB").ok().as_deref()) {
        tracing::warn!(
            "OPENFDD_ALLOW_DESTRUCTIVE_DB is set; central startup still does not drop, truncate, or reseed"
        );
    }
    let pool = PgPoolOptions::new()
        .max_connections(1)
        .acquire_timeout(Duration::from_secs(15))
        .connect(url.trim())
        .await
        .map_err(BootstrapError::Connect)?;
    let report = apply_forward_schema(&pool)
        .await
        .map_err(BootstrapError::Probe)?;
    pool.close().await;
    Ok(report)
}

pub async fn apply_forward_schema(pool: &PgPool) -> Result<BootstrapReport, sqlx::Error> {
    let names = probe_relation_names(pool).await?;
    let has_sample_relation = names.iter().any(|name| name == "sample");
    let has_sample_row = if has_sample_relation {
        probe_has_sample_row(pool).await?
    } else {
        false
    };
    let disposition = decide_bootstrap(HistorianProbe {
        known_relations: !names.is_empty(),
        has_sample_row,
    });
    let plan = plan_bundled_schema(disposition);
    let mut applied = 0u32;
    let mut failed = 0u32;
    for stmt in &plan.apply {
        if let Err(err) = sqlx::query(stmt).execute(pool).await {
            failed = failed.saturating_add(1);
            tracing::warn!(
                error = %err,
                "forward schema statement failed; existing rows were not deleted"
            );
        } else {
            applied = applied.saturating_add(1);
        }
    }
    for item in &plan.refused {
        tracing::error!(
            source = %item.source,
            reason = item.reason,
            "refused schema statement; it was not executed"
        );
    }
    tracing::info!(
        disposition = disposition.label(),
        has_sample_row,
        applied,
        failed,
        refused = plan.refused.len(),
        "timescale forward schema plan finished"
    );
    Ok(BootstrapReport {
        skipped: false,
        disposition: Some(disposition),
        applied,
        failed,
        refused: u32::try_from(plan.refused.len()).unwrap_or(u32::MAX),
    })
}

async fn probe_relation_names(pool: &PgPool) -> Result<Vec<String>, sqlx::Error> {
    let rows = sqlx::query(PROBE_RELATIONS_SQL).fetch_all(pool).await?;
    let mut names = Vec::with_capacity(rows.len());
    for row in rows {
        names.push(row.try_get("table_name")?);
    }
    Ok(names)
}

async fn probe_has_sample_row(pool: &PgPool) -> Result<bool, sqlx::Error> {
    let exists: bool = sqlx::query_scalar(PROBE_SAMPLE_ROW_SQL)
        .fetch_one(pool)
        .await?;
    Ok(exists)
}

fn split_sql(body: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut current = String::new();
    for line in body.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("--") {
            continue;
        }
        current.push_str(line);
        current.push('\n');
        if trimmed.ends_with(';') {
            let stmt = current.trim().trim_end_matches(';').trim().to_string();
            if !stmt.is_empty() {
                out.push(stmt);
            }
            current.clear();
        }
    }
    let tail = current.trim().trim_end_matches(';').trim();
    if !tail.is_empty() {
        out.push(tail.to_string());
    }
    out
}

fn normalize_sql(sql: &str) -> String {
    sql.split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_ascii_lowercase()
}

fn tokens(sql: &str) -> Vec<&str> {
    sql.split(|c: char| !c.is_ascii_alphanumeric() && c != '_')
        .filter(|tok| !tok.is_empty())
        .collect()
}

fn is_destructive(norm: &str) -> bool {
    let words = tokens(norm);
    words
        .iter()
        .any(|tok| matches!(*tok, "drop" | "truncate" | "delete" | "dropdb" | "dropuser"))
}

fn is_forward(norm: &str) -> bool {
    if norm.starts_with("create extension if not exists ")
        || norm.starts_with("create schema if not exists ")
        || norm.starts_with("create table if not exists ")
        || norm.starts_with("create index if not exists ")
        || norm.starts_with("create unique index if not exists ")
    {
        return true;
    }
    if norm.starts_with("select create_hypertable(") && norm.contains("if_not_exists") {
        return true;
    }
    norm.starts_with("insert into seed_meta") && norm.contains("on conflict")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unset_opt_in_is_safe() {
        assert!(!destructive_db_opt_in(None));
        assert!(!destructive_db_opt_in(Some("")));
        assert!(!destructive_db_opt_in(Some("0")));
        assert!(!destructive_db_opt_in(Some("false")));
        assert!(!destructive_db_opt_in(Some("no")));
        assert!(destructive_db_opt_in(Some("1")));
        assert!(destructive_db_opt_in(Some(" TRUE ")));
        assert!(destructive_db_opt_in(Some("yes")));
    }

    #[test]
    fn existing_database_is_preserved_even_with_zero_rows() {
        let existing = decide_bootstrap(HistorianProbe {
            known_relations: true,
            has_sample_row: false,
        });
        assert_eq!(
            existing,
            BootstrapDisposition::ExistingPreserve {
                has_sample_row: false
            }
        );
        assert!(reset_permitted(existing, false).is_err());
        assert!(reset_permitted(existing, destructive_db_opt_in(Some("1"))).is_ok());
    }

    #[test]
    fn populated_database_refuses_reset_without_opt_in() {
        let existing = decide_bootstrap(HistorianProbe {
            known_relations: true,
            has_sample_row: true,
        });
        assert!(existing.has_sample_row());
        assert!(reset_permitted(existing, false).is_err());
        assert!(reset_permitted(existing, true).is_ok());
    }

    #[test]
    fn missing_relations_are_a_new_database() {
        let fresh = decide_bootstrap(HistorianProbe {
            known_relations: false,
            has_sample_row: false,
        });
        assert_eq!(fresh, BootstrapDisposition::NewDatabase);
        assert!(!fresh.has_sample_row());
        assert!(reset_permitted(fresh, false).is_ok());
    }

    #[test]
    fn startup_plan_never_applies_destructive_sql() {
        let files = [(
            "evil.sql",
            "DROP TABLE sample;\nTRUNCATE sample;\nDELETE FROM sample;\nINSERT INTO sample(ts) VALUES (now());\n",
        )];
        for probe in [
            HistorianProbe {
                known_relations: false,
                has_sample_row: false,
            },
            HistorianProbe {
                known_relations: true,
                has_sample_row: true,
            },
        ] {
            let plan = plan_forward_schema(decide_bootstrap(probe), &files);
            assert!(
                plan.apply.is_empty(),
                "startup applied SQL that can destroy or reseed data"
            );
            assert_eq!(plan.refused.len(), 4);
        }
    }

    #[test]
    fn bundled_schema_is_forward_only() {
        let plan = plan_bundled_schema(BootstrapDisposition::NewDatabase);
        assert!(
            plan.refused.is_empty(),
            "bundled schema is not forward-only: {:?}",
            plan.refused
                .iter()
                .map(|item| format!("{}: {}", item.source, item.sql))
                .collect::<Vec<_>>()
        );
        assert!(!plan.apply.is_empty());
        for stmt in &plan.apply {
            let class = classify_sql(stmt);
            assert_eq!(class, SqlClass::Forward, "{stmt}");
            let norm = normalize_sql(stmt);
            assert!(!is_destructive(&norm), "{stmt}");
        }
    }

    #[test]
    fn probe_sql_is_read_only() {
        for sql in [PROBE_RELATIONS_SQL, PROBE_SAMPLE_ROW_SQL] {
            let norm = normalize_sql(sql);
            assert!(norm.starts_with("select "));
            assert!(!is_destructive(&norm), "{sql}");
        }
    }

    #[test]
    fn forward_classifier_accepts_idempotent_ddl_only() {
        assert_eq!(
            classify_sql("CREATE TABLE IF NOT EXISTS site (site_id text);"),
            SqlClass::Forward
        );
        assert_eq!(
            classify_sql("CREATE TABLE site (site_id text);"),
            SqlClass::Refused
        );
        assert_eq!(
            classify_sql(
                "INSERT INTO seed_meta(key, value) VALUES ('schema_version', '4') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;"
            ),
            SqlClass::Forward
        );
        assert_eq!(
            classify_sql("INSERT INTO sample(ts, site_id) VALUES (now(), 'x');"),
            SqlClass::Refused
        );
        assert_eq!(classify_sql("DROP TABLE sample;"), SqlClass::Destructive);
        assert_eq!(
            classify_sql("ALTER TABLE sample DROP COLUMN val;"),
            SqlClass::Destructive
        );
    }
}
