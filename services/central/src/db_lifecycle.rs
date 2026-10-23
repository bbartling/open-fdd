//! Timescale startup lifecycle.
//!
//! Image updates and process restarts preserve historian rows. Schema changes
//! are forward-only (`CREATE … IF NOT EXISTS` and the idempotent init SQL).
//! A reset runs only when `OPENFDD_RESET_DB=1` and
//! `OPENFDD_ALLOW_DESTRUCTIVE_DB=1` are both set. Either flag alone does not
//! delete, truncate, or re-bootstrap existing data.

use std::time::Duration;

use anyhow::{bail, Context};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;

pub(crate) const REFUSE_MSG: &str = "\
REFUSING startup: OPENFDD_RESET_DB is set but OPENFDD_ALLOW_DESTRUCTIVE_DB is not 1. \
The database was not modified. Unset OPENFDD_RESET_DB to keep existing Timescale data, \
or set OPENFDD_ALLOW_DESTRUCTIVE_DB=1 together with a one-shot OPENFDD_RESET_DB token to truncate it.";

const RESET_TOKEN_KEY: &str = "destructive_reset_token";

const SCHEMA_SQL: &[&str] = &[
    include_str!("../../../sql/schema/00_extensions.sql"),
    include_str!("../../../sql/schema/01_bps_core.sql"),
    include_str!("../../../sql/schema/02_openfdd_dims.sql"),
    include_str!("../../../sql/schema/03_wide_history_helper.sql"),
    include_str!("../../../sql/schema/04_provider_hourly_jobs.sql"),
    include_str!("../../../sql/schema/04_ingest_queue.sql"),
];

/// Tables whose rows mean this database is already in use.
/// `seed_meta` is excluded: init SQL writes a schema version on an empty volume.
const PRESENCE_TABLES: &[&str] = &[
    "sample",
    "site",
    "equipment",
    "building",
    "point_map",
    "role_map",
    "fdd_run",
    "analytics_result",
    "ingest_job",
    "provider_hourly_job",
];

const RESET_TABLES: &[&str] = &[
    "sample",
    "fdd_run",
    "analytics_result",
    "point_map",
    "role_map",
    "equipment",
    "building",
    "batch_job",
    "ingest_audit",
    "ingest_idempotency",
    "ingest_receipt",
    "ingest_job",
    "ingest_scheduler_lease",
    "ingest_portal_budget",
    "provider_hourly_gap",
    "provider_hourly_receipt",
    "provider_hourly_checkpoint",
    "provider_hourly_job",
    "seed_meta",
    "site",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum DbPresence {
    Empty,
    Existing,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum StartupAction {
    Skip,
    BootstrapEmpty,
    EnsureForwardSchema,
    RefuseDestructive,
    ResetExisting,
    /// Same forward schema as an ordinary boot. The reset token was already used.
    PreserveConsumedReset,
    /// Empty database. Record the reset token so a later boot does not wipe the reseed.
    BootstrapAndConsumeReset,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct DecideInput {
    pub database_url_set: bool,
    pub reset_requested: bool,
    pub allow_destructive: bool,
    pub presence: DbPresence,
    pub reset_already_consumed: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct StartupFlags {
    database_url_set: bool,
    reset_token: Option<String>,
    allow_destructive: bool,
}

pub(crate) fn env_flag_on(value: Option<&str>) -> bool {
    value
        .map(str::trim)
        .map(str::to_ascii_lowercase)
        .is_some_and(|flag| matches!(flag.as_str(), "1" | "true" | "yes" | "on"))
}

/// Any value other than empty/`0`/`false`/`no`/`off` is a one-shot reset token.
pub(crate) fn reset_token(value: Option<&str>) -> Option<String> {
    let raw = value?.trim();
    if raw.is_empty() {
        return None;
    }
    if matches!(
        raw.to_ascii_lowercase().as_str(),
        "0" | "false" | "no" | "off"
    ) {
        return None;
    }
    Some(raw.to_string())
}

fn flags_from_env() -> StartupFlags {
    StartupFlags {
        database_url_set: std::env::var("OPENFDD_DATABASE_URL")
            .ok()
            .is_some_and(|url| !url.trim().is_empty()),
        reset_token: reset_token(std::env::var("OPENFDD_RESET_DB").ok().as_deref()),
        allow_destructive: env_flag_on(
            std::env::var("OPENFDD_ALLOW_DESTRUCTIVE_DB")
                .ok()
                .as_deref(),
        ),
    }
}

pub(crate) fn decide(input: DecideInput) -> StartupAction {
    if !input.database_url_set {
        return StartupAction::Skip;
    }
    if input.reset_requested && !input.allow_destructive {
        return StartupAction::RefuseDestructive;
    }
    if input.reset_requested && input.allow_destructive {
        if input.reset_already_consumed {
            return if input.presence == DbPresence::Existing {
                StartupAction::PreserveConsumedReset
            } else {
                StartupAction::BootstrapEmpty
            };
        }
        return if input.presence == DbPresence::Existing {
            StartupAction::ResetExisting
        } else {
            StartupAction::BootstrapAndConsumeReset
        };
    }
    if input.presence == DbPresence::Existing {
        return StartupAction::EnsureForwardSchema;
    }
    StartupAction::BootstrapEmpty
}

pub(crate) fn statements(ddl: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut current = String::new();
    for line in ddl.lines() {
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
    out
}

pub(crate) fn forward_statements() -> Vec<String> {
    SCHEMA_SQL.iter().flat_map(|sql| statements(sql)).collect()
}

pub(crate) fn statement_destructive_kind(sql: &str) -> Option<&'static str> {
    let mut stripped = String::new();
    for line in sql.lines() {
        if let Some((code, _)) = line.split_once("--") {
            stripped.push_str(code);
        } else {
            stripped.push_str(line);
        }
        stripped.push('\n');
    }
    let upper = stripped.to_ascii_uppercase();
    for (kind, keyword) in [
        ("drop", "DROP"),
        ("truncate", "TRUNCATE"),
        ("delete", "DELETE"),
    ] {
        if keyword_present(&upper, keyword) {
            return Some(kind);
        }
    }
    None
}

fn keyword_present(upper_sql: &str, keyword: &str) -> bool {
    let bytes = upper_sql.as_bytes();
    let key = keyword.as_bytes();
    if key.is_empty() || bytes.len() < key.len() {
        return false;
    }
    let mut index = 0;
    while index + key.len() <= bytes.len() {
        if &bytes[index..index + key.len()] == key {
            let before_ok = index == 0 || !bytes[index - 1].is_ascii_alphanumeric();
            let after = index + key.len();
            let after_ok = after == bytes.len() || !bytes[after].is_ascii_alphanumeric();
            if before_ok && after_ok {
                return true;
            }
        }
        index += 1;
    }
    false
}

fn is_safe_ident(name: &str) -> bool {
    let mut chars = name.chars();
    match chars.next() {
        Some(first) if first.is_ascii_alphabetic() || first == '_' => {}
        _ => return false,
    }
    chars.all(|ch| ch.is_ascii_alphanumeric() || ch == '_')
}

pub(crate) fn truncate_sql(tables: &[&str]) -> anyhow::Result<String> {
    if tables.is_empty() {
        bail!("no tables");
    }
    if tables.iter().any(|table| !is_safe_ident(table)) {
        bail!("unsafe identifier");
    }
    Ok(format!(
        "TRUNCATE TABLE {} RESTART IDENTITY CASCADE",
        tables.join(", ")
    ))
}

/// Opt-in reset also drops the file-volume dataset list and job metadata.
/// Tenant and user admin files under `openfdd/control_plane` stay.
/// Security audit JSONL under `logs/` is intentionally preserved (not Timescale;
/// not part of the historian wipe).
pub(crate) fn clear_workspace_datasets_and_jobs(root: &std::path::Path) -> std::io::Result<()> {
    let jobs = root.join("jobs");
    if jobs.exists() {
        std::fs::remove_dir_all(&jobs)?;
    }
    let datasets = root.join("data").join("datasets");
    if datasets.exists() {
        std::fs::remove_dir_all(&datasets)?;
    }
    Ok(())
}

fn clear_file_volume_for_reset() -> anyhow::Result<()> {
    let root = crate::jobs::workspace_root();
    clear_workspace_datasets_and_jobs(&root)
        .with_context(|| format!("clear jobs and datasets under {}", root.display()))
}

fn exists_sql(table: &str) -> anyhow::Result<String> {
    if !is_safe_ident(table) {
        bail!("unsafe identifier");
    }
    Ok(format!("SELECT EXISTS (SELECT 1 FROM {table})"))
}

#[cfg(test)]
fn plan_statements(action: StartupAction) -> Vec<String> {
    match action {
        StartupAction::Skip | StartupAction::RefuseDestructive => Vec::new(),
        StartupAction::BootstrapEmpty
        | StartupAction::BootstrapAndConsumeReset
        | StartupAction::EnsureForwardSchema
        | StartupAction::PreserveConsumedReset => forward_statements(),
        StartupAction::ResetExisting => {
            let mut sql = forward_statements();
            sql.push(truncate_sql(RESET_TABLES).expect("RESET_TABLES are safe identifiers"));
            sql
        }
    }
}

fn safe_db_error(err: &impl std::fmt::Display) -> String {
    let text = err.to_string();
    if text.contains("://") || text.to_ascii_lowercase().contains("password") {
        "database error (details redacted)".to_string()
    } else {
        text.chars().take(300).collect()
    }
}

pub(crate) async fn apply_on_startup() -> anyhow::Result<()> {
    let flags = flags_from_env();
    if !flags.database_url_set {
        tracing::info!("db lifecycle: OPENFDD_DATABASE_URL unset; database left untouched");
        return Ok(());
    }
    if decide(DecideInput {
        database_url_set: true,
        reset_requested: flags.reset_token.is_some(),
        allow_destructive: flags.allow_destructive,
        presence: DbPresence::Existing,
        reset_already_consumed: false,
    }) == StartupAction::RefuseDestructive
    {
        tracing::error!("{REFUSE_MSG}");
        bail!("{REFUSE_MSG}");
    }

    let url = std::env::var("OPENFDD_DATABASE_URL").context("OPENFDD_DATABASE_URL")?;
    let connect = PgPoolOptions::new()
        .max_connections(1)
        .acquire_timeout(Duration::from_secs(5))
        .connect(url.trim());
    let pool = match tokio::time::timeout(Duration::from_secs(8), connect).await {
        Ok(Ok(pool)) => pool,
        Ok(Err(err)) => {
            return startup_without_connection(&flags, &safe_db_error(&err));
        }
        Err(_) => return startup_without_connection(&flags, "timed out after 8s"),
    };

    let presence = match detect_presence(&pool).await {
        Ok(presence) => presence,
        Err(err) => {
            if flags.reset_token.is_some() {
                bail!(
                    "OPENFDD_RESET_DB is set but historian presence could not be read ({}); refusing to start",
                    safe_db_error(&err)
                );
            }
            tracing::warn!(
                error = %safe_db_error(&err),
                "db lifecycle: could not read historian presence; leaving data untouched"
            );
            return Ok(());
        }
    };
    let consumed = match stored_reset_token(&pool).await {
        Ok(stored) => {
            stored.as_deref() == flags.reset_token.as_deref() && flags.reset_token.is_some()
        }
        Err(err) => {
            if flags.reset_token.is_some() {
                bail!(
                    "OPENFDD_RESET_DB is set but the reset token could not be read ({}); refusing to start",
                    safe_db_error(&err)
                );
            }
            tracing::warn!(
                error = %safe_db_error(&err),
                "db lifecycle: could not read reset token; leaving data untouched"
            );
            return Ok(());
        }
    };
    let action = decide(DecideInput {
        database_url_set: true,
        reset_requested: flags.reset_token.is_some(),
        allow_destructive: flags.allow_destructive,
        presence,
        reset_already_consumed: consumed,
    });
    match action {
        StartupAction::Skip | StartupAction::RefuseDestructive => {
            bail!("{REFUSE_MSG}");
        }
        StartupAction::BootstrapEmpty => {
            tracing::info!("db lifecycle: empty Timescale database; creating schema");
            apply_forward(&pool)
                .await
                .context("bootstrap empty Timescale database")?;
        }
        StartupAction::BootstrapAndConsumeReset => {
            tracing::warn!(
                "db lifecycle: empty database; recording one-shot reset token so a later reseed is kept"
            );
            apply_forward(&pool)
                .await
                .context("bootstrap before recording reset token")?;
            let token = flags.reset_token.as_deref().context("reset token")?;
            clear_file_volume_for_reset()?;
            record_reset_token(&pool, token).await?;
        }
        StartupAction::EnsureForwardSchema => {
            tracing::info!("db lifecycle: existing Timescale data preserved; forward-only schema");
            if let Err(err) = apply_forward(&pool).await {
                tracing::warn!(
                    error = %safe_db_error(&err),
                    "forward schema apply failed; existing rows were not modified"
                );
            }
        }
        StartupAction::PreserveConsumedReset => {
            tracing::info!(
                "db lifecycle: reset token already used; historian data preserved; forward-only schema"
            );
            if let Err(err) = apply_forward(&pool).await {
                tracing::warn!(
                    error = %safe_db_error(&err),
                    "forward schema apply failed; existing rows were not modified"
                );
            }
        }
        StartupAction::ResetExisting => {
            tracing::warn!(
                "DESTRUCTIVE one-shot historian reset (OPENFDD_ALLOW_DESTRUCTIVE_DB=1). This token will not purge again."
            );
            apply_forward(&pool)
                .await
                .context("forward schema before destructive reset")?;
            let token = flags.reset_token.as_deref().context("reset token")?;
            clear_file_volume_for_reset()?;
            truncate_and_consume(&pool, token).await?;
            apply_forward(&pool)
                .await
                .context("forward schema after destructive reset")?;
            tracing::warn!("db lifecycle: one-shot destructive reset committed");
        }
    }
    Ok(())
}

fn startup_without_connection(flags: &StartupFlags, detail: &str) -> anyhow::Result<()> {
    if flags.reset_token.is_some() {
        bail!(
            "OPENFDD_RESET_DB is set but the database is unreachable ({detail}); refusing to start"
        );
    }
    tracing::warn!(
        error = %detail,
        "db lifecycle: database unreachable; leaving data untouched"
    );
    Ok(())
}

async fn detect_presence(pool: &PgPool) -> anyhow::Result<DbPresence> {
    for table in PRESENCE_TABLES {
        if !relation_exists(pool, table).await? {
            continue;
        }
        let sql = exists_sql(table)?;
        let any: bool = sqlx::query_scalar(&sql).fetch_one(pool).await?;
        if any {
            return Ok(DbPresence::Existing);
        }
    }
    Ok(DbPresence::Empty)
}

async fn relation_exists(pool: &PgPool, table: &str) -> anyhow::Result<bool> {
    if !is_safe_ident(table) {
        bail!("unsafe table identifier");
    }
    let reg: Option<String> = sqlx::query_scalar("SELECT to_regclass($1)::text")
        .bind(format!("public.{table}"))
        .fetch_one(pool)
        .await?;
    Ok(reg.is_some())
}

async fn apply_forward(pool: &PgPool) -> anyhow::Result<()> {
    for stmt in forward_statements() {
        if let Some(kind) = statement_destructive_kind(&stmt) {
            bail!("refusing {kind} statement during forward schema");
        }
        sqlx::query(&stmt).execute(pool).await.with_context(|| {
            let preview: String = stmt.chars().take(80).collect();
            format!("forward schema statement failed: {preview}")
        })?;
    }
    Ok(())
}

async fn stored_reset_token(pool: &PgPool) -> anyhow::Result<Option<String>> {
    if !relation_exists(pool, "seed_meta").await? {
        return Ok(None);
    }
    let value: Option<String> = sqlx::query_scalar("SELECT value FROM seed_meta WHERE key = $1")
        .bind(RESET_TOKEN_KEY)
        .fetch_optional(pool)
        .await
        .context("read one-shot reset token")?;
    Ok(value)
}

async fn record_reset_token(pool: &PgPool, token: &str) -> anyhow::Result<()> {
    sqlx::query(
        "INSERT INTO seed_meta(key, value) VALUES ($1, $2)
         ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
    )
    .bind(RESET_TOKEN_KEY)
    .bind(token)
    .execute(pool)
    .await
    .context("record one-shot reset token")?;
    Ok(())
}

async fn truncate_and_consume(pool: &PgPool, token: &str) -> anyhow::Result<()> {
    let mut present = Vec::new();
    for table in RESET_TABLES {
        if relation_exists(pool, table).await? {
            present.push(*table);
        }
    }
    let mut tx = pool.begin().await.context("begin destructive reset")?;
    if present.is_empty() {
        tracing::warn!("destructive reset found no historian tables");
    } else {
        let sql = truncate_sql(&present)?;
        sqlx::query(&sql)
            .execute(&mut *tx)
            .await
            .context("truncate historian tables")?;
    }
    sqlx::query(
        "INSERT INTO seed_meta(key, value) VALUES ($1, $2)
         ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
    )
    .bind(RESET_TOKEN_KEY)
    .bind(token)
    .execute(&mut *tx)
    .await
    .context("record one-shot reset token")?;
    tx.commit().await.context("commit destructive reset")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn input(reset_requested: bool, allow_destructive: bool, presence: DbPresence) -> DecideInput {
        DecideInput {
            database_url_set: true,
            reset_requested,
            allow_destructive,
            presence,
            reset_already_consumed: false,
        }
    }

    #[test]
    fn env_flag_accepts_only_explicit_truthy_values() {
        for value in ["1", "true", "TRUE", "yes", "on", " on "] {
            assert!(env_flag_on(Some(value)), "{value}");
        }
        for value in [
            None,
            Some(""),
            Some("0"),
            Some("false"),
            Some("no"),
            Some("allow"),
        ] {
            assert!(!env_flag_on(value), "{value:?}");
        }
    }

    #[test]
    fn reset_clears_jobs_and_datasets_and_keeps_tenant_admin() {
        let root =
            std::env::temp_dir().join(format!("openfdd-reset-volume-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let jobs = root.join("jobs").join("job-1");
        let datasets = root.join("data").join("datasets");
        let plane = root.join("openfdd").join("control_plane");
        std::fs::create_dir_all(&jobs).unwrap();
        std::fs::create_dir_all(&datasets).unwrap();
        std::fs::create_dir_all(&plane).unwrap();
        std::fs::write(jobs.join("job.json"), b"{}").unwrap();
        std::fs::write(datasets.join("registry.json"), b"{}").unwrap();
        std::fs::write(plane.join("tenants.json"), b"{\"keep\":true}").unwrap();
        std::fs::write(plane.join("users.json"), b"{\"keep\":true}").unwrap();
        clear_workspace_datasets_and_jobs(&root).unwrap();
        assert!(!root.join("jobs").exists());
        assert!(!datasets.exists());
        assert_eq!(
            std::fs::read_to_string(plane.join("tenants.json")).unwrap(),
            "{\"keep\":true}"
        );
        assert_eq!(
            std::fs::read_to_string(plane.join("users.json")).unwrap(),
            "{\"keep\":true}"
        );
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn guarded_reset_leaves_security_audit_jsonl_in_place() {
        let root = std::env::temp_dir().join(format!("openfdd-reset-audit-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let logs = root.join("logs");
        let jobs = root.join("jobs").join("job-1");
        std::fs::create_dir_all(&logs).unwrap();
        std::fs::create_dir_all(&jobs).unwrap();
        let audit = logs.join("security_audit.jsonl");
        std::fs::write(&audit, b"{\"channel\":\"security_audit\"}\n").unwrap();
        std::fs::write(jobs.join("job.json"), b"{}").unwrap();
        clear_workspace_datasets_and_jobs(&root).unwrap();
        assert!(!root.join("jobs").exists());
        assert!(
            audit.exists(),
            "DB/file reset must not delete logs/security_audit.jsonl"
        );
        assert_eq!(
            std::fs::read_to_string(&audit).unwrap(),
            "{\"channel\":\"security_audit\"}\n"
        );
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn default_startup_preserves_existing_data() {
        assert_eq!(
            decide(input(false, false, DbPresence::Existing)),
            StartupAction::EnsureForwardSchema
        );
        assert_eq!(
            decide(input(false, true, DbPresence::Existing)),
            StartupAction::EnsureForwardSchema
        );
        assert_eq!(
            decide(DecideInput {
                database_url_set: false,
                reset_requested: true,
                allow_destructive: true,
                presence: DbPresence::Existing,
                reset_already_consumed: false,
            }),
            StartupAction::Skip
        );
    }

    #[test]
    fn empty_database_bootstraps_without_a_reset_flag() {
        assert_eq!(
            decide(input(false, false, DbPresence::Empty)),
            StartupAction::BootstrapEmpty
        );
        assert_eq!(
            decide(input(true, true, DbPresence::Empty)),
            StartupAction::BootstrapAndConsumeReset
        );
    }

    #[test]
    fn reset_token_is_explicit_and_one_shot() {
        assert_eq!(reset_token(None), None);
        assert_eq!(reset_token(Some("0")), None);
        assert_eq!(reset_token(Some("false")), None);
        assert_eq!(reset_token(Some("off")), None);
        assert_eq!(reset_token(Some("1")).as_deref(), Some("1"));
        assert_eq!(
            reset_token(Some(" b50-wipe-20261020 ")).as_deref(),
            Some("b50-wipe-20261020")
        );
        let mut consumed = input(true, true, DbPresence::Existing);
        consumed.reset_already_consumed = true;
        assert_eq!(decide(consumed), StartupAction::PreserveConsumedReset);
        let mut consumed_empty = input(true, true, DbPresence::Empty);
        consumed_empty.reset_already_consumed = true;
        assert_eq!(decide(consumed_empty), StartupAction::BootstrapEmpty);
    }

    #[test]
    fn reset_without_allow_flag_is_refused() {
        assert_eq!(
            decide(input(true, false, DbPresence::Existing)),
            StartupAction::RefuseDestructive
        );
        assert_eq!(
            decide(input(true, false, DbPresence::Empty)),
            StartupAction::RefuseDestructive
        );
    }

    #[test]
    fn reset_of_existing_data_requires_both_flags() {
        assert_eq!(
            decide(input(true, true, DbPresence::Existing)),
            StartupAction::ResetExisting
        );
    }

    #[test]
    fn forward_schema_and_default_plans_never_destroy_rows() {
        let forward = forward_statements();
        assert!(
            forward.len() > 10,
            "schema splitter dropped statements: {}",
            forward.len()
        );
        assert!(
            forward.iter().any(|stmt| stmt.contains("CREATE EXTENSION")),
            "extensions SQL missing"
        );
        assert!(
            forward
                .iter()
                .any(|stmt| stmt.contains("CREATE TABLE IF NOT EXISTS sample")),
            "sample table SQL missing"
        );
        for action in [
            StartupAction::Skip,
            StartupAction::RefuseDestructive,
            StartupAction::BootstrapEmpty,
            StartupAction::BootstrapAndConsumeReset,
            StartupAction::EnsureForwardSchema,
            StartupAction::PreserveConsumedReset,
        ] {
            for stmt in plan_statements(action) {
                assert_eq!(
                    statement_destructive_kind(&stmt),
                    None,
                    "{action:?} planned destructive SQL: {stmt}"
                );
            }
        }
    }

    #[test]
    fn destructive_plan_is_opt_in_and_classifier_catches_it() {
        let plan = plan_statements(StartupAction::ResetExisting);
        let truncate = plan.last().expect("reset plan");
        assert_eq!(statement_destructive_kind(truncate), Some("truncate"));
        for stmt in &plan[..plan.len() - 1] {
            assert_eq!(statement_destructive_kind(stmt), None, "{stmt}");
        }
        assert_eq!(
            statement_destructive_kind("DROP TABLE sample"),
            Some("drop")
        );
        assert_eq!(
            statement_destructive_kind("DELETE FROM sample WHERE site_id = $1"),
            Some("delete")
        );
        assert_eq!(
            statement_destructive_kind(
                "INSERT INTO seed_meta(key, value) VALUES ('schema_version', 'x') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            ),
            None
        );
        assert_eq!(
            statement_destructive_kind(
                "SELECT create_hypertable('sample', 'ts', if_not_exists => TRUE)"
            ),
            None
        );
        assert!(truncate_sql(&["sample;drop"]).is_err());
    }

    #[test]
    fn refuse_plan_runs_no_sql() {
        assert!(plan_statements(StartupAction::RefuseDestructive).is_empty());
        assert!(plan_statements(StartupAction::Skip).is_empty());
    }
}
