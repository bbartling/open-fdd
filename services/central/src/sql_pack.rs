//! PostgreSQL pack runtime for advertised FDD rules.
//!
//! Fresh startup and forward upgrades install `fdd.try_double` and the pack
//! catalog. Weather, utility, and `authorized_series` inputs are temporary
//! projections scoped to one building (and its site binding) per rule
//! transaction. They are not global views during FDD execution. Missing input,
//! unsupported capability, schema incompatibility, and runtime failure stay
//! distinct. An empty projection is not used to turn a missing input into zero
//! fault hours.

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use serde_json::{json, Value};
use sqlx::{PgConnection, PgPool, Row};

pub const CONTRACT_ID: &str = "openfdd-postgres-pack";
pub const CONTRACT_VERSION: &str = "1";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PackStatus {
    pub checked: bool,
    pub compatible: bool,
    pub helper_installed: bool,
    pub contract_installed: bool,
    pub detail: String,
}

impl PackStatus {
    fn compatible(detail: impl Into<String>) -> Self {
        Self {
            checked: true,
            compatible: true,
            helper_installed: true,
            contract_installed: true,
            detail: detail.into(),
        }
    }

    fn incompatible(
        helper_installed: bool,
        contract_installed: bool,
        detail: impl Into<String>,
    ) -> Self {
        Self {
            checked: true,
            compatible: false,
            helper_installed,
            contract_installed,
            detail: detail.into(),
        }
    }

    pub fn to_json(&self) -> Value {
        json!({
            "contract_id": CONTRACT_ID,
            "contract_version": CONTRACT_VERSION,
            "checked": self.checked,
            "compatible": self.compatible,
            "helper_installed": self.helper_installed,
            "contract_installed": self.contract_installed,
            "failure_class": if self.compatible {
                Value::Null
            } else if self.checked {
                json!("schema_incompatible")
            } else {
                Value::Null
            },
            "detail": self.detail,
        })
    }
}

#[derive(Debug, Clone)]
pub struct RuleStop {
    pub status: &'static str,
    pub failure_class: &'static str,
    pub notes: String,
    pub input_condition: Option<&'static str>,
    pub relation: Option<String>,
}

impl RuleStop {
    pub fn schema(detail: &str) -> Self {
        Self {
            status: "SCHEMA_INCOMPATIBLE",
            failure_class: "schema_incompatible",
            notes: detail.to_string(),
            input_condition: None,
            relation: None,
        }
    }

    pub fn to_json(&self, equipment_id: Option<&str>, metric: bool) -> Value {
        let mut body = serde_json::Map::new();
        if let Some(id) = equipment_id.map(str::trim).filter(|id| !id.is_empty()) {
            body.insert("equipment_id".into(), json!(id));
        }
        body.insert("status".into(), json!(self.status));
        body.insert("failure_class".into(), json!(self.failure_class));
        body.insert("notes".into(), json!(self.notes));
        body.insert(
            "output_kind".into(),
            json!(if metric { "metric" } else { "diagnostic" }),
        );
        if let Some(condition) = self.input_condition {
            body.insert("input_condition".into(), json!(condition));
        }
        if let Some(relation) = &self.relation {
            body.insert("relation".into(), json!(relation));
        }
        Value::Object(body)
    }
}

pub enum InputGate {
    Ready(Value),
    Stop(RuleStop),
}

pub fn sql_needs_helper(sql: &str) -> bool {
    sql.to_ascii_lowercase().contains("fdd.try_double")
}

pub fn sql_depends_on_pack(sql: &str) -> bool {
    sql_needs_helper(sql) || !external_relations(sql).is_empty()
}

/// A missing helper stops only rules that call it. A missing contract row stops
/// every pack-dependent rule. Weather rules still run when the helper alone is
/// absent, so a dropped function is not reported as a weather failure.
pub fn schema_stop(sql: &str, status: &PackStatus) -> Option<RuleStop> {
    if !sql_depends_on_pack(sql) {
        return None;
    }
    if !status.checked {
        return Some(RuleStop::schema(&status.detail));
    }
    if sql_needs_helper(sql) && !status.helper_installed {
        let notes = if status.detail.is_empty() {
            "fdd.try_double is not installed".to_string()
        } else {
            status.detail.clone()
        };
        return Some(RuleStop::schema(&notes));
    }
    if !status.contract_installed {
        let notes = if status.detail.contains("contract") {
            status.detail.clone()
        } else {
            "pack contract row is not installed".to_string()
        };
        return Some(RuleStop::schema(&notes));
    }
    None
}

/// `ERROR` stays a runtime failure. A missing helper is schema incompatibility.
pub fn classify_database_error(err: &str) -> (&'static str, &'static str) {
    let lower = err.to_ascii_lowercase();
    if lower.contains("try_double")
        && (lower.contains("does not exist") || lower.contains("undefined function"))
    {
        ("SCHEMA_INCOMPATIBLE", "schema_incompatible")
    } else {
        ("ERROR", "runtime_failure")
    }
}

pub fn attach_ready_scope(row: &mut Value, scope: &Value) {
    if let Some(obj) = row.as_object_mut() {
        obj.insert("input_scope".into(), scope.clone());
        obj.insert("failure_class".into(), Value::Null);
    }
}

pub async fn pack_status(pool: &PgPool) -> Result<PackStatus> {
    let mut conn = pool.acquire().await.context("pack status connection")?;
    probe_conn(&mut conn).await
}

pub async fn attach_pack_readiness(body: &mut Value) {
    let Ok(url) = std::env::var("OPENFDD_DATABASE_URL") else {
        insert_unchecked(body, "OPENFDD_DATABASE_URL is unset");
        return;
    };
    if url.trim().is_empty() {
        insert_unchecked(body, "OPENFDD_DATABASE_URL is unset");
        return;
    }
    let connect = sqlx::postgres::PgPoolOptions::new()
        .max_connections(1)
        .acquire_timeout(std::time::Duration::from_secs(5))
        .connect(url.trim());
    let pool = match tokio::time::timeout(std::time::Duration::from_secs(8), connect).await {
        Ok(Ok(pool)) => pool,
        Ok(Err(err)) => {
            insert_unchecked(body, &format!("pack probe unavailable: {err}"));
            return;
        }
        Err(_) => {
            insert_unchecked(body, "pack probe timed out");
            return;
        }
    };
    match pack_status(&pool).await {
        Ok(status) => {
            if let Some(obj) = body.as_object_mut() {
                obj.insert("pack".into(), status.to_json());
                if status.checked && !status.compatible {
                    obj.insert("clean".into(), json!(false));
                    push_dirty(obj, "schema_incompatible");
                }
            }
        }
        Err(err) => insert_unchecked(body, &format!("pack probe failed: {err}")),
    }
}

fn insert_unchecked(body: &mut Value, detail: &str) {
    let status = PackStatus {
        checked: false,
        compatible: false,
        helper_installed: false,
        contract_installed: false,
        detail: detail.chars().take(300).collect(),
    };
    if let Some(obj) = body.as_object_mut() {
        obj.insert("pack".into(), status.to_json());
    }
}

fn push_dirty(obj: &mut serde_json::Map<String, Value>, reason: &str) {
    let reasons = obj
        .entry("dirty_reasons")
        .or_insert_with(|| json!([]))
        .as_array_mut();
    if let Some(reasons) = reasons {
        if !reasons.iter().any(|item| item.as_str() == Some(reason)) {
            reasons.push(json!(reason));
        }
    }
}

pub async fn prepare_rule_inputs(
    conn: &mut PgConnection,
    building_id: &str,
    window_start: Option<&str>,
    window_end: Option<&str>,
    sql: &str,
    diagnostic: bool,
) -> Result<InputGate> {
    if diagnostic {
        let stamps: i64 =
            sqlx::query_scalar("SELECT COUNT(DISTINCT timestamp_utc)::bigint FROM history")
                .fetch_one(&mut *conn)
                .await
                .context("history timestamp count")?;
        if stamps < 2 {
            return Ok(InputGate::Stop(RuleStop {
                status: "SKIP_SHORT_HISTORY",
                failure_class: "input_missing",
                notes: "fewer than two timestamps in scope; elapsed fault time is not defined"
                    .into(),
                input_condition: Some("short_history"),
                relation: None,
            }));
        }
    }
    if sql_depends_on_pack(sql) {
        let status = probe_conn(conn).await?;
        if let Some(stop) = schema_stop(sql, &status) {
            return Ok(InputGate::Stop(stop));
        }
    }
    let relations = external_relations(sql);
    if relations.is_empty() {
        return Ok(InputGate::Ready(empty_scope(
            building_id,
            window_start,
            window_end,
        )));
    }
    let mut scope = empty_scope(building_id, window_start, window_end);
    let (start, end) = window_bounds(window_start, window_end);
    for name in relations {
        match PackInput::parse(&name) {
            None => {
                return Ok(InputGate::Stop(RuleStop {
                    status: "SKIP_UNSUPPORTED",
                    failure_class: "unsupported",
                    notes: format!(
                        "relation {name} is not a scoped pack projection and is not available"
                    ),
                    input_condition: None,
                    relation: Some(name),
                }));
            }
            Some(input) => match project_input(conn, building_id, start, end, input).await? {
                InputGate::Stop(stop) => return Ok(InputGate::Stop(stop)),
                InputGate::Ready(note) => {
                    if let Some(relations) =
                        scope.get_mut("relations").and_then(Value::as_object_mut)
                    {
                        relations.insert(input.name().to_string(), note);
                    }
                }
            },
        }
    }
    Ok(InputGate::Ready(scope))
}

#[derive(Clone, Copy)]
enum PackInput {
    Weather,
    UtilityInterval,
    UtilityMonthly,
    AuthorizedSeries,
}

impl PackInput {
    fn parse(name: &str) -> Option<Self> {
        match name {
            "weather" => Some(Self::Weather),
            "utility_interval" => Some(Self::UtilityInterval),
            "utility_monthly" => Some(Self::UtilityMonthly),
            "authorized_series" => Some(Self::AuthorizedSeries),
            _ => None,
        }
    }

    fn name(self) -> &'static str {
        match self {
            Self::Weather => "weather",
            Self::UtilityInterval => "utility_interval",
            Self::UtilityMonthly => "utility_monthly",
            Self::AuthorizedSeries => "authorized_series",
        }
    }
}

async fn probe_conn(conn: &mut PgConnection) -> Result<PackStatus> {
    let helper: bool = sqlx::query_scalar(
        "SELECT EXISTS (
            SELECT 1
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'fdd' AND p.proname = 'try_double'
         )",
    )
    .fetch_one(&mut *conn)
    .await
    .context("probe fdd.try_double")?;
    let version = match sqlx::query_scalar::<_, String>(
        "SELECT contract_version FROM fdd.pack_runtime WHERE contract_id = $1",
    )
    .bind(CONTRACT_ID)
    .fetch_optional(&mut *conn)
    .await
    {
        Ok(value) => value,
        Err(err) if missing_relation(&err) => None,
        Err(err) => return Err(err).context("probe pack contract"),
    };
    let contract_ok = version.as_deref() == Some(CONTRACT_VERSION);
    if helper && contract_ok {
        return Ok(PackStatus::compatible("pack runtime matches"));
    }
    let detail = if !helper {
        "fdd.try_double is not installed".to_string()
    } else {
        match version.as_deref() {
            None => "pack contract row is not installed".to_string(),
            Some(found) => format!("pack contract version is {found}"),
        }
    };
    Ok(PackStatus::incompatible(helper, contract_ok, detail))
}

fn missing_relation(err: &sqlx::Error) -> bool {
    match err {
        sqlx::Error::Database(db) => {
            matches!(db.code().as_deref(), Some("42P01") | Some("3F000"))
        }
        _ => false,
    }
}

fn empty_scope(building_id: &str, window_start: Option<&str>, window_end: Option<&str>) -> Value {
    json!({
        "building_id": building_id,
        "window": {
            "start": window_start,
            "end": window_end,
        },
        "relations": {},
    })
}

fn window_bounds(
    start: Option<&str>,
    end: Option<&str>,
) -> (Option<DateTime<Utc>>, Option<DateTime<Utc>>) {
    fn parse(value: Option<&str>) -> Option<DateTime<Utc>> {
        let raw = value?.trim();
        if raw.is_empty() || raw.len() > 40 {
            return None;
        }
        DateTime::parse_from_rfc3339(raw)
            .ok()
            .map(|stamp| stamp.with_timezone(&Utc))
    }
    (parse(start), parse(end))
}

async fn project_input(
    conn: &mut PgConnection,
    building_id: &str,
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
    input: PackInput,
) -> Result<InputGate> {
    match input {
        PackInput::Weather => project_weather(conn, building_id, start, end).await,
        PackInput::UtilityInterval => {
            project_utility(conn, building_id, start, end, UtilityKind::Interval).await
        }
        PackInput::UtilityMonthly => {
            project_utility(conn, building_id, start, end, UtilityKind::Monthly).await
        }
        PackInput::AuthorizedSeries => project_authorized_series(conn, building_id).await,
    }
}

async fn project_authorized_series(
    conn: &mut PgConnection,
    building_id: &str,
) -> Result<InputGate> {
    // Resolved binding metadata lives on point_map (overlay > NF tag > empty; #1429 /
    // sql/schema/11_point_map_binding_metadata.sql). Empty quantity stays NULL (unresolved).
    // Role→quantity defaults live in sql/fdd/postgres_helpers.sql (`fdd.quantity_for_sql_role`)
    // for assessability helpers only; they are not copied into this projection.
    let sql = "
         CREATE TEMP TABLE authorized_series ON COMMIT DROP AS
         SELECT
           pm.site_id,
           pm.openfdd_key,
           rm.equipment_id,
           rm.role,
           NULLIF(btrim(pm.unit), '') AS unit,
           NULLIF(btrim(pm.quantity), '') AS quantity,
           pm.referenced,
           pm.portal_point_id,
           pm.provider_instance_id,
           pm.haystack_id
         FROM point_map pm
         JOIN role_map rm
           ON rm.building_id = pm.site_id
          AND rm.openfdd_key = pm.openfdd_key
          AND rm.equipment_id = pm.equipment_id
          AND rm.role = pm.role
         JOIN equipment e
           ON e.building_id = $1
          AND e.equipment_id = rm.equipment_id
         WHERE pm.referenced
           AND rm.building_id = $1
           AND pm.site_id = (
             SELECT COALESCE(b.site_id, b.building_id)
             FROM building b
             WHERE b.building_id = $1
           )";
    sqlx::query(sql)
        .bind(building_id)
        .execute(&mut *conn)
        .await
        .context("create scoped authorized_series projection")?;
    Ok(InputGate::Ready(
        relation_stats(conn, "authorized_series").await?,
    ))
}

async fn project_weather(
    conn: &mut PgConnection,
    building_id: &str,
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
) -> Result<InputGate> {
    let equipment = stamped_equipment_count(conn, building_id, "weather").await?;
    let samples = weather_sample_count(conn, building_id, start, end).await?;
    let invalid = weather_invalid_unit_count(conn, building_id, start, end).await?;
    if invalid > 0 {
        return Ok(InputGate::Stop(RuleStop {
            status: "SKIP_INPUT_INVALID",
            failure_class: "input_invalid",
            notes: "weather samples use a unit that is not an admitted temperature unit".into(),
            input_condition: Some("invalid_unit"),
            relation: Some("weather".into()),
        }));
    }
    if samples == 0 {
        if history_has_local_weather(conn).await? {
            create_weather_table(conn).await?;
            return Ok(InputGate::Ready(json!({
                "rows": 0,
                "equipment_ids": [],
                "note": "weather projection empty; equipment-local web columns are present",
            })));
        }
        let condition = if equipment == 0 {
            "absent"
        } else {
            "present_but_empty"
        };
        let notes = if equipment == 0 {
            "weather input missing: no weather-stamped equipment in scope"
        } else {
            "weather input missing: weather equipment is present but has no samples in the window"
        };
        return Ok(InputGate::Stop(RuleStop {
            status: "SKIP_INPUT_MISSING",
            failure_class: "input_missing",
            notes: notes.into(),
            input_condition: Some(condition),
            relation: Some("weather".into()),
        }));
    }
    create_weather_table(conn).await?;
    // $1..$3 are building, start, and end. Admission binds follow those.
    let mut admit = crate::admitted_sample::AdmitBuilder::after_occupied(3);
    let oa = admit.admitted_on_sample("oa_t");
    let web = admit.admitted_on_sample("web_oa_t");
    let dew = admit.admitted_on_sample("web_oa_dp");
    let insert = format!(
        "INSERT INTO weather (timestamp_utc, oa_t, web_oa_t, web_oa_dp, source_equipment_id)
         SELECT s.ts,
           MAX(CASE WHEN a.role = 'oa_t' THEN {oa} END),
           MAX(CASE WHEN a.role = 'web_oa_t' THEN {web} END),
           MAX(CASE WHEN a.role = 'web_oa_dp' THEN {dew} END),
           a.equipment_id
         FROM sample s
         JOIN authorized_series a
           ON a.site_id = s.site_id AND a.openfdd_key = s.openfdd_key
         JOIN equipment e
           ON e.building_id = $1 AND e.equipment_id = a.equipment_id
         WHERE s.site_id = $1
           AND a.role IN ('oa_t', 'web_oa_t', 'web_oa_dp')
           AND lower(btrim(coalesce(e.equip_type, ''))) = 'weather'
           AND (
             SELECT count(*) FROM authorized_series c
             WHERE c.site_id = a.site_id
               AND c.equipment_id = a.equipment_id
               AND c.role = a.role
           ) = 1
           AND ($2::timestamptz IS NULL OR s.ts >= $2)
           AND ($3::timestamptz IS NULL OR s.ts < $3)
         GROUP BY a.equipment_id, s.ts"
    );
    crate::admitted_sample::apply_binds(
        sqlx::query(&insert).bind(building_id).bind(start).bind(end),
        admit.binds(),
    )
    .execute(&mut *conn)
    .await
    .context("insert scoped weather projection")?;
    Ok(InputGate::Ready(relation_stats(conn, "weather").await?))
}

fn weather_scope_predicate() -> &'static str {
    "site_id = $1
       AND openfdd_key IN (
         SELECT a.openfdd_key
         FROM authorized_series a
         JOIN equipment e
           ON e.building_id = $1 AND e.equipment_id = a.equipment_id
         WHERE a.site_id = $1
           AND a.role IN ('oa_t', 'web_oa_t', 'web_oa_dp')
           AND lower(btrim(coalesce(e.equip_type, ''))) = 'weather'
           AND (
             SELECT count(*) FROM authorized_series c
             WHERE c.site_id = a.site_id
               AND c.equipment_id = a.equipment_id
               AND c.role = a.role
           ) = 1
       )
       AND ($2::timestamptz IS NULL OR ts >= $2)
       AND ($3::timestamptz IS NULL OR ts < $3)"
}

async fn weather_sample_count(
    conn: &mut PgConnection,
    building_id: &str,
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
) -> Result<i64> {
    let sql = format!(
        "SELECT COUNT(*)::bigint FROM sample WHERE {}",
        weather_scope_predicate()
    );
    let count: i64 = sqlx::query_scalar(&sql)
        .bind(building_id)
        .bind(start)
        .bind(end)
        .fetch_one(&mut *conn)
        .await
        .context("count scoped weather samples")?;
    Ok(count)
}

async fn weather_invalid_unit_count(
    conn: &mut PgConnection,
    building_id: &str,
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
) -> Result<i64> {
    let sql = format!(
        "SELECT COUNT(*)::bigint FROM sample WHERE {}
           AND unit IS NOT NULL
           AND btrim(unit) <> ''
           AND lower(regexp_replace(unit, '[^a-zA-Z0-9]', '', 'g'))
               NOT IN ('c', 'degc', 'celsius', 'f', 'degf', 'fahrenheit')",
        weather_scope_predicate()
    );
    let count: i64 = sqlx::query_scalar(&sql)
        .bind(building_id)
        .bind(start)
        .bind(end)
        .fetch_one(&mut *conn)
        .await
        .context("count invalid weather units")?;
    Ok(count)
}

async fn create_weather_table(conn: &mut PgConnection) -> Result<()> {
    sqlx::query(
        "CREATE TEMP TABLE weather (
            timestamp_utc timestamptz,
            oa_t double precision,
            web_oa_t double precision,
            web_oa_dp double precision,
            source_equipment_id text
         ) ON COMMIT DROP",
    )
    .execute(&mut *conn)
    .await
    .context("create scoped weather projection")?;
    Ok(())
}

async fn history_has_local_weather(conn: &mut PgConnection) -> Result<bool> {
    for column in ["web_oa_t", "web_oa_dp"] {
        if temp_column_has_value(conn, column).await? {
            return Ok(true);
        }
    }
    Ok(false)
}

async fn temp_column_has_value(conn: &mut PgConnection, column: &str) -> Result<bool> {
    if column != "web_oa_t" && column != "web_oa_dp" {
        return Ok(false);
    }
    let exists: bool = sqlx::query_scalar(
        "SELECT EXISTS (
            SELECT 1
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            WHERE c.relname = 'history'
              AND c.relpersistence = 't'
              AND a.attname = $1
              AND a.attnum > 0
              AND NOT a.attisdropped
         )",
    )
    .bind(column)
    .fetch_one(&mut *conn)
    .await
    .context("history column lookup")?;
    if !exists {
        return Ok(false);
    }
    let sql = format!("SELECT EXISTS (SELECT 1 FROM history WHERE \"{column}\" IS NOT NULL)");
    let any: bool = sqlx::query_scalar(&sql)
        .fetch_one(&mut *conn)
        .await
        .context("history local weather")?;
    Ok(any)
}

#[derive(Clone, Copy)]
enum UtilityKind {
    Interval,
    Monthly,
}

impl UtilityKind {
    fn relation(self) -> &'static str {
        match self {
            Self::Interval => "utility_interval",
            Self::Monthly => "utility_monthly",
        }
    }

    fn role(self) -> &'static str {
        match self {
            Self::Interval => "kwh",
            Self::Monthly => "monthly_kwh",
        }
    }
}

async fn project_utility(
    conn: &mut PgConnection,
    building_id: &str,
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
    kind: UtilityKind,
) -> Result<InputGate> {
    let relation = kind.relation();
    let role = kind.role();
    let equipment = stamped_equipment_count(conn, building_id, "utility").await?;
    let contributors = utility_contributor_count(conn, building_id, role, start, end).await?;
    if contributors > 1 {
        return Ok(InputGate::Stop(RuleStop {
            status: "SKIP_UNSUPPORTED",
            failure_class: "unsupported",
            notes: format!(
                "{relation} has multiple utility-stamped equipment rows in scope; no approval policy selects one"
            ),
            input_condition: None,
            relation: Some(relation.into()),
        }));
    }
    let invalid = utility_invalid_unit_count(conn, building_id, role, start, end).await?;
    if invalid > 0 {
        return Ok(InputGate::Stop(RuleStop {
            status: "SKIP_INPUT_INVALID",
            failure_class: "input_invalid",
            notes: format!("{relation} samples use a unit that is not an admitted energy unit"),
            input_condition: Some("invalid_unit"),
            relation: Some(relation.into()),
        }));
    }
    if contributors == 0 {
        let condition = if equipment == 0 {
            "absent"
        } else {
            "present_but_empty"
        };
        let notes = if equipment == 0 {
            format!("{relation} input missing: no utility-stamped equipment in scope")
        } else {
            format!(
                "{relation} input missing: utility equipment is present but has no samples in the window"
            )
        };
        return Ok(InputGate::Stop(RuleStop {
            status: "SKIP_INPUT_MISSING",
            failure_class: "input_missing",
            notes,
            input_condition: Some(condition),
            relation: Some(relation.into()),
        }));
    }
    match kind {
        UtilityKind::Interval => create_utility_interval(conn, building_id, start, end).await?,
        UtilityKind::Monthly => create_utility_monthly(conn, building_id, start, end).await?,
    }
    Ok(InputGate::Ready(relation_stats(conn, relation).await?))
}

fn utility_scope_predicate() -> &'static str {
    "site_id = $1
       AND openfdd_key IN (
         SELECT a.openfdd_key
         FROM authorized_series a
         JOIN equipment e
           ON e.building_id = $1 AND e.equipment_id = a.equipment_id
         WHERE a.site_id = $1
           AND a.role = $4
           AND lower(btrim(coalesce(e.equip_type, ''))) = 'utility'
           AND (
             SELECT count(*) FROM authorized_series c
             WHERE c.site_id = a.site_id
               AND c.equipment_id = a.equipment_id
               AND c.role = a.role
           ) = 1
       )
       AND ($2::timestamptz IS NULL OR ts >= $2)
       AND ($3::timestamptz IS NULL OR ts < $3)"
}

async fn utility_contributor_count(
    conn: &mut PgConnection,
    building_id: &str,
    role: &str,
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
) -> Result<i64> {
    let sql = "SELECT COUNT(DISTINCT a.equipment_id)::bigint
         FROM sample s
         JOIN authorized_series a
           ON a.site_id = s.site_id AND a.openfdd_key = s.openfdd_key
         WHERE s.site_id = $1
           AND a.role = $4
           AND a.equipment_id IN (
             SELECT equipment_id FROM equipment
             WHERE building_id = $1
               AND lower(btrim(coalesce(equip_type, ''))) = 'utility'
           )
           AND (
             SELECT count(*) FROM authorized_series c
             WHERE c.site_id = a.site_id
               AND c.equipment_id = a.equipment_id
               AND c.role = a.role
           ) = 1
           AND ($2::timestamptz IS NULL OR s.ts >= $2)
           AND ($3::timestamptz IS NULL OR s.ts < $3)";
    let count: i64 = sqlx::query_scalar(sql)
        .bind(building_id)
        .bind(start)
        .bind(end)
        .bind(role)
        .fetch_one(&mut *conn)
        .await
        .context("count utility contributors")?;
    Ok(count)
}

async fn utility_invalid_unit_count(
    conn: &mut PgConnection,
    building_id: &str,
    role: &str,
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
) -> Result<i64> {
    let sql = format!(
        "SELECT COUNT(*)::bigint FROM sample WHERE {}
           AND unit IS NOT NULL
           AND btrim(unit) <> ''
           AND lower(regexp_replace(unit, '[^a-zA-Z0-9]', '', 'g'))
               NOT IN ('kwh', 'kilowatthour', 'kwhr')",
        utility_scope_predicate()
    );
    let count: i64 = sqlx::query_scalar(&sql)
        .bind(building_id)
        .bind(start)
        .bind(end)
        .bind(role)
        .fetch_one(&mut *conn)
        .await
        .context("count invalid utility units")?;
    Ok(count)
}

async fn create_utility_interval(
    conn: &mut PgConnection,
    building_id: &str,
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
) -> Result<()> {
    sqlx::query(
        "CREATE TEMP TABLE utility_interval (
            timestamp_utc timestamptz,
            kwh double precision,
            source_equipment_id text
         ) ON COMMIT DROP",
    )
    .execute(&mut *conn)
    .await
    .context("create scoped utility interval")?;
    let sql = "INSERT INTO utility_interval (timestamp_utc, kwh, source_equipment_id)
         SELECT s.ts, s.val, a.equipment_id
         FROM sample s
         JOIN authorized_series a
           ON a.site_id = s.site_id AND a.openfdd_key = s.openfdd_key
         WHERE s.site_id = $1
           AND a.role = $4
           AND a.equipment_id IN (
             SELECT equipment_id FROM equipment
             WHERE building_id = $1
               AND lower(btrim(coalesce(equip_type, ''))) = 'utility'
           )
           AND (
             SELECT count(*) FROM authorized_series c
             WHERE c.site_id = a.site_id
               AND c.equipment_id = a.equipment_id
               AND c.role = a.role
           ) = 1
           AND ($2::timestamptz IS NULL OR s.ts >= $2)
           AND ($3::timestamptz IS NULL OR s.ts < $3)
           AND s.val IS NOT NULL";
    sqlx::query(sql)
        .bind(building_id)
        .bind(start)
        .bind(end)
        .bind("kwh")
        .execute(&mut *conn)
        .await
        .context("insert scoped utility interval")?;
    Ok(())
}

async fn create_utility_monthly(
    conn: &mut PgConnection,
    building_id: &str,
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
) -> Result<()> {
    sqlx::query(
        "CREATE TEMP TABLE utility_monthly (
            billing_period varchar,
            kwh double precision,
            source_equipment_id text
         ) ON COMMIT DROP",
    )
    .execute(&mut *conn)
    .await
    .context("create scoped utility monthly")?;
    let sql = "INSERT INTO utility_monthly (billing_period, kwh, source_equipment_id)
         SELECT to_char(s.ts AT TIME ZONE 'UTC', 'YYYY-MM'),
                SUM(s.val),
                a.equipment_id
         FROM sample s
         JOIN authorized_series a
           ON a.site_id = s.site_id AND a.openfdd_key = s.openfdd_key
         WHERE s.site_id = $1
           AND a.role = $4
           AND a.equipment_id IN (
             SELECT equipment_id FROM equipment
             WHERE building_id = $1
               AND lower(btrim(coalesce(equip_type, ''))) = 'utility'
           )
           AND (
             SELECT count(*) FROM authorized_series c
             WHERE c.site_id = a.site_id
               AND c.equipment_id = a.equipment_id
               AND c.role = a.role
           ) = 1
           AND ($2::timestamptz IS NULL OR s.ts >= $2)
           AND ($3::timestamptz IS NULL OR s.ts < $3)
           AND s.val IS NOT NULL
         GROUP BY 1, a.equipment_id";
    sqlx::query(sql)
        .bind(building_id)
        .bind(start)
        .bind(end)
        .bind("monthly_kwh")
        .execute(&mut *conn)
        .await
        .context("insert scoped utility monthly")?;
    Ok(())
}

async fn stamped_equipment_count(
    conn: &mut PgConnection,
    building_id: &str,
    stamp: &str,
) -> Result<i64> {
    let predicate = match stamp {
        "weather" => "lower(btrim(coalesce(equip_type, ''))) = 'weather'",
        "utility" => "lower(btrim(coalesce(equip_type, ''))) = 'utility'",
        _ => return Ok(0),
    };
    let sql =
        format!("SELECT COUNT(*)::bigint FROM equipment WHERE building_id = $1 AND {predicate}");
    let count: i64 = sqlx::query_scalar(&sql)
        .bind(building_id)
        .fetch_one(&mut *conn)
        .await
        .context("count stamped equipment")?;
    Ok(count)
}

async fn relation_stats(conn: &mut PgConnection, relation: &str) -> Result<Value> {
    if relation == "authorized_series" {
        let ids: Vec<String> =
            sqlx::query_scalar("SELECT DISTINCT equipment_id FROM authorized_series ORDER BY 1")
                .fetch_all(&mut *conn)
                .await
                .context("authorized_series equipment ids")?;
        let site_ids: Vec<String> =
            sqlx::query_scalar("SELECT DISTINCT site_id FROM authorized_series ORDER BY 1")
                .fetch_all(&mut *conn)
                .await
                .context("authorized_series site ids")?;
        let rows: i64 = sqlx::query_scalar("SELECT COUNT(*)::bigint FROM authorized_series")
            .fetch_one(&mut *conn)
            .await
            .context("authorized_series row count")?;
        return Ok(json!({
            "rows": rows,
            "equipment_ids": ids,
            "site_ids": site_ids,
        }));
    }
    let (id_sql, value_sql) = match relation {
        "weather" => (
            "SELECT DISTINCT source_equipment_id FROM weather WHERE source_equipment_id IS NOT NULL ORDER BY 1",
            "SELECT MIN(web_oa_t)::float8, MAX(web_oa_t)::float8, MIN(oa_t)::float8, MAX(oa_t)::float8, COUNT(*)::bigint FROM weather",
        ),
        "utility_interval" => (
            "SELECT DISTINCT source_equipment_id FROM utility_interval WHERE source_equipment_id IS NOT NULL ORDER BY 1",
            "SELECT MIN(kwh)::float8, MAX(kwh)::float8, NULL::float8, NULL::float8, COUNT(*)::bigint FROM utility_interval",
        ),
        "utility_monthly" => (
            "SELECT DISTINCT source_equipment_id FROM utility_monthly WHERE source_equipment_id IS NOT NULL ORDER BY 1",
            "SELECT MIN(kwh)::float8, MAX(kwh)::float8, NULL::float8, NULL::float8, COUNT(*)::bigint FROM utility_monthly",
        ),
        _ => {
            return Ok(json!({
                "rows": 0,
                "equipment_ids": [],
            }));
        }
    };
    let ids: Vec<String> = sqlx::query_scalar(id_sql)
        .fetch_all(&mut *conn)
        .await
        .context("projection equipment ids")?;
    let row = sqlx::query(value_sql)
        .fetch_one(&mut *conn)
        .await
        .context("projection stats")?;
    let min_primary = row.try_get::<Option<f64>, _>(0).ok().flatten();
    let max_primary = row.try_get::<Option<f64>, _>(1).ok().flatten();
    let min_secondary = row.try_get::<Option<f64>, _>(2).ok().flatten();
    let max_secondary = row.try_get::<Option<f64>, _>(3).ok().flatten();
    let rows: i64 = row.try_get(4).context("projection row count")?;
    let (primary, secondary) = if relation == "weather" {
        ("web_oa_t", "oa_t")
    } else {
        ("kwh", "kwh")
    };
    let mut body = json!({
        "rows": rows,
        "equipment_ids": ids,
    });
    if let Some(obj) = body.as_object_mut() {
        obj.insert(format!("{primary}_min"), json!(min_primary));
        obj.insert(format!("{primary}_max"), json!(max_primary));
        obj.insert(format!("{secondary}_min"), json!(min_secondary));
        obj.insert(format!("{secondary}_max"), json!(max_secondary));
    }
    Ok(body)
}

fn mask_non_sql(sql: &str) -> String {
    let chars: Vec<char> = sql.chars().collect();
    let mut out = String::with_capacity(chars.len());
    let mut index = 0;
    while index < chars.len() {
        if chars[index] == '-' && chars.get(index + 1) == Some(&'-') {
            while index < chars.len() && chars[index] != '\n' {
                out.push(' ');
                index += 1;
            }
            continue;
        }
        if chars[index] == '/' && chars.get(index + 1) == Some(&'*') {
            out.push(' ');
            out.push(' ');
            index += 2;
            while index < chars.len()
                && !(chars[index] == '*' && chars.get(index + 1) == Some(&'/'))
            {
                out.push(' ');
                index += 1;
            }
            if index < chars.len() {
                out.push(' ');
                index += 1;
            }
            if index < chars.len() && chars[index] == '/' {
                out.push(' ');
                index += 1;
            }
            continue;
        }
        if chars[index] == '\'' {
            out.push(' ');
            index += 1;
            while index < chars.len() {
                if chars[index] == '\'' && chars.get(index + 1) == Some(&'\'') {
                    out.push(' ');
                    out.push(' ');
                    index += 2;
                    continue;
                }
                let done = chars[index] == '\'';
                out.push(' ');
                index += 1;
                if done {
                    break;
                }
            }
            continue;
        }
        out.push(chars[index]);
        index += 1;
    }
    out
}

fn is_ident(ch: char) -> bool {
    ch.is_ascii_alphanumeric() || ch == '_'
}

fn keyword_at(chars: &[char], index: usize, word: &[char]) -> bool {
    let end = index + word.len();
    if end > chars.len() || chars[index..end] != *word {
        return false;
    }
    let before_ok = index == 0 || !is_ident(chars[index - 1]);
    let after_ok = end == chars.len() || !is_ident(chars[end]);
    before_ok && after_ok
}

fn read_ident(chars: &[char], index: usize) -> Option<(String, usize)> {
    if index >= chars.len() || !(chars[index].is_ascii_alphabetic() || chars[index] == '_') {
        return None;
    }
    let mut end = index + 1;
    while end < chars.len() && is_ident(chars[end]) {
        end += 1;
    }
    Some((chars[index..end].iter().collect(), end))
}

fn skip_ws(chars: &[char], mut index: usize) -> usize {
    while index < chars.len() && chars[index].is_whitespace() {
        index += 1;
    }
    index
}

/// Relations named after FROM/JOIN that are not CTE names and not `history`.
pub fn external_relations(sql: &str) -> Vec<String> {
    let lower = mask_non_sql(&sql.to_ascii_lowercase());
    let chars: Vec<char> = lower.chars().collect();
    let mut ctes = std::collections::BTreeSet::new();
    let mut index = 0;
    while index < chars.len() {
        if let Some((name, after_name)) = read_ident(&chars, index) {
            let after_ws = skip_ws(&chars, after_name);
            if keyword_at(&chars, after_ws, &['a', 's']) {
                let after_as = skip_ws(&chars, after_ws + 2);
                if chars.get(after_as) == Some(&'(') {
                    ctes.insert(name);
                }
            }
            index = after_name;
            continue;
        }
        index += 1;
    }
    let mut found = std::collections::BTreeSet::new();
    index = 0;
    while index < chars.len() {
        let from_or_join = keyword_at(&chars, index, &['f', 'r', 'o', 'm'])
            || keyword_at(&chars, index, &['j', 'o', 'i', 'n']);
        let matched = if from_or_join { Some(4) } else { None };
        if let Some(len) = matched {
            let mut cursor = skip_ws(&chars, index + len);
            if keyword_at(&chars, cursor, &['o', 'n', 'l', 'y']) {
                cursor = skip_ws(&chars, cursor + 4);
            }
            if let Some((name, _)) = read_ident(&chars, cursor) {
                if name != "history" && !ctes.contains(&name) {
                    found.insert(name);
                }
            }
            index += len;
            continue;
        }
        index += 1;
    }
    found.into_iter().collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn relation_parser_ignores_ctes_and_names_pack_inputs() {
        let econ = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../sql/fdd/postgres/rules/econ6_econ_freezing.sql"
        ))
        .expect("econ6 sql");
        assert_eq!(external_relations(&econ), vec!["weather".to_string()]);
        let oat = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../sql/fdd/postgres/rules/oat_meteo_fault.sql"
        ))
        .expect("oat sql");
        assert_eq!(external_relations(&oat), vec!["weather".to_string()]);
        let sv_flat = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../sql/fdd/postgres/rules/sv_flatline.sql"
        ))
        .expect("sv flatline sql");
        let sv_relations = external_relations(&sv_flat);
        assert!(
            sv_relations.iter().any(|name| name == "authorized_series"),
            "sv rules must declare authorized_series pack input: {sv_relations:?}"
        );
        assert!(PackInput::parse("authorized_series").is_some());
        let missing_helper = PackStatus {
            checked: true,
            compatible: false,
            helper_installed: false,
            contract_installed: true,
            detail: "fdd.try_double is not installed".into(),
        };
        assert!(schema_stop("SELECT fdd.try_double('1')", &missing_helper).is_some());
        assert!(schema_stop("SELECT 1 FROM weather", &missing_helper).is_none());
        let with_cte = "WITH wx AS (SELECT 1 AS n) SELECT * FROM wx JOIN history ON true";
        assert!(external_relations(with_cte).is_empty());
        assert_eq!(
            external_relations("SELECT 1 FROM bas_submeter"),
            vec!["bas_submeter".to_string()]
        );
        assert!(sql_needs_helper(
            "fdd.try_double(trim(CAST(occ_mode AS VARCHAR)))"
        ));
        assert!(!sql_needs_helper("SELECT 1 FROM history"));
        let weather_sql = weather_scope_predicate();
        assert!(weather_sql.contains("site_id = $1"));
        assert!(weather_sql.contains("building_id = $1"));
        assert!(weather_sql.contains("= 'weather'"));
        assert!(!weather_sql.to_ascii_lowercase().contains(" like "));
        assert!(!weather_sql.contains("CREATE VIEW"));
        let (status, class) =
            classify_database_error("function fdd.try_double(text) does not exist");
        assert_eq!(status, "SCHEMA_INCOMPATIBLE");
        assert_eq!(class, "schema_incompatible");
        let (status, class) = classify_database_error("division by zero");
        assert_eq!(status, "ERROR");
        assert_eq!(class, "runtime_failure");
    }

    fn database_url() -> Option<String> {
        for key in [
            "OPENFDD_LIFECYCLE_DATABASE_URL",
            "OPENFDD_TEST_DATABASE_URL",
        ] {
            if let Ok(value) = std::env::var(key) {
                let value = value.trim().to_string();
                if !value.is_empty() {
                    return Some(value);
                }
            }
        }
        Some("postgresql://openfdd:openfdd@127.0.0.1:5432/openfdd".to_string())
    }

    fn explicit_database_url() -> bool {
        [
            "OPENFDD_LIFECYCLE_DATABASE_URL",
            "OPENFDD_TEST_DATABASE_URL",
        ]
        .into_iter()
        .any(|key| {
            std::env::var(key)
                .ok()
                .is_some_and(|value| !value.trim().is_empty())
        })
    }

    fn timescale_required() -> bool {
        std::env::var("OPENFDD_LIFECYCLE_DATABASE_REQUIRED")
            .ok()
            .is_some_and(|value| matches!(value.trim(), "1" | "true" | "yes"))
    }

    struct EnvHold {
        saved: Vec<(&'static str, Option<String>)>,
    }

    impl EnvHold {
        fn capture(keys: &[&'static str]) -> Self {
            Self {
                saved: keys
                    .iter()
                    .map(|key| (*key, std::env::var(key).ok()))
                    .collect(),
            }
        }
    }

    impl Drop for EnvHold {
        fn drop(&mut self) {
            for (key, value) in self.saved.drain(..) {
                match value {
                    Some(value) => std::env::set_var(key, value),
                    None => std::env::remove_var(key),
                }
            }
        }
    }

    struct DropDb {
        admin: String,
        name: String,
    }

    impl Drop for DropDb {
        fn drop(&mut self) {
            let admin = self.admin.clone();
            let name = self.name.clone();
            if !name
                .chars()
                .all(|ch| ch.is_ascii_alphanumeric() || ch == '_')
            {
                return;
            }
            let _ = std::thread::spawn(move || {
                let runtime = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("drop runtime");
                runtime.block_on(async move {
                    let Ok(pool) = sqlx::postgres::PgPoolOptions::new()
                        .max_connections(1)
                        .connect(&admin)
                        .await
                    else {
                        return;
                    };
                    let sql = format!("DROP DATABASE IF EXISTS {name} WITH (FORCE)");
                    let _ = sqlx::query(&sql).execute(&pool).await;
                });
            })
            .join();
        }
    }

    async fn create_database(admin_url: &str, name: &str) -> PgPool {
        let admin = sqlx::postgres::PgPoolOptions::new()
            .max_connections(1)
            .connect(admin_url)
            .await
            .expect("admin connect");
        let sql = format!("CREATE DATABASE {name}");
        sqlx::query(&sql)
            .execute(&admin)
            .await
            .expect("create database");
        let mut url = url::Url::parse(admin_url).expect("admin url");
        url.set_path(&format!("/{name}"));
        sqlx::postgres::PgPoolOptions::new()
            .max_connections(4)
            .connect(url.as_str())
            .await
            .expect("fresh connect")
    }

    fn admin_url(database_url: &str) -> String {
        let mut url = url::Url::parse(database_url).expect("database url");
        url.set_path("/postgres");
        url.to_string()
    }

    async fn apply_sql(pool: &PgPool, ddl: &[&str]) {
        for source in ddl {
            for stmt in crate::db_lifecycle::statements(source) {
                sqlx::query(&stmt)
                    .execute(pool)
                    .await
                    .unwrap_or_else(|err| {
                        let preview: String = stmt.chars().take(80).collect();
                        panic!("schema statement failed ({preview}): {err}");
                    });
            }
        }
    }

    async fn seed_dimensions(pool: &PgPool, site: &str, equipment: &[(&str, &str)]) {
        sqlx::query(
            "INSERT INTO site(site_id, dis) VALUES ($1, $1) ON CONFLICT (site_id) DO NOTHING",
        )
        .bind(site)
        .execute(pool)
        .await
        .expect("site");
        sqlx::query(
            "INSERT INTO building(building_id, site_id, dis) VALUES ($1, $1, $1) ON CONFLICT (building_id) DO NOTHING",
        )
        .bind(site)
        .execute(pool)
        .await
        .expect("building");
        for (id, kind) in equipment {
            sqlx::query(
                "INSERT INTO equipment(building_id, equipment_id, equip_type)
                 VALUES ($1, $2, $3)
                 ON CONFLICT (building_id, equipment_id) DO UPDATE SET equip_type = EXCLUDED.equip_type",
            )
            .bind(site)
            .bind(id)
            .bind(kind)
            .execute(pool)
            .await
            .expect("equipment");
        }
    }

    async fn put_sample(
        pool: &PgPool,
        site: &str,
        equipment_id: &str,
        role: &str,
        minutes: i64,
        value: f64,
        unit: Option<&str>,
    ) {
        let ts = DateTime::parse_from_rfc3339("2026-06-01T00:00:00Z")
            .expect("origin")
            .with_timezone(&Utc)
            + chrono::Duration::minutes(minutes);
        sqlx::query(
            "INSERT INTO sample (ts, site_id, openfdd_key, val, unit)
             VALUES ($1, $2, $3, $4, $5)",
        )
        .bind(ts)
        .bind(site)
        .bind(format!("{equipment_id}.{role}"))
        .bind(value)
        .bind(unit)
        .execute(pool)
        .await
        .expect("sample");
        crate::series_binding::bind_conventional_key(pool, site, &format!("{equipment_id}.{role}"))
            .await;
    }

    fn row<'a>(body: &'a Value, rule_id: &str, equipment_id: &str) -> &'a Value {
        body.get("results")
            .and_then(Value::as_array)
            .and_then(|rows| {
                rows.iter().find(|row| {
                    row.get("rule_id").and_then(Value::as_str) == Some(rule_id)
                        && row.get("equipment_id").and_then(Value::as_str) == Some(equipment_id)
                })
            })
            .unwrap_or_else(|| panic!("missing {rule_id}/{equipment_id} in {body}"))
    }

    fn hours(row: &Value) -> f64 {
        row.get("fault_hours")
            .and_then(Value::as_f64)
            .unwrap_or_else(|| panic!("fault_hours missing on {row}"))
    }

    const PRIOR_SCHEMA: &[&str] = &[
        include_str!("../../../sql/schema/00_extensions.sql"),
        include_str!("../../../sql/schema/01_bps_core.sql"),
        include_str!("../../../sql/schema/02_openfdd_dims.sql"),
        include_str!("../../../sql/schema/03_wide_history_helper.sql"),
        include_str!("../../../sql/schema/04_provider_hourly_jobs.sql"),
        include_str!("../../../sql/schema/04_ingest_queue.sql"),
        include_str!("../../../sql/schema/05_portal_inventory.sql"),
    ];

    async fn counts(pool: &PgPool, site: &str) -> (i64, i64, i64, i64) {
        let sample: i64 =
            sqlx::query_scalar("SELECT COUNT(*)::bigint FROM sample WHERE site_id = $1")
                .bind(site)
                .fetch_one(pool)
                .await
                .expect("sample count");
        let runs: i64 =
            sqlx::query_scalar("SELECT COUNT(*)::bigint FROM fdd_run WHERE site_id = $1")
                .bind(site)
                .fetch_one(pool)
                .await
                .expect("run count");
        let points: i64 =
            sqlx::query_scalar("SELECT COUNT(*)::bigint FROM point_map WHERE site_id = $1")
                .bind(site)
                .fetch_one(pool)
                .await
                .expect("point count");
        let equipment: i64 =
            sqlx::query_scalar("SELECT COUNT(*)::bigint FROM equipment WHERE building_id = $1")
                .bind(site)
                .fetch_one(pool)
                .await
                .expect("equipment count");
        (sample, runs, points, equipment)
    }

    #[expect(
        clippy::await_holding_lock,
        reason = "OPENFDD_* env is process-global while disposable pack databases are connected"
    )]
    #[tokio::test]
    async fn advertised_pack_rules_run_on_fresh_start_and_upgrade() {
        let Some(shared_url) = database_url() else {
            eprintln!("skip: no postgres url");
            return;
        };
        let admin = admin_url(&shared_url);
        let admin_pool = match sqlx::postgres::PgPoolOptions::new()
            .max_connections(1)
            .acquire_timeout(std::time::Duration::from_secs(3))
            .connect(&admin)
            .await
        {
            Ok(pool) => pool,
            Err(_) if explicit_database_url() => {
                panic!("pack database admin connect failed");
            }
            Err(_) => {
                eprintln!("skip: postgres admin unavailable");
                return;
            }
        };
        let timescale: bool = sqlx::query_scalar(
            "SELECT EXISTS (
                SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'
             )",
        )
        .fetch_one(&admin_pool)
        .await
        .unwrap_or(false);
        drop(admin_pool);
        if !timescale {
            if timescale_required() {
                panic!("timescaledb extension is not available");
            }
            eprintln!("skip: timescaledb extension is not available");
            return;
        }
        let _lock = crate::test_env_lock::lock_env();
        let results = tempfile::tempdir().expect("results");
        let _env = EnvHold::capture(&[
            "OPENFDD_DATABASE_URL",
            "OPENFDD_HISTORIAN",
            "OPENFDD_SQL_ROOT",
            "OPENFDD_SQL_RULES_DIR",
            "OPENFDD_RULE_RESULTS_DIR",
            "OPENFDD_RESET_DB",
            "OPENFDD_ALLOW_DESTRUCTIVE_DB",
        ]);
        std::env::remove_var("OPENFDD_RESET_DB");
        std::env::remove_var("OPENFDD_ALLOW_DESTRUCTIVE_DB");
        std::env::remove_var("OPENFDD_SQL_ROOT");
        std::env::remove_var("OPENFDD_SQL_RULES_DIR");
        std::env::set_var("OPENFDD_HISTORIAN", "timescale");
        std::env::set_var("OPENFDD_RULE_RESULTS_DIR", results.path());

        let fresh_name = format!("w1bfresh{}", uuid::Uuid::new_v4().simple());
        let upgrade_name = format!("w1bup{}", uuid::Uuid::new_v4().simple());
        let _drop_fresh = DropDb {
            admin: admin.clone(),
            name: fresh_name.clone(),
        };
        let _drop_upgrade = DropDb {
            admin: admin.clone(),
            name: upgrade_name.clone(),
        };
        let fresh = create_database(&admin, &fresh_name).await;
        let mut fresh_url = url::Url::parse(&admin).expect("admin");
        fresh_url.set_path(&format!("/{fresh_name}"));
        std::env::set_var("OPENFDD_DATABASE_URL", fresh_url.as_str());
        fdd_tsdb::clear_shared_pool();
        crate::db_lifecycle::apply_on_startup()
            .await
            .expect("ordinary fresh startup");
        let status = pack_status(&fresh).await.expect("fresh pack status");
        assert!(status.compatible, "{status:?}");
        assert!(status.helper_installed, "{status:?}");

        let site = format!("p{}", &uuid::Uuid::new_v4().simple().to_string()[..12]);
        let other = format!("q{}", &uuid::Uuid::new_v4().simple().to_string()[..12]);
        let bare = format!("r{}", &uuid::Uuid::new_v4().simple().to_string()[..12]);
        let empty_wx = format!("s{}", &uuid::Uuid::new_v4().simple().to_string()[..12]);
        let bad_unit = format!("t{}", &uuid::Uuid::new_v4().simple().to_string()[..12]);
        let short = format!("u{}", &uuid::Uuid::new_v4().simple().to_string()[..12]);
        let multi = format!("v{}", &uuid::Uuid::new_v4().simple().to_string()[..12]);
        seed_dimensions(
            &fresh,
            &site,
            &[
                ("eq_ahu", "ahu"),
                ("eq_vav", "vav"),
                ("eq_wx", "weather"),
                ("eq_util", "utility"),
            ],
        )
        .await;
        seed_dimensions(&fresh, &other, &[("eq_ahu", "ahu"), ("eq_wx", "weather")]).await;
        for minutes in [0_i64, 15, 30] {
            put_sample(&fresh, &site, "eq_ahu", "oa_damper_pct", minutes, 0.8, None).await;
            put_sample(&fresh, &site, "eq_ahu", "fan_status", minutes, 1.0, None).await;
            put_sample(&fresh, &site, "eq_ahu", "fan_cmd", minutes, 1.0, None).await;
            put_sample(&fresh, &site, "eq_ahu", "kwh", minutes, 10.0, Some("kWh")).await;
            put_sample(
                &fresh,
                &site,
                "eq_wx",
                "web_oa_t",
                minutes,
                10.0,
                Some("degF"),
            )
            .await;
            put_sample(&fresh, &site, "eq_util", "kwh", minutes, 40.0, Some("kWh")).await;
            put_sample(
                &fresh,
                &other,
                "eq_ahu",
                "oa_damper_pct",
                minutes,
                0.8,
                None,
            )
            .await;
            put_sample(&fresh, &other, "eq_ahu", "fan_status", minutes, 1.0, None).await;
            put_sample(&fresh, &other, "eq_ahu", "fan_cmd", minutes, 1.0, None).await;
            put_sample(
                &fresh,
                &other,
                "eq_wx",
                "web_oa_t",
                minutes,
                90.0,
                Some("degF"),
            )
            .await;
            put_sample(
                &fresh,
                &site,
                "eq_vav",
                "zone_t",
                minutes,
                80.0,
                Some("degF"),
            )
            .await;
            put_sample(&fresh, &site, "eq_vav", "occ_mode", minutes, 1.0, None).await;
        }
        put_sample(
            &fresh,
            &site,
            "eq_util",
            "monthly_kwh",
            0,
            1000.0,
            Some("kWh"),
        )
        .await;

        let payload = serde_json::json!({
            "building_id": site,
            "confirmation_seconds": 0,
        });
        let summary = crate::timescale_product::run_fdd_registry(&payload)
            .await
            .expect("fresh run");
        assert_eq!(summary["rules_failed"], json!(0), "{summary}");
        let run_id = summary["run_id"].as_str().expect("run id").to_string();
        assert!(summary["results"]
            .as_array()
            .expect("results")
            .iter()
            .all(
                |row| row.get("run_id").and_then(Value::as_str) == Some(run_id.as_str())
                    || row.get("rule_id").is_some()
            ));
        let manifest_path = results.path().join(format!(
            "building={site}/generations/{run_id}/manifest.json"
        ));
        assert!(manifest_path.is_file(), "one manifest at {manifest_path:?}");
        let manifests = std::fs::read_dir(
            results
                .path()
                .join(format!("building={site}/generations/{run_id}")),
        )
        .expect("generation")
        .filter_map(|entry| entry.ok())
        .filter(|entry| entry.file_name() == "manifest.json")
        .count();
        assert_eq!(manifests, 1);
        let manifest: Value =
            serde_json::from_str(&std::fs::read_to_string(&manifest_path).expect("read manifest"))
                .expect("manifest json");
        assert_eq!(manifest["run_id"], summary["run_id"]);
        assert_eq!(manifest["pack"]["compatible"], json!(true));
        assert_eq!(
            summary["rules_succeeded"].as_u64().unwrap()
                + summary["rules_failed"].as_u64().unwrap()
                + summary["rules_skipped"].as_u64().unwrap(),
            summary["rules_run"].as_u64().unwrap()
        );
        let errors: Vec<String> = summary["results"]
            .as_array()
            .expect("results")
            .iter()
            .filter(|row| {
                let status = row.get("status").and_then(Value::as_str).unwrap_or("");
                status == "ERROR" || status == "SCHEMA_INCOMPATIBLE"
            })
            .map(|row| format!("{row}"))
            .collect();
        assert!(errors.is_empty(), "pack rules errored: {errors:?}");

        let mut comparisons = 0u32;
        let econ = row(&summary, "ECON-6", "eq_ahu");
        assert_eq!(econ["status"], "FAULT");
        let econ_hours = hours(econ);
        assert!((econ_hours - 0.5).abs() < 1.0 / 3600.0, "{econ}");
        assert!(econ_hours > 0.0, "known answer must be nonzero");
        comparisons += 1;
        let scope = &econ["input_scope"]["relations"]["weather"];
        assert_eq!(scope["equipment_ids"], json!(["eq_wx"]));
        assert_eq!(scope["web_oa_t_min"], json!(10.0));
        assert_eq!(scope["web_oa_t_max"], json!(10.0));
        comparisons += 1;
        let vav = row(&summary, "VAV-1", "eq_vav");
        assert_eq!(vav["status"], "FAULT");
        assert!((hours(vav) - 0.5).abs() < 1.0 / 3600.0, "{vav}");
        assert!(hours(vav) > 0.0);
        comparisons += 1;
        let interval = row(&summary, "UTIL-INTERVAL", "eq_ahu");
        assert_eq!(interval["status"], "FAULT");
        assert!((hours(interval) - 720.0).abs() < 1e-6, "{interval}");
        comparisons += 1;
        let monthly = row(&summary, "UTIL-MONTHLY", "eq_ahu");
        assert_eq!(monthly["status"], "FAULT");
        assert!((hours(monthly) - 720.0).abs() < 1e-6, "{monthly}");
        comparisons += 1;
        assert!(comparisons >= 5, "known-answer comparisons were empty");

        let public_views: i64 = sqlx::query_scalar(
            "SELECT COUNT(*)::bigint
             FROM pg_class c
             JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public'
               AND c.relname IN ('weather', 'utility_interval', 'utility_monthly')",
        )
        .fetch_one(&fresh)
        .await
        .expect("view count");
        assert_eq!(public_views, 0, "pack inputs must not be global relations");

        let other_run = crate::timescale_product::run_fdd_registry(&serde_json::json!({
            "building_id": other,
            "rule_ids": ["ECON-6"],
            "confirmation_seconds": 0,
        }))
        .await
        .expect("other tenant");
        let other_row = row(&other_run, "ECON-6", "eq_ahu");
        assert_eq!(other_row["status"], "PASS");
        assert!((hours(other_row) - 0.0).abs() < 1e-9, "{other_row}");
        let covered = other_row["covered_hours"].as_f64().expect("covered");
        assert!((covered - 0.5).abs() < 1.0 / 3600.0, "{other_row}");
        assert_eq!(
            other_row["input_scope"]["relations"]["weather"]["web_oa_t_max"],
            json!(90.0)
        );
        comparisons += 1;
        assert!(comparisons > 0);

        fdd_tsdb::clear_shared_pool();
        let preview =
            crate::timescale_product::preview_confirmed_fault_for_rule(&site, "eq_ahu", "ECON-6")
                .await
                .expect("preview");
        assert_eq!(preview.len(), 3, "{preview:?}");
        assert!(preview.values().all(|flag| *flag), "{preview:?}");

        seed_dimensions(&fresh, &bare, &[("eq_ahu", "ahu")]).await;
        for minutes in [0_i64, 15] {
            put_sample(&fresh, &bare, "eq_ahu", "oa_damper_pct", minutes, 0.8, None).await;
            put_sample(&fresh, &bare, "eq_ahu", "fan_status", minutes, 1.0, None).await;
        }
        let missing = crate::timescale_product::run_fdd_registry(&serde_json::json!({
            "building_id": bare,
            "rule_ids": ["ECON-6"],
            "confirmation_seconds": 0,
        }))
        .await
        .expect("missing weather");
        let missing_row = row(&missing, "ECON-6", "eq_ahu");
        assert_eq!(missing_row["status"], "SKIP_INPUT_MISSING");
        assert_eq!(missing_row["failure_class"], "input_missing");
        assert_eq!(missing_row["input_condition"], "absent");
        assert_ne!(missing_row["status"], "PASS");
        assert_ne!(missing_row["status"], "ERROR");

        seed_dimensions(
            &fresh,
            &empty_wx,
            &[("eq_ahu", "ahu"), ("eq_wx", "weather")],
        )
        .await;
        for minutes in [0_i64, 15] {
            put_sample(
                &fresh,
                &empty_wx,
                "eq_ahu",
                "oa_damper_pct",
                minutes,
                0.8,
                None,
            )
            .await;
            put_sample(
                &fresh,
                &empty_wx,
                "eq_ahu",
                "fan_status",
                minutes,
                1.0,
                None,
            )
            .await;
        }
        let empty = crate::timescale_product::run_fdd_registry(&serde_json::json!({
            "building_id": empty_wx,
            "rule_ids": ["ECON-6"],
            "confirmation_seconds": 0,
        }))
        .await
        .expect("empty weather");
        let empty_row = row(&empty, "ECON-6", "eq_ahu");
        assert_eq!(empty_row["status"], "SKIP_INPUT_MISSING");
        assert_eq!(empty_row["input_condition"], "present_but_empty");
        assert_ne!(empty_row["status"], "PASS");

        seed_dimensions(
            &fresh,
            &bad_unit,
            &[("eq_ahu", "ahu"), ("eq_wx", "weather")],
        )
        .await;
        for minutes in [0_i64, 15] {
            put_sample(
                &fresh,
                &bad_unit,
                "eq_ahu",
                "oa_damper_pct",
                minutes,
                0.8,
                None,
            )
            .await;
            put_sample(
                &fresh,
                &bad_unit,
                "eq_ahu",
                "fan_status",
                minutes,
                1.0,
                None,
            )
            .await;
            put_sample(
                &fresh,
                &bad_unit,
                "eq_wx",
                "web_oa_t",
                minutes,
                10.0,
                Some("furlong"),
            )
            .await;
        }
        let invalid = crate::timescale_product::run_fdd_registry(&serde_json::json!({
            "building_id": bad_unit,
            "rule_ids": ["ECON-6"],
            "confirmation_seconds": 0,
        }))
        .await
        .expect("invalid unit");
        let invalid_row = row(&invalid, "ECON-6", "eq_ahu");
        assert_eq!(invalid_row["status"], "SKIP_INPUT_INVALID");
        assert_eq!(invalid_row["failure_class"], "input_invalid");
        assert_ne!(invalid_row["status"], "PASS");
        assert_ne!(invalid_row["status"], "ERROR");

        seed_dimensions(&fresh, &short, &[("eq_vav", "vav")]).await;
        put_sample(&fresh, &short, "eq_vav", "zone_t", 0, 80.0, Some("degF")).await;
        let short_run = crate::timescale_product::run_fdd_registry(&serde_json::json!({
            "building_id": short,
            "rule_ids": ["VAV-1"],
            "confirmation_seconds": 0,
        }))
        .await
        .expect("short history");
        let short_row = row(&short_run, "VAV-1", "eq_vav");
        assert_eq!(short_row["status"], "SKIP_SHORT_HISTORY");
        assert_eq!(short_row["input_condition"], "short_history");
        assert_ne!(short_row["status"], "PASS");

        seed_dimensions(
            &fresh,
            &multi,
            &[
                ("eq_ahu", "ahu"),
                ("eq_util_a", "utility"),
                ("eq_util_b", "utility"),
            ],
        )
        .await;
        for minutes in [0_i64, 15] {
            put_sample(&fresh, &multi, "eq_ahu", "kwh", minutes, 10.0, Some("kWh")).await;
            put_sample(
                &fresh,
                &multi,
                "eq_util_a",
                "kwh",
                minutes,
                40.0,
                Some("kWh"),
            )
            .await;
            put_sample(
                &fresh,
                &multi,
                "eq_util_b",
                "kwh",
                minutes,
                50.0,
                Some("kWh"),
            )
            .await;
        }
        let ambiguous = crate::timescale_product::run_fdd_registry(&serde_json::json!({
            "building_id": multi,
            "rule_ids": ["UTIL-INTERVAL"],
            "confirmation_seconds": 0,
        }))
        .await
        .expect("ambiguous utility");
        let ambiguous_row = row(&ambiguous, "UTIL-INTERVAL", "eq_ahu");
        assert_eq!(ambiguous_row["status"], "SKIP_UNSUPPORTED");
        assert_eq!(ambiguous_row["failure_class"], "unsupported");
        assert_ne!(ambiguous_row["status"], "PASS");

        let mut tx = fresh.begin().await.expect("tx");
        sqlx::query(
            "CREATE TEMP TABLE history (equipment_id text, timestamp_utc timestamptz) ON COMMIT DROP",
        )
        .execute(&mut *tx)
        .await
        .expect("history");
        sqlx::query(
            "INSERT INTO history VALUES ('eq', '2026-06-01T00:00:00Z'), ('eq', '2026-06-01T00:15:00Z')",
        )
        .execute(&mut *tx)
        .await
        .expect("history rows");
        let gate = prepare_rule_inputs(
            &mut tx,
            &site,
            None,
            None,
            "SELECT 1 FROM bas_submeter",
            true,
        )
        .await
        .expect("unsupported gate");
        match gate {
            InputGate::Stop(stop) => {
                assert_eq!(stop.status, "SKIP_UNSUPPORTED");
                assert_eq!(stop.relation.as_deref(), Some("bas_submeter"));
            }
            InputGate::Ready(scope) => panic!("unsupported relation ran: {scope}"),
        }
        let _ = tx.rollback().await;
        let runtime = sqlx::query("SELECT (1/0)::int")
            .fetch_one(&fresh)
            .await
            .expect_err("division");
        let (status_token, class) = classify_database_error(&runtime.to_string());
        assert_eq!(status_token, "ERROR");
        assert_eq!(class, "runtime_failure");

        sqlx::query("DROP FUNCTION fdd.try_double(text)")
            .execute(&fresh)
            .await
            .expect("drop helper");
        fdd_tsdb::clear_shared_pool();
        let broken = crate::timescale_product::run_fdd_registry(&serde_json::json!({
            "building_id": site,
            "rule_ids": ["VAV-1", "ECON-6"],
            "confirmation_seconds": 0,
        }))
        .await
        .expect("missing helper run");
        let broken_vav = broken["results"]
            .as_array()
            .expect("rows")
            .iter()
            .find(|row| row["rule_id"] == "VAV-1")
            .expect("vav");
        assert_eq!(broken_vav["status"], "SCHEMA_INCOMPATIBLE");
        assert_ne!(broken_vav["status"], "PASS");
        assert_eq!(broken["run_status"], "partial");
        assert_eq!(broken["rules_failed"], 1);
        let mut readiness = json!({"ok": true, "clean": true, "dirty_reasons": []});
        attach_pack_readiness(&mut readiness).await;
        assert_eq!(readiness["clean"], json!(false), "{readiness}");
        assert_eq!(readiness["pack"]["compatible"], json!(false));
        assert!(readiness["dirty_reasons"]
            .as_array()
            .expect("reasons")
            .iter()
            .any(|reason| reason == "schema_incompatible"));
        crate::db_lifecycle::apply_on_startup()
            .await
            .expect("restore helper");
        let restored = pack_status(&fresh).await.expect("restored");
        assert!(restored.compatible, "{restored:?}");

        let upgrade = create_database(&admin, &upgrade_name).await;
        apply_sql(&upgrade, PRIOR_SCHEMA).await;
        let kept = format!("k{}", &uuid::Uuid::new_v4().simple().to_string()[..12]);
        seed_dimensions(&upgrade, &kept, &[("eq_ahu", "ahu")]).await;
        put_sample(&upgrade, &kept, "eq_ahu", "fan_status", 0, 1.0, None).await;
        sqlx::query(
            "INSERT INTO point_map (site_id, openfdd_key, haystack_id, role, equipment_id)
             VALUES ($1, 'eq_ahu.fan_status', 'point-kept', 'fan_status', 'eq_ahu')",
        )
        .bind(&kept)
        .execute(&upgrade)
        .await
        .expect("point");
        sqlx::query(
            "INSERT INTO fdd_run (site_id, equipment_id, rule_id, window_start, window_end, status)
             VALUES ($1, 'eq_ahu', 'FC1', '2026-06-01T00:00:00Z', '2026-06-02T00:00:00Z', 'PASS')",
        )
        .bind(&kept)
        .execute(&upgrade)
        .await
        .expect("fdd_run");
        let before = counts(&upgrade, &kept).await;
        assert_eq!(before, (1, 1, 1, 1));
        let mut upgrade_url = url::Url::parse(&admin).expect("admin");
        upgrade_url.set_path(&format!("/{upgrade_name}"));
        std::env::set_var("OPENFDD_DATABASE_URL", upgrade_url.as_str());
        fdd_tsdb::clear_shared_pool();
        crate::db_lifecycle::apply_on_startup()
            .await
            .expect("upgrade startup");
        let after = counts(&upgrade, &kept).await;
        assert_eq!(after, before, "upgrade changed historian rows");
        let upgraded = pack_status(&upgrade).await.expect("upgraded pack");
        assert!(upgraded.compatible, "{upgraded:?}");
        crate::db_lifecycle::apply_on_startup()
            .await
            .expect("second upgrade");
        assert_eq!(counts(&upgrade, &kept).await, before);
        for minutes in [0_i64, 15, 30] {
            put_sample(
                &upgrade,
                &kept,
                "eq_vav",
                "zone_t",
                minutes,
                80.0,
                Some("degF"),
            )
            .await;
            put_sample(&upgrade, &kept, "eq_vav", "occ_mode", minutes, 1.0, None).await;
        }
        sqlx::query(
            "INSERT INTO equipment(building_id, equipment_id, equip_type) VALUES ($1, 'eq_vav', 'vav')",
        )
        .bind(&kept)
        .execute(&upgrade)
        .await
        .expect("vav");
        fdd_tsdb::clear_shared_pool();
        let upgraded_run = crate::timescale_product::run_fdd_registry(&serde_json::json!({
            "building_id": kept,
            "rule_ids": ["VAV-1"],
            "confirmation_seconds": 0,
        }))
        .await
        .expect("upgrade vav");
        let upgraded_vav = row(&upgraded_run, "VAV-1", "eq_vav");
        assert_eq!(upgraded_vav["status"], "FAULT");
        assert!(
            (hours(upgraded_vav) - 0.5).abs() < 1.0 / 3600.0,
            "{upgraded_vav}"
        );
        assert_eq!(
            counts(&upgrade, &kept).await.1,
            1,
            "upgrade run deleted fdd_run"
        );
        fresh.close().await;
        upgrade.close().await;
        fdd_tsdb::clear_shared_pool();
    }

    #[expect(
        clippy::await_holding_lock,
        reason = "OPENFDD_* env is process-global while disposable pack databases are connected"
    )]
    #[tokio::test]
    async fn sv_range_skips_humidity_without_binding_unit() {
        let Some(shared_url) = database_url() else {
            eprintln!("skip: no postgres url");
            return;
        };
        let admin = admin_url(&shared_url);
        let admin_pool = match sqlx::postgres::PgPoolOptions::new()
            .max_connections(1)
            .acquire_timeout(std::time::Duration::from_secs(3))
            .connect(&admin)
            .await
        {
            Ok(pool) => pool,
            Err(_) if explicit_database_url() => {
                panic!("pack database admin connect failed");
            }
            Err(_) => {
                eprintln!("skip: postgres admin unavailable");
                return;
            }
        };
        let timescale: bool = sqlx::query_scalar(
            "SELECT EXISTS (
                SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'
             )",
        )
        .fetch_one(&admin_pool)
        .await
        .unwrap_or(false);
        drop(admin_pool);
        if !timescale {
            if timescale_required() {
                panic!("timescaledb extension is not available");
            }
            eprintln!("skip: timescaledb extension is not available");
            return;
        }
        let _lock = crate::test_env_lock::lock_env();
        let results = tempfile::tempdir().expect("results");
        let _env = EnvHold::capture(&[
            "OPENFDD_DATABASE_URL",
            "OPENFDD_HISTORIAN",
            "OPENFDD_SQL_ROOT",
            "OPENFDD_SQL_RULES_DIR",
            "OPENFDD_RULE_RESULTS_DIR",
        ]);
        std::env::remove_var("OPENFDD_RESET_DB");
        std::env::remove_var("OPENFDD_ALLOW_DESTRUCTIVE_DB");
        std::env::remove_var("OPENFDD_SQL_ROOT");
        std::env::remove_var("OPENFDD_SQL_RULES_DIR");
        std::env::set_var("OPENFDD_HISTORIAN", "timescale");
        std::env::set_var("OPENFDD_RULE_RESULTS_DIR", results.path());

        let db_name = format!("w3bunit{}", uuid::Uuid::new_v4().simple());
        let _drop = DropDb {
            admin: admin.clone(),
            name: db_name.clone(),
        };
        let pool = create_database(&admin, &db_name).await;
        let mut url = url::Url::parse(&admin).expect("admin");
        url.set_path(&format!("/{db_name}"));
        std::env::set_var("OPENFDD_DATABASE_URL", url.as_str());
        fdd_tsdb::clear_shared_pool();
        crate::db_lifecycle::apply_on_startup()
            .await
            .expect("db startup");

        let site = format!("u{}", &uuid::Uuid::new_v4().simple().to_string()[..10]);
        seed_dimensions(&pool, &site, &[("eq_ahu", "ahu")]).await;
        for minutes in [0_i64, 5, 10, 15, 20] {
            put_sample(&pool, &site, "eq_ahu", "fan_status", minutes, 1.0, None).await;
            put_sample(&pool, &site, "eq_ahu", "ra_h", minutes, 150.0, None).await;
        }
        let run = crate::timescale_product::run_fdd_registry(&serde_json::json!({
            "building_id": site,
            "rule_ids": ["SV-RANGE", "SV-FLATLINE", "SV-STALE"],
            "confirmation_seconds": 0,
        }))
        .await
        .expect("sv sweep run");
        let range = row(&run, "SV-RANGE", "eq_ahu");
        assert_eq!(range["status"], "OK", "{range}");
        assert!(
            hours(range).abs() < 1.0 / 3600.0,
            "ununit ra_h must not fault: {range}"
        );
        let flat = row(&run, "SV-FLATLINE", "eq_ahu");
        assert_eq!(flat["status"], "OK", "{flat}");
        let stale = row(&run, "SV-STALE", "eq_ahu");
        assert_eq!(stale["status"], "OK", "{stale}");

        sqlx::query(
            "UPDATE point_map SET unit = '%RH'
             WHERE site_id = $1 AND equipment_id = 'eq_ahu' AND role = 'ra_h'",
        )
        .bind(&site)
        .execute(&pool)
        .await
        .expect("unit");
        fdd_tsdb::clear_shared_pool();
        let run2 = crate::timescale_product::run_fdd_registry(&serde_json::json!({
            "building_id": site,
            "rule_ids": ["SV-RANGE"],
            "confirmation_seconds": 0,
        }))
        .await
        .expect("sv range with unit");
        let range2 = row(&run2, "SV-RANGE", "eq_ahu");
        assert_eq!(range2["status"], "FAULT", "{range2}");
        assert!(hours(range2) > 0.0, "{range2}");
        pool.close().await;
        fdd_tsdb::clear_shared_pool();
    }

    #[expect(
        clippy::await_holding_lock,
        reason = "OPENFDD_* env is process-global while disposable pack databases are connected"
    )]
    #[tokio::test]
    async fn t1408_2_sv_pack_flags_stuck_humidity_not_setpoint() {
        let Some(shared_url) = database_url() else {
            eprintln!("skip: no postgres url");
            return;
        };
        let admin = admin_url(&shared_url);
        let admin_pool = match sqlx::postgres::PgPoolOptions::new()
            .max_connections(1)
            .acquire_timeout(std::time::Duration::from_secs(3))
            .connect(&admin)
            .await
        {
            Ok(pool) => pool,
            Err(_) if explicit_database_url() => {
                panic!("pack database admin connect failed");
            }
            Err(_) => {
                eprintln!("skip: postgres admin unavailable");
                return;
            }
        };
        let timescale: bool = sqlx::query_scalar(
            "SELECT EXISTS (
                SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'
             )",
        )
        .fetch_one(&admin_pool)
        .await
        .unwrap_or(false);
        drop(admin_pool);
        if !timescale {
            if timescale_required() {
                panic!("timescaledb extension is not available");
            }
            eprintln!("skip: timescaledb extension is not available");
            return;
        }
        let _lock = crate::test_env_lock::lock_env();
        let results = tempfile::tempdir().expect("results");
        let _env = EnvHold::capture(&[
            "OPENFDD_DATABASE_URL",
            "OPENFDD_HISTORIAN",
            "OPENFDD_SQL_ROOT",
            "OPENFDD_SQL_RULES_DIR",
            "OPENFDD_RULE_RESULTS_DIR",
        ]);
        std::env::remove_var("OPENFDD_RESET_DB");
        std::env::remove_var("OPENFDD_ALLOW_DESTRUCTIVE_DB");
        std::env::remove_var("OPENFDD_SQL_ROOT");
        std::env::remove_var("OPENFDD_SQL_RULES_DIR");
        std::env::set_var("OPENFDD_HISTORIAN", "timescale");
        std::env::set_var("OPENFDD_RULE_RESULTS_DIR", results.path());

        let db_name = format!("t14082{}", uuid::Uuid::new_v4().simple());
        let _drop = DropDb {
            admin: admin.clone(),
            name: db_name.clone(),
        };
        let pool = create_database(&admin, &db_name).await;
        let mut url = url::Url::parse(&admin).expect("admin");
        url.set_path(&format!("/{db_name}"));
        std::env::set_var("OPENFDD_DATABASE_URL", url.as_str());
        fdd_tsdb::clear_shared_pool();
        crate::db_lifecycle::apply_on_startup()
            .await
            .expect("db startup");

        let site = format!("s{}", &uuid::Uuid::new_v4().simple().to_string()[..10]);
        let foreign = format!("f{}", &uuid::Uuid::new_v4().simple().to_string()[..10]);
        seed_dimensions(&pool, &site, &[("eq_ahu", "ahu"), ("eq_sp_only", "ahu")]).await;
        seed_dimensions(&pool, &foreign, &[("eq_ahu", "ahu")]).await;
        for minutes in (0..269_i64).map(|idx| idx * 5) {
            put_sample(&pool, &site, "eq_ahu", "fan_status", minutes, 1.0, None).await;
            put_sample(&pool, &site, "eq_ahu", "ra_h", minutes, 45.0, Some("%RH")).await;
            put_sample(&pool, &site, "eq_ahu", "sat_sp", minutes, 55.0, None).await;
            put_sample(&pool, &site, "eq_sp_only", "fan_status", minutes, 1.0, None).await;
            put_sample(&pool, &site, "eq_sp_only", "sat_sp", minutes, 55.0, None).await;
        }
        for minutes in (0..269_i64).map(|idx| idx * 5) {
            put_sample(&pool, &foreign, "eq_ahu", "fan_status", minutes, 1.0, None).await;
            put_sample(
                &pool,
                &foreign,
                "eq_ahu",
                "ra_h",
                minutes,
                150.0,
                Some("%RH"),
            )
            .await;
        }
        sqlx::query(
            "UPDATE point_map SET unit = '%RH'
             WHERE site_id = $1 AND equipment_id = 'eq_ahu' AND role = 'ra_h'",
        )
        .bind(&site)
        .execute(&pool)
        .await
        .expect("humidity unit");
        sqlx::query(
            "UPDATE point_map SET unit = '%RH'
             WHERE site_id = $1 AND equipment_id = 'eq_ahu' AND role = 'ra_h'",
        )
        .bind(&foreign)
        .execute(&pool)
        .await
        .expect("foreign humidity unit");

        fdd_tsdb::clear_shared_pool();
        let run = crate::timescale_product::run_fdd_registry(&serde_json::json!({
            "building_id": site,
            "rule_ids": ["SV-RANGE", "SV-FLATLINE", "SV-STALE"],
            "confirmation_seconds": 0,
        }))
        .await
        .expect("t1408-2 sv pack run");

        let range = row(&run, "SV-RANGE", "eq_ahu");
        assert_ne!(range["status"], "SKIP_UNSUPPORTED", "{range}");
        assert_eq!(range["status"], "OK", "{range}");
        assert!(
            hours(range).abs() < 1.0 / 3600.0,
            "in-range humidity must not range-fault: {range}"
        );

        let flat = row(&run, "SV-FLATLINE", "eq_ahu");
        assert_ne!(flat["status"], "SKIP_UNSUPPORTED", "{flat}");
        assert_eq!(flat["status"], "FAULT", "{flat}");
        assert!(hours(flat) > 0.0, "{flat}");
        let scope = flat
            .get("input_scope")
            .and_then(Value::as_object)
            .expect("input_scope");
        let auth = scope
            .get("relations")
            .and_then(Value::as_object)
            .and_then(|rels| rels.get("authorized_series"))
            .expect("authorized_series pack projection");
        assert!(
            auth.get("rows")
                .and_then(Value::as_i64)
                .is_some_and(|n| n > 0),
            "{auth}"
        );
        let site_ids = auth
            .get("site_ids")
            .and_then(Value::as_array)
            .expect("authorized_series site_ids");
        assert_eq!(site_ids.len(), 1, "{auth}");
        assert_eq!(site_ids[0].as_str(), Some(site.as_str()), "{auth}");
        assert!(
            !site_ids
                .iter()
                .any(|id| id.as_str() == Some(foreign.as_str())),
            "foreign site must not appear in scoped authorized_series: {auth}"
        );

        let stale = row(&run, "SV-STALE", "eq_ahu");
        assert_ne!(stale["status"], "SKIP_UNSUPPORTED", "{stale}");
        assert_eq!(stale["status"], "FAULT", "{stale}");
        assert!(hours(stale) > 0.0, "{stale}");

        let flat_sp = row(&run, "SV-FLATLINE", "eq_sp_only");
        assert_ne!(flat_sp["status"], "SKIP_UNSUPPORTED", "{flat_sp}");
        assert_eq!(
            flat_sp["status"], "OK",
            "constant sat_sp alone must not flatline-fault: {flat_sp}"
        );
        let stale_sp = row(&run, "SV-STALE", "eq_sp_only");
        assert_ne!(stale_sp["status"], "SKIP_UNSUPPORTED", "{stale_sp}");
        assert_eq!(
            stale_sp["status"], "OK",
            "constant sat_sp alone must not stale-fault: {stale_sp}"
        );

        fdd_tsdb::clear_shared_pool();
        let foreign_run = crate::timescale_product::run_fdd_registry(&serde_json::json!({
            "building_id": foreign,
            "rule_ids": ["SV-RANGE"],
            "confirmation_seconds": 0,
        }))
        .await
        .expect("foreign sv range positive control");
        let foreign_range = row(&foreign_run, "SV-RANGE", "eq_ahu");
        assert_eq!(
            foreign_range["status"], "FAULT",
            "out-of-range foreign humidity must range-fault: {foreign_range}"
        );
        assert!(hours(foreign_range) > 0.0, "{foreign_range}");

        pool.close().await;
        fdd_tsdb::clear_shared_pool();
    }
}
