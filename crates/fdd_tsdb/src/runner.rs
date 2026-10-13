//! SQL rule runner (BPS sql_runner pattern, Rust).

use std::path::{Path, PathBuf};

use anyhow::{anyhow, Context, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::Row;

use crate::client::Tsdb;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuleRunRequest {
    pub site_id: String,
    pub equipment_id: String,
    pub rule_id: String,
    pub window_start: DateTime<Utc>,
    pub window_end: DateTime<Utc>,
    pub poll_seconds: i32,
    pub confirm_min: f64,
    pub sql_body: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuleRunResult {
    pub rule_id: String,
    pub equipment_id: String,
    pub status: String,
    pub fault_hours: Option<f64>,
    pub fault_seconds: Option<i32>,
    pub sample_count: Option<i32>,
    pub detail: serde_json::Value,
}

pub fn load_rule_sql(sql_root: &Path, sql_file: &str) -> Result<String> {
    let candidates = [
        sql_root.join("postgres/rules").join(sql_file),
        sql_root.join("warehouse/rules").join(sql_file),
        sql_root.join("rules").join(sql_file),
        sql_root.join(sql_file),
    ];
    for path in candidates {
        if path.is_file() {
            return std::fs::read_to_string(&path)
                .with_context(|| format!("read rule sql {}", path.display()));
        }
    }
    Err(anyhow!("rule sql not found: {sql_file} under {}", sql_root.display()))
}

pub fn render_placeholders(sql: &str, req: &RuleRunRequest) -> String {
    sql.replace("{{SITE_ID}}", &req.site_id)
        .replace("{{EQUIPMENT_ID}}", &req.equipment_id)
        .replace("{{POLL_SECONDS}}", &req.poll_seconds.to_string())
        .replace("{{CONFIRM_MIN}}", &req.confirm_min.to_string())
        .replace("{{WINDOW_START}}", &req.window_start.to_rfc3339())
        .replace("{{WINDOW_END}}", &req.window_end.to_rfc3339())
}

impl Tsdb {
    pub async fn insert_fdd_run(&self, req: &RuleRunRequest, result: &RuleRunResult) -> Result<()> {
        sqlx::query(
            r#"
            INSERT INTO fdd_run(
              site_id, equipment_id, rule_id, window_start, window_end,
              poll_seconds, confirm_min, status, fault_seconds, fault_hours,
              sample_count, detail
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            "#,
        )
        .bind(&req.site_id)
        .bind(&req.equipment_id)
        .bind(&req.rule_id)
        .bind(req.window_start)
        .bind(req.window_end)
        .bind(req.poll_seconds)
        .bind(req.confirm_min)
        .bind(&result.status)
        .bind(result.fault_seconds)
        .bind(result.fault_hours)
        .bind(result.sample_count)
        .bind(&result.detail)
        .execute(self.pool())
        .await?;
        Ok(())
    }

    /// Execute a warehouse SQL template that returns fault_hours (aggregate).
    pub async fn run_rule_sql(&self, req: &RuleRunRequest) -> Result<RuleRunResult> {
        let sql = render_placeholders(&req.sql_body, req);
        let rows = sqlx::query(&sql).fetch_all(self.pool()).await;
        match rows {
            Ok(rows) => {
                let mut fault_hours = None;
                let mut sample_count = None;
                for row in &rows {
                    if let Ok(v) = row.try_get::<f64, _>("fault_hours") {
                        fault_hours = Some(fault_hours.unwrap_or(0.0) + v);
                    }
                    if let Ok(v) = row.try_get::<i32, _>("sample_count") {
                        sample_count = Some(sample_count.unwrap_or(0) + v);
                    }
                }
                let result = RuleRunResult {
                    rule_id: req.rule_id.clone(),
                    equipment_id: req.equipment_id.clone(),
                    status: "ok".into(),
                    fault_hours,
                    fault_seconds: fault_hours.map(|h| (h * 3600.0) as i32),
                    sample_count,
                    detail: serde_json::json!({ "row_count": rows.len() }),
                };
                self.insert_fdd_run(req, &result).await?;
                Ok(result)
            }
            Err(e) => {
                let result = RuleRunResult {
                    rule_id: req.rule_id.clone(),
                    equipment_id: req.equipment_id.clone(),
                    status: "error".into(),
                    fault_hours: None,
                    fault_seconds: None,
                    sample_count: None,
                    detail: serde_json::json!({ "error": e.to_string() }),
                };
                let _ = self.insert_fdd_run(req, &result).await;
                Err(e.into())
            }
        }
    }

    pub async fn sql_file_for_rule(&self, rule_id: &str) -> Result<Option<String>> {
        let row = sqlx::query("SELECT sql_file FROM fdd_rule_registry WHERE rule_id = $1")
            .bind(rule_id)
            .fetch_optional(self.pool())
            .await?;
        Ok(row.map(|r| r.get::<String, _>("sql_file")))
    }
}

pub fn default_sql_root() -> PathBuf {
    std::env::var_os("OPENFDD_SQL_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("sql/fdd"))
}
