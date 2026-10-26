//! Sample admission into the imperial-f-v1 pack ABI.
//!
//! `authorized_series.unit` is not the sample unit. The sample columns are
//! `s.val` and `s.unit`. A role selects one closed expression kind. It is not
//! SQL text. Conversion factors and unit tokens are bound parameters.

use sqlx::postgres::PgArguments;
use sqlx::query::Query;
use sqlx::Postgres;

const UNIT_TOKEN: &str = "lower(regexp_replace(coalesce(s.unit, ''), '[^a-zA-Z0-9]', '', 'g'))";

const CELSIUS_TOKENS: &[&str] = &["c", "degc", "celsius"];
const PASCAL_TOKENS: &[&str] = &["pa", "pascal"];
const LPS_TOKENS: &[&str] = &["lps", "ls", "lpers"];

/// One bound value appended after the caller's own parameters.
#[derive(Debug, Clone, Copy, PartialEq)]
pub(crate) enum AdmitBind {
    TextList(&'static [&'static str]),
    Float(f64),
}

/// Allocates `$n` placeholders for one statement.
pub(crate) struct AdmitBuilder {
    next_param: usize,
    binds: Vec<AdmitBind>,
}

impl AdmitBuilder {
    /// `occupied` is how many parameters the caller already binds (`$1..=$occupied`).
    pub(crate) fn after_occupied(occupied: usize) -> Self {
        Self {
            next_param: occupied.saturating_add(1),
            binds: Vec::new(),
        }
    }

    /// SQL fragment for `role`. The role string is not copied into the fragment.
    pub(crate) fn admitted_on_sample(&mut self, role: &str) -> String {
        let sql = if fdd_core::is_temperature_role(role) {
            self.temperature_expr()
        } else if fdd_core::is_pressure_role(role) {
            self.scaled_expr(PASCAL_TOKENS, fdd_core::units::PA_PER_IN_WC)
        } else if fdd_core::is_flow_role(role) {
            self.scaled_expr(LPS_TOKENS, fdd_core::units::LPS_PER_CFM)
        } else {
            "s.val".to_string()
        };
        debug_assert!(
            !sql.contains('{') && !sql.contains('}'),
            "admission SQL is interpolated into a format string"
        );
        sql
    }

    pub(crate) fn binds(&self) -> &[AdmitBind] {
        &self.binds
    }

    fn temperature_expr(&mut self) -> String {
        let tokens = self.alloc(AdmitBind::TextList(CELSIUS_TOKENS));
        let numerator = self.alloc(AdmitBind::Float(9.0));
        let denominator = self.alloc(AdmitBind::Float(5.0));
        let offset = self.alloc(AdmitBind::Float(32.0));
        let mut then = String::from("(s.val * ");
        push_param(&mut then, numerator, "::float8");
        then.push_str(" / ");
        push_param(&mut then, denominator, "::float8");
        then.push_str(") + ");
        push_param(&mut then, offset, "::float8");
        case_expr(tokens, &then)
    }

    fn scaled_expr(&mut self, tokens: &'static [&'static str], divisor: f64) -> String {
        let tokens = self.alloc(AdmitBind::TextList(tokens));
        let divisor = self.alloc(AdmitBind::Float(divisor));
        let mut then = String::from("s.val / ");
        push_param(&mut then, divisor, "::float8");
        case_expr(tokens, &then)
    }

    fn alloc(&mut self, bind: AdmitBind) -> usize {
        let index = self.next_param;
        self.next_param = self.next_param.saturating_add(1);
        self.binds.push(bind);
        index
    }
}

fn case_expr(token_param: usize, then_body: &str) -> String {
    let mut sql = String::from("CASE WHEN ");
    sql.push_str(UNIT_TOKEN);
    sql.push_str(" = ANY(");
    push_param(&mut sql, token_param, "::text[]");
    sql.push_str(") THEN ");
    sql.push_str(then_body);
    sql.push_str(" ELSE s.val END");
    sql
}

fn push_param(out: &mut String, index: usize, cast: &str) {
    out.push('$');
    out.push_str(&index.to_string());
    out.push_str(cast);
}

type PgQuery<'q> = Query<'q, Postgres, PgArguments>;

pub(crate) fn apply_binds<'q>(mut query: PgQuery<'q>, binds: &[AdmitBind]) -> PgQuery<'q> {
    for bind in binds {
        query = match bind {
            AdmitBind::TextList(items) => {
                let owned: Vec<String> = items.iter().copied().map(str::to_string).collect();
                query.bind(owned)
            }
            AdmitBind::Float(value) => query.bind(*value),
        };
    }
    query
}

#[cfg(test)]
mod tests {
    use super::*;
    use sqlx::Row;

    const TEMPERATURE_SQL: &str = "CASE WHEN lower(regexp_replace(coalesce(s.unit, ''), '[^a-zA-Z0-9]', '', 'g')) = ANY($1::text[]) THEN (s.val * $2::float8 / $3::float8) + $4::float8 ELSE s.val END";
    const PRESSURE_SQL: &str = "CASE WHEN lower(regexp_replace(coalesce(s.unit, ''), '[^a-zA-Z0-9]', '', 'g')) = ANY($1::text[]) THEN s.val / $2::float8 ELSE s.val END";
    const FLOW_SQL: &str = PRESSURE_SQL;

    fn fresh(role: &str) -> (String, Vec<AdmitBind>) {
        let mut builder = AdmitBuilder::after_occupied(0);
        let sql = builder.admitted_on_sample(role);
        (sql, builder.binds().to_vec())
    }

    fn shape(sql: &str) -> String {
        let mut out = String::new();
        let mut chars = sql.chars().peekable();
        while let Some(ch) = chars.next() {
            if ch == '$' {
                out.push('$');
                while chars.peek().is_some_and(|next| next.is_ascii_digit()) {
                    chars.next();
                }
                out.push('#');
            } else {
                out.push(ch);
            }
        }
        out
    }

    /// The pre-builder expression, kept only as the behaviour oracle.
    fn legacy_admitted_on_sample(role: &str) -> String {
        fdd_core::sql_admit_val_expr(role)
            .replace("unit", "s.unit")
            .replace("val", "s.val")
    }

    fn legacy_kind(role: &str) -> &'static str {
        let sql = legacy_admitted_on_sample(role);
        if sql.contains("celsius") {
            "temperature"
        } else if sql.contains("pascal") {
            "pressure"
        } else if sql.contains("lpers") {
            "flow"
        } else {
            "identity"
        }
    }

    fn assert_text_list(bind: &AdmitBind, expected: &[&str]) {
        match bind {
            AdmitBind::TextList(items) => assert_eq!(*items, expected),
            AdmitBind::Float(_) => panic!("expected text list"),
        }
    }

    fn assert_float(bind: &AdmitBind, expected: f64) {
        match bind {
            AdmitBind::Float(value) => assert_eq!(value.to_bits(), expected.to_bits()),
            AdmitBind::TextList(_) => panic!("expected float bind"),
        }
    }

    #[test]
    fn representative_roles_match_legacy_kind_and_closed_sql() {
        let samples = [
            ("sat", "temperature"),
            ("SAT", "temperature"),
            ("  oa_t  ", "temperature"),
            ("web_oa_t", "temperature"),
            ("web_oa_dp", "temperature"),
            ("duct_static", "pressure"),
            ("DUCT_STATIC_SP", "pressure"),
            ("zone_flow", "flow"),
            ("chw_flow", "flow"),
            (" min_flow_sp ", "flow"),
            ("fan_cmd", "identity"),
            ("dry_bulb_f", "identity"),
        ];
        for (role, kind) in samples {
            assert_eq!(legacy_kind(role), kind, "{role}");
            let (sql, binds) = fresh(role);
            match kind {
                "temperature" => {
                    assert_eq!(sql, TEMPERATURE_SQL);
                    assert_text_list(&binds[0], CELSIUS_TOKENS);
                    assert_float(&binds[1], 9.0);
                    assert_float(&binds[2], 5.0);
                    assert_float(&binds[3], 32.0);
                    assert_eq!(binds.len(), 4);
                }
                "pressure" => {
                    assert_eq!(sql, PRESSURE_SQL);
                    assert_text_list(&binds[0], PASCAL_TOKENS);
                    assert_float(&binds[1], fdd_core::units::PA_PER_IN_WC);
                    assert_eq!(binds.len(), 2);
                }
                "flow" => {
                    assert_eq!(sql, FLOW_SQL);
                    assert_text_list(&binds[0], LPS_TOKENS);
                    assert_float(&binds[1], fdd_core::units::LPS_PER_CFM);
                    assert_eq!(binds.len(), 2);
                }
                "identity" => {
                    assert_eq!(sql, "s.val");
                    assert!(binds.is_empty());
                }
                _ => panic!("unknown kind"),
            }
            assert!(!sql.contains(role.trim()), "{role} was copied into SQL");
        }

        for role in fdd_core::TEMPERATURE_ROLES {
            assert_eq!(fresh(role).0, TEMPERATURE_SQL, "{role}");
            assert_eq!(legacy_kind(role), "temperature");
        }
        for role in fdd_core::PRESSURE_ROLES {
            assert_eq!(fresh(role).0, PRESSURE_SQL, "{role}");
            assert_eq!(legacy_kind(role), "pressure");
        }
        for role in fdd_core::FLOW_ROLES {
            assert_eq!(fresh(role).0, FLOW_SQL, "{role}");
            assert_eq!(legacy_kind(role), "flow");
        }
    }

    #[test]
    fn hostile_roles_cannot_change_sql_shape() {
        let hostile = [
            "sat'; DROP TABLE sample; --",
            "oa_t) OR true --",
            "duct_static; DELETE FROM sample",
            "zone_flow' UNION SELECT 1 --",
            "'; SELECT pg_sleep(1); --",
            "unit",
            "val",
            "s.val",
            "s.unit",
            "s.val OR true",
            "$4::float8",
            "sat; update sample set val = 0",
            "web_oa_t' OR '1'='1",
            "\n sat",
            "sat\0; DROP TABLE sample",
            "°C",
            "celsius",
            "pascal",
        ];
        let temperature_shape = shape(TEMPERATURE_SQL);
        let pressure_shape = shape(PRESSURE_SQL);
        for role in hostile {
            let legacy = legacy_kind(role);
            let (sql, binds) = fresh(role);
            assert!(
                !sql.contains("DROP")
                    && !sql.contains("DELETE")
                    && !sql.contains("UNION")
                    && !sql.contains("pg_sleep")
                    && !sql.contains("--"),
                "{role} changed SQL: {sql}"
            );
            match legacy {
                "temperature" => {
                    assert_eq!(shape(&sql), temperature_shape);
                    assert_eq!(binds.len(), 4);
                }
                "pressure" => {
                    assert_eq!(shape(&sql), pressure_shape);
                    assert_eq!(binds.len(), 2);
                }
                "identity" => {
                    assert_eq!(sql, "s.val");
                    assert!(binds.is_empty());
                }
                other => panic!("{role} legacy kind {other} is not a closed shape"),
            }
            if role.contains('\'') || role.contains(';') || role.contains('-') {
                assert_eq!(sql, "s.val");
                assert!(!sql.contains(role));
            }
        }

        let mut mixed = AdmitBuilder::after_occupied(3);
        let temperature = mixed.admitted_on_sample("sat");
        let identity = mixed.admitted_on_sample("fan_cmd");
        let pressure = mixed.admitted_on_sample("duct_static");
        let flow = mixed.admitted_on_sample("zone_flow");
        let injected = mixed.admitted_on_sample("sat'; DROP TABLE sample;--");
        assert_eq!(
            temperature,
            "CASE WHEN lower(regexp_replace(coalesce(s.unit, ''), '[^a-zA-Z0-9]', '', 'g')) = ANY($4::text[]) THEN (s.val * $5::float8 / $6::float8) + $7::float8 ELSE s.val END"
        );
        assert_eq!(identity, "s.val");
        assert_eq!(
            pressure,
            "CASE WHEN lower(regexp_replace(coalesce(s.unit, ''), '[^a-zA-Z0-9]', '', 'g')) = ANY($8::text[]) THEN s.val / $9::float8 ELSE s.val END"
        );
        assert_eq!(
            flow,
            "CASE WHEN lower(regexp_replace(coalesce(s.unit, ''), '[^a-zA-Z0-9]', '', 'g')) = ANY($10::text[]) THEN s.val / $11::float8 ELSE s.val END"
        );
        assert_eq!(injected, "s.val");
        assert!(!injected.contains("DROP"));
        assert_eq!(mixed.binds().len(), 8);
        assert_eq!(shape(&temperature), shape(&fresh("web_oa_dp").0));
        assert_eq!(shape(&pressure), shape(&fresh("duct_static_sp").0));
        assert_eq!(shape(&flow), shape(&fresh("chw_flow").0));
    }

    fn database_url() -> (String, bool) {
        for key in [
            "OPENFDD_LIFECYCLE_DATABASE_URL",
            "OPENFDD_TEST_DATABASE_URL",
        ] {
            if let Ok(value) = std::env::var(key) {
                let value = value.trim();
                if !value.is_empty() {
                    return (value.to_string(), true);
                }
            }
        }
        (
            "postgresql://openfdd:openfdd@127.0.0.1:5432/openfdd".to_string(),
            false,
        )
    }

    fn same_sample(left: Option<f64>, right: Option<f64>) -> bool {
        match (left, right) {
            (None, None) => true,
            (Some(left), Some(right)) => {
                left.to_bits() == right.to_bits()
                    || (left - right).abs() <= 1e-9 * (1.0 + left.abs().max(right.abs()))
            }
            _ => false,
        }
    }

    async fn eval_expr(
        pool: &sqlx::PgPool,
        expr: &str,
        extra: &[AdmitBind],
        value: Option<f64>,
        unit: Option<&str>,
    ) -> Option<f64> {
        let sql =
            format!("SELECT ({expr})::float8 FROM (SELECT $1::float8 AS val, $2::text AS unit) s");
        let row = apply_binds(sqlx::query(&sql).bind(value).bind(unit), extra)
            .fetch_one(pool)
            .await
            .unwrap_or_else(|err| {
                panic!("eval failed for [{expr}] value={value:?} unit={unit:?}: {err}")
            });
        row.try_get(0)
            .unwrap_or_else(|err| panic!("decode [{expr}]: {err}"))
    }

    #[tokio::test]
    async fn admitted_sql_results_match_legacy_substitution() {
        let (url, explicit) = database_url();
        let pool = match sqlx::postgres::PgPoolOptions::new()
            .max_connections(1)
            .acquire_timeout(std::time::Duration::from_secs(5))
            .connect(&url)
            .await
        {
            Ok(pool) => pool,
            Err(err) if explicit => panic!("admission database connect failed: {err}"),
            Err(err) => {
                eprintln!("skip: postgres unavailable for admission parity: {err}");
                return;
            }
        };

        let cases = [
            ("sat", Some(20.0), Some("°C")),
            ("sat", Some(20.0), Some("degC")),
            ("sat", Some(20.0), Some("celsius")),
            ("sat", Some(20.0), Some("C")),
            ("sat", Some(68.0), Some("°F")),
            ("sat", Some(68.0), Some("")),
            ("sat", Some(68.0), None),
            ("sat", Some(20.0), Some("c'; DROP TABLE sample; --")),
            ("sat", Some(20.0), Some("celsius; drop table sample")),
            ("sat", None, Some("°C")),
            ("  SAT  ", Some(0.0), Some("C")),
            ("web_oa_t", Some(100.0), Some("°C")),
            ("web_oa_dp", Some(10.0), Some("degF")),
            ("duct_static", Some(248.84), Some("Pa")),
            ("duct_static", Some(248.84), Some("pascal")),
            ("duct_static", Some(1.5), Some("in.w.c.")),
            ("duct_static", Some(100.0), Some("Pa")),
            ("duct_static_sp", Some(10.0), Some("")),
            ("zone_flow", Some(0.471947), Some("lps")),
            ("zone_flow", Some(0.471947), Some("L/s")),
            ("zone_flow", Some(100.0), Some("cfm")),
            ("chw_flow", Some(2.0), Some("lpers")),
            ("fan_cmd", Some(1.0), Some("°C")),
            ("fan_cmd", Some(20.0), Some("Pa")),
            ("dry_bulb_f", Some(20.0), Some("°C")),
            ("sat'; DROP TABLE sample; --", Some(12.5), Some("°C")),
            ("zone_flow' UNION SELECT 1 --", Some(4.0), Some("lps")),
        ];

        for (role, value, unit) in cases {
            let legacy_sql = legacy_admitted_on_sample(role);
            let mut builder = AdmitBuilder::after_occupied(2);
            let built_sql = builder.admitted_on_sample(role);
            if role.contains('\'') || role.contains(';') {
                assert_eq!(built_sql, "s.val");
                assert!(!built_sql.contains(role));
            }
            let legacy = eval_expr(&pool, &legacy_sql, &[], value, unit).await;
            let built = eval_expr(&pool, &built_sql, builder.binds(), value, unit).await;
            assert!(
                same_sample(legacy, built),
                "role={role} value={value:?} unit={unit:?} legacy={legacy:?} built={built:?}\nlegacy SQL: {legacy_sql}\nbuilt SQL: {built_sql}"
            );
            if let Some(value) = value {
                let rust = fdd_core::admit_value_to_pack_v1(role, value, unit.unwrap_or(""));
                assert!(
                    same_sample(Some(rust), built),
                    "role={role} value={value} unit={unit:?} rust={rust} built={built:?}"
                );
            }
        }
    }
}
