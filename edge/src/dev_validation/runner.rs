//! Orchestrate dev validation harness run.

use super::api_health::{self, EndpointResult};
use super::auth_client;
use super::browser::{self, BrowserSmokeSummary};
use super::fdd_analytics::{self, FddAnalytics};
use super::report_output;
use super::sources::{self, SourceValidationSummary};
use crate::validation::dev_profile::DevValidationProfile;
use chrono::Utc;
use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

#[derive(Clone, Debug)]
pub struct HarnessOptions {
    pub base_url: String,
    pub profile_path: PathBuf,
    pub auth_env: PathBuf,
    pub duration_minutes: u64,
    pub bacnet_interval_seconds: u64,
    pub driver_interval_seconds: u64,
    pub output_dir: PathBuf,
    pub dry_run: bool,
    pub skip_browser: bool,
    pub skip_haystack_if_not_configured: bool,
    pub skip_modbus_if_not_configured: bool,
    pub generate_report: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HarnessResult {
    pub pass: bool,
    pub run_id: String,
    pub artifact_dir: String,
    pub pdf_path: Option<String>,
    pub report_id: Option<String>,
    pub api_health: Vec<EndpointResult>,
    pub browser_smoke: BrowserSmokeSummary,
    pub source_validation: SourceValidationSummary,
    pub fdd_analytics: FddAnalytics,
}

pub fn run(opts: HarnessOptions) -> Result<HarnessResult, String> {
    let profile = DevValidationProfile::load(&opts.profile_path)?;
    std::env::set_var("OPENFDD_VALIDATION_PROFILE", &opts.profile_path);
    std::env::set_var("OPENFDD_SMOKE_PROFILE_PATH", &opts.profile_path);

    let run_ts = Utc::now().format("%Y%m%dT%H%M%SZ").to_string();
    let artifact_dir = if opts.output_dir.as_os_str().is_empty() {
        find_repo_root()
            .join("workspace/logs")
            .join(format!("dev_5007_validation_{run_ts}"))
    } else {
        opts.output_dir.clone()
    };
    std::fs::create_dir_all(&artifact_dir).map_err(|e| e.to_string())?;
    let run_id = format!("dev-validation-{run_ts}");

    let client = Client::builder()
        .timeout(Duration::from_secs(60))
        .build()
        .map_err(|e| e.to_string())?;

    eprintln!("==> login");
    let token = auth_client::login(&opts.base_url, &opts.auth_env, "integrator")?;

    eprintln!("==> API health");
    let api_health = api_health::check_endpoints(
        &client,
        &opts.base_url,
        &token,
        &api_health::core_endpoints(),
    );
    let api_ok = api_health::all_passed(&api_health);

    let browser_smoke = if opts.skip_browser {
        BrowserSmokeSummary {
            pass: true,
            notes: "skipped via --skip-browser".into(),
            ..Default::default()
        }
    } else if opts.dry_run {
        BrowserSmokeSummary {
            pass: true,
            notes: "skipped in --dry-run".into(),
            ..Default::default()
        }
    } else {
        eprintln!("==> browser smoke");
        browser::run_ui_smoke(&find_repo_root(), &opts.base_url, &artifact_dir)?
    };

    let live_artifact = artifact_dir.join("live_fdd_validation");
    let validation_summary = if opts.dry_run {
        eprintln!("==> dry-run: skipping live 1-hour validation");
        json!({
            "bacnet_poll_ok": 1,
            "modbus_ok": if profile.modbus_configured() && !opts.skip_modbus_if_not_configured { 1 } else { 0 },
            "haystack_ok": if profile.haystack_configured() && !opts.skip_haystack_if_not_configured { 1 } else { 0 },
            "csv_import_ok": if profile.smoke.csv_enabled { 1 } else { 0 },
            "json_api_ok": if profile.smoke.json_api_enabled { 1 } else { 0 },
        })
    } else {
        eprintln!("==> live validation ({} minutes)", opts.duration_minutes);
        run_live_validation_script(&opts, &profile, &live_artifact)?;
        load_validation_artifact_summary(&live_artifact)
    };

    let mut source_validation =
        sources::source_summary_from_artifact(&profile, &validation_summary);
    if opts.skip_modbus_if_not_configured && !profile.modbus_configured() {
        source_validation.modbus.pass = true;
        source_validation.modbus.status = "not_configured".into();
    }
    if opts.skip_haystack_if_not_configured && !profile.haystack_configured() {
        source_validation.haystack.pass = true;
        source_validation.haystack.status = "not_configured".into();
    }

    let summary_path = live_artifact.join("summary.jsonl");
    let fdd_analytics = if summary_path.exists() {
        fdd_analytics::analyze_summary_jsonl(
            &summary_path,
            profile.smoke.confirmation_minutes,
            opts.duration_minutes,
        )
    } else if opts.dry_run {
        FddAnalytics {
            pass: true,
            confirmation_minutes: profile.smoke.confirmation_minutes,
            raw_fault_before_confirmed: true,
            confirmed_after_delay: true,
            notes: "dry-run stub analytics".into(),
            ..Default::default()
        }
    } else {
        FddAnalytics {
            confirmation_minutes: profile.smoke.confirmation_minutes,
            notes: "summary.jsonl not found".into(),
            ..Default::default()
        }
    };

    let sources_ok = source_validation.bacnet.pass
        && source_validation.modbus.pass
        && source_validation.json_api.pass
        && source_validation.haystack.pass
        && source_validation.csv.pass;
    let pass = api_ok && browser_smoke.pass && sources_ok && fdd_analytics.pass;

    let harness_doc = fdd_analytics::report_data_model(
        &profile.smoke.profile_id,
        &api_health,
        &browser_smoke,
        &source_validation,
        &fdd_analytics,
        pass,
    );

    let md = report_output::build_markdown(
        &profile.report_title,
        pass,
        &api_health,
        &browser_smoke,
        &source_validation,
        &fdd_analytics,
        None,
    );
    report_output::write_artifacts(&artifact_dir, pass, &harness_doc, &md)?;

    let mut pdf_path = None;
    let mut report_id = None;
    if opts.generate_report {
        eprintln!("==> generate PDF report");
        match report_output::create_report_via_api(
            &client,
            &opts.base_url,
            &token,
            &run_id,
            live_artifact.to_str().unwrap_or(""),
            pass,
            &harness_doc,
        ) {
            Ok(created) => {
                let rid = created
                    .get("report_id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                pdf_path = created
                    .get("pdf_path")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());
                if !rid.is_empty() {
                    let _ = report_output::verify_report_lifecycle(
                        &client,
                        &opts.base_url,
                        &token,
                        &rid,
                    );
                    report_id = Some(rid);
                }
            }
            Err(err) => eprintln!("WARN: report API: {err}"),
        }
    }

    Ok(HarnessResult {
        pass,
        run_id,
        artifact_dir: artifact_dir.display().to_string(),
        pdf_path,
        report_id,
        api_health,
        browser_smoke,
        source_validation,
        fdd_analytics,
    })
}

fn run_live_validation_script(
    opts: &HarnessOptions,
    profile: &DevValidationProfile,
    artifact_dir: &Path,
) -> Result<(), String> {
    let root = find_repo_root();
    let script = root.join("scripts/smoke_live_fdd_validation.sh");
    if !script.exists() {
        return Err("smoke_live_fdd_validation.sh not found".into());
    }
    std::fs::create_dir_all(artifact_dir).map_err(|e| e.to_string())?;
    let hours = format!("{:.4}", opts.duration_minutes as f64 / 60.0);
    let status = Command::new("bash")
        .arg(&script)
        .current_dir(&root)
        .env("OPENFDD_API_BASE", &opts.base_url)
        .env("OPENFDD_VALIDATION_PROFILE", &opts.profile_path)
        .env("OPENFDD_SMOKE_PROFILE_PATH", &opts.profile_path)
        .env("OPENFDD_VALIDATION_ONE_HOUR", "1")
        .env("OPENFDD_SMOKE_ARTIFACT_DIR", artifact_dir)
        .env("OPENFDD_SMOKE_DURATION_HOURS", &hours)
        .env(
            "OPENFDD_SMOKE_INTERVAL_SECONDS",
            opts.bacnet_interval_seconds.to_string(),
        )
        .env(
            "OPENFDD_SMOKE_MODBUS_INTERVAL_SECONDS",
            opts.driver_interval_seconds.to_string(),
        )
        .env(
            "OPENFDD_SMOKE_HAYSTACK_INTERVAL_SECONDS",
            opts.driver_interval_seconds.to_string(),
        )
        .env(
            "OPENFDD_SMOKE_CSV_INTERVAL_SECONDS",
            opts.driver_interval_seconds.to_string(),
        )
        .env("OPENFDD_SMOKE_LIVE_FDD", "1")
        .env(
            "OPENFDD_SMOKE_CSV_APPEND",
            if profile.smoke.csv_enabled { "1" } else { "0" },
        )
        .env(
            "OPENFDD_SMOKE_VALIDATE_MODBUS",
            if profile.modbus_configured() {
                "1"
            } else {
                "0"
            },
        )
        .env(
            "OPENFDD_SMOKE_VALIDATE_JSON_API",
            if profile.smoke.json_api_enabled {
                "1"
            } else {
                "0"
            },
        )
        .env("OPENFDD_SMOKE_NO_DEMO_PASS", "1")
        .env(
            "OPENFDD_SMOKE_REQUIRE_CONFIRMED_FAULT",
            if opts.duration_minutes >= profile.smoke.confirmation_minutes as u64 {
                "1"
            } else {
                "0"
            },
        )
        .status()
        .map_err(|e| e.to_string())?;
    if !status.success() {
        return Err(format!("live validation exited {}", status));
    }
    Ok(())
}

fn load_validation_artifact_summary(artifact_dir: &Path) -> Value {
    let path = artifact_dir.join("summary.jsonl");
    let text = std::fs::read_to_string(&path).unwrap_or_default();
    let mut bacnet_poll_ok = 0_u64;
    let mut modbus_ok = 0_u64;
    let mut haystack_ok = 0_u64;
    let mut csv_import_ok = 0_u64;
    let mut json_api_ok = 0_u64;
    for line in text.lines() {
        if line.trim().is_empty() {
            continue;
        }
        let Ok(row) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        if row.get("bacnet_poll_ok").and_then(|v| v.as_bool()) == Some(true) {
            bacnet_poll_ok += 1;
        }
        if row.get("modbus_ok").and_then(|v| v.as_bool()) == Some(true) {
            modbus_ok += 1;
        }
        if row.get("haystack_ok").and_then(|v| v.as_bool()) == Some(true) {
            haystack_ok += 1;
        }
        if row.get("csv_import_ok").and_then(|v| v.as_bool()) == Some(true) {
            csv_import_ok += 1;
        }
        if row.get("json_api_ok").and_then(|v| v.as_bool()) == Some(true) {
            json_api_ok += 1;
        }
    }
    json!({
        "bacnet_poll_ok": bacnet_poll_ok,
        "modbus_ok": modbus_ok,
        "haystack_ok": haystack_ok,
        "csv_import_ok": csv_import_ok,
        "json_api_ok": json_api_ok,
    })
}

pub fn find_repo_root() -> PathBuf {
    if let Ok(root) = std::env::var("OPENFDD_REPO_ROOT") {
        return PathBuf::from(root);
    }
    let mut dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    for _ in 0..8 {
        if dir
            .join("scripts/openfdd_dev_5007_report_validation.sh")
            .exists()
            || dir.join("Cargo.toml").exists() && dir.join("edge/Cargo.toml").exists()
        {
            return dir;
        }
        if !dir.pop() {
            break;
        }
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn harness_options_defaults_are_generic() {
        let opts = HarnessOptions {
            base_url: "http://127.0.0.1:8080".into(),
            profile_path: PathBuf::from("workspace/smoke-profiles/local/example.local.toml"),
            auth_env: PathBuf::from("workspace/auth.env.local"),
            duration_minutes: 60,
            bacnet_interval_seconds: 60,
            driver_interval_seconds: 300,
            output_dir: PathBuf::new(),
            dry_run: true,
            skip_browser: true,
            skip_haystack_if_not_configured: true,
            skip_modbus_if_not_configured: true,
            generate_report: false,
        };
        assert!(!opts.base_url.contains("192.168"));
    }
}
