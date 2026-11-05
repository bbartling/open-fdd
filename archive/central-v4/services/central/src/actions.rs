//! Durable Actions run log — JSONL under `$OPENFDD_WORKSPACE/data/actions/log.jsonl`.

use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::sync::Mutex;

use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use uuid::Uuid;

static LOG_LOCK: Mutex<()> = Mutex::new(());

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActionEntry {
    pub id: String,
    pub kind: String,
    pub label: String,
    pub started_at: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub finished_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub duration_ms: Option<u64>,
    pub status: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub detail: Option<Value>,
    /// Tenant that owned the site when the row was written, when known.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tenant_id: Option<String>,
    /// Site the row belongs to. Older rows may carry this only inside `detail`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub building_id: Option<String>,
    /// Server request id for the HTTP call that started the row.
    ///
    /// The same value is `request_id` on the typed audit record and
    /// `x-openfdd-server-request-id`. Rows started outside a request omit it.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub request_id: Option<String>,
}

/// Identity copied out of a row for an audit event. Labels and detail stay in the log.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ActionRef {
    pub id: String,
    pub tenant_id: Option<String>,
    pub building_id: Option<String>,
}

pub(crate) enum RemoveOne {
    Removed {
        action: ActionRef,
        in_scope_remaining: usize,
    },
    OutOfScope(ActionRef),
    Missing,
}

fn workspace_root() -> PathBuf {
    if let Ok(ws) = std::env::var("OPENFDD_WORKSPACE") {
        return PathBuf::from(ws);
    }
    if let Ok(ws) = std::env::var("OPENFDD_WORKSPACE_DIR") {
        return PathBuf::from(ws);
    }
    PathBuf::from("workspace")
}

fn log_path() -> PathBuf {
    workspace_root()
        .join("data")
        .join("actions")
        .join("log.jsonl")
}

fn utc_now() -> String {
    Utc::now().format("%Y-%m-%dT%H:%M:%S%.3fZ").to_string()
}

fn ensure_parent(path: &std::path::Path) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    Ok(())
}

fn read_all_unlocked() -> Vec<ActionEntry> {
    let path = log_path();
    if !path.is_file() {
        return Vec::new();
    }
    let Ok(file) = File::open(&path) else {
        return Vec::new();
    };
    let reader = BufReader::new(file);
    let mut out = Vec::new();
    for line in reader.lines().map_while(Result::ok) {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        if let Ok(entry) = serde_json::from_str::<ActionEntry>(trimmed) {
            out.push(entry);
        }
    }
    out
}

fn rewrite_all_unlocked(entries: &[ActionEntry]) -> Result<(), String> {
    let path = log_path();
    ensure_parent(&path).map_err(|e| e.to_string())?;
    let tmp = path.with_extension("jsonl.tmp");
    {
        let mut f = File::create(&tmp).map_err(|e| e.to_string())?;
        for e in entries {
            let line = serde_json::to_string(e).map_err(|err| err.to_string())?;
            writeln!(f, "{line}").map_err(|err| err.to_string())?;
        }
        f.flush().map_err(|e| e.to_string())?;
    }
    fs::rename(&tmp, &path).map_err(|e| e.to_string())?;
    Ok(())
}

const JSONL_CAP: usize = 50;
const DEFAULT_LIST_LIMIT: usize = 10;
const MAX_LIST_LIMIT: usize = 500;
/// Orphaned `running` rows after OOM/crash — fail them so single-flight can recover.
/// Soft-OPEN large-site hangs were observed >20m; reclaim at 20m so list/start recover without
/// waiting for a second POST (Wave U interrupt).
const STALE_RUNNING_SECS: i64 = 20 * 60;

fn is_heavy_fdd_kind(kind: &str) -> bool {
    matches!(kind, "fdd_run_all" | "fdd_run_rule") || kind.starts_with("fdd_")
}

fn reclaim_stale_running_unlocked(now: chrono::DateTime<Utc>) -> Result<(), String> {
    let mut entries = read_all_unlocked();
    let mut changed = false;
    for entry in &mut entries {
        if entry.status != "running" {
            continue;
        }
        let Some(started) = chrono::DateTime::parse_from_rfc3339(&entry.started_at)
            .ok()
            .map(|t| t.with_timezone(&Utc))
        else {
            continue;
        };
        if (now - started).num_seconds() < STALE_RUNNING_SECS {
            continue;
        }
        entry.status = "fail".into();
        entry.finished_at = Some(utc_now());
        entry.duration_ms = Some(((now - started).num_milliseconds().max(0)) as u64);
        match &mut entry.detail {
            Some(Value::Object(base)) => {
                base.insert("error".into(), json!("stale running action reclaimed"));
                base.insert("reclaimed".into(), json!(true));
            }
            slot => {
                *slot = Some(json!({
                    "error": "stale running action reclaimed",
                    "reclaimed": true,
                }));
            }
        }
        changed = true;
    }
    if changed {
        rewrite_all_unlocked(&entries)?;
    }
    Ok(())
}

fn prune_unlocked(cap: usize) -> Result<(), String> {
    let mut entries = read_all_unlocked();
    if entries.len() <= cap {
        return Ok(());
    }
    let drop_n = entries.len() - cap;
    entries.drain(0..drop_n);
    rewrite_all_unlocked(&entries)
}

fn append_unlocked(entry: &ActionEntry) -> Result<(), String> {
    let path = log_path();
    ensure_parent(&path).map_err(|e| e.to_string())?;
    let mut f = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .map_err(|e| e.to_string())?;
    let line = serde_json::to_string(entry).map_err(|e| e.to_string())?;
    writeln!(f, "{line}").map_err(|e| e.to_string())?;
    f.flush().map_err(|e| e.to_string())?;
    prune_unlocked(JSONL_CAP)?;
    Ok(())
}

/// Start a new action (`status=running`). Returns the entry id.
///
/// Heavy FDD kinds (`fdd_run_all` / `fdd_run_rule` / `fdd_*`) are single-flight:
/// a second start fails with a busy error so Railway low-RAM hubs do not OOM
/// from overlapping DataFusion runs.
pub fn start_action(kind: &str, label: &str, detail: Option<Value>) -> Result<String, String> {
    let id = format!("act-{}", Uuid::new_v4());
    let mut entry = ActionEntry {
        id: id.clone(),
        kind: kind.to_string(),
        label: label.to_string(),
        started_at: utc_now(),
        finished_at: None,
        duration_ms: None,
        status: "running".into(),
        detail,
        tenant_id: None,
        building_id: None,
        request_id: crate::audit::current_server_request_id().filter(|id| !id.is_empty()),
    };
    crate::actions_scope::bind_entry_scope(&mut entry);
    let _guard = LOG_LOCK.lock().map_err(|e| e.to_string())?;
    reclaim_stale_running_unlocked(Utc::now())?;
    if is_heavy_fdd_kind(kind) {
        if let Some(other) = read_all_unlocked()
            .into_iter()
            .find(|e| e.status == "running" && is_heavy_fdd_kind(&e.kind))
        {
            return Err(format!(
                "busy: {} still running (id={}, started_at={}) — wait for it to finish or clear Actions",
                other.kind, other.id, other.started_at
            ));
        }
    }
    append_unlocked(&entry)?;
    Ok(id)
}

/// Finish an action with `ok`, `partial`, or `fail` and optional detail merge.
pub fn finish_action(id: &str, status: &str, detail: Option<Value>) -> Result<ActionEntry, String> {
    let status = match status {
        "ok" | "partial" | "fail" => status,
        other => {
            return Err(format!(
                "invalid finish status '{other}' (expected ok|partial|fail)"
            ));
        }
    };
    let finished_at = utc_now();
    let _guard = LOG_LOCK.lock().map_err(|e| e.to_string())?;
    let mut entries = read_all_unlocked();
    let Some(pos) = entries.iter().position(|e| e.id == id) else {
        return Err(format!("action not found: {id}"));
    };
    let entry = &mut entries[pos];
    let started = chrono::DateTime::parse_from_rfc3339(&entry.started_at)
        .ok()
        .map(|t| t.with_timezone(&Utc));
    let finished = chrono::DateTime::parse_from_rfc3339(&finished_at)
        .ok()
        .map(|t| t.with_timezone(&Utc));
    let duration_ms = match (started, finished) {
        (Some(s), Some(f)) => Some((f - s).num_milliseconds().max(0) as u64),
        _ => None,
    };
    entry.finished_at = Some(finished_at);
    entry.duration_ms = duration_ms;
    entry.status = status.to_string();
    if let Some(d) = detail {
        match (&mut entry.detail, d) {
            (Some(Value::Object(base)), Value::Object(extra)) => {
                for (k, v) in extra {
                    base.insert(k, v);
                }
            }
            (slot, other) => {
                *slot = Some(other);
            }
        }
    }
    crate::actions_scope::bind_entry_scope(entry);
    let out = entry.clone();
    rewrite_all_unlocked(&entries)?;
    Ok(out)
}

pub(crate) fn clamp_list_limit(limit: usize) -> usize {
    if limit == 0 {
        DEFAULT_LIST_LIMIT
    } else {
        limit.min(MAX_LIST_LIMIT)
    }
}

/// Newest-first rows that `visible` accepts, after the usual stale-run reclaim.
///
/// The predicate must not call back into this log. The lock is held for the read.
pub(crate) fn list_visible(
    limit: usize,
    visible: impl Fn(&ActionEntry) -> bool,
) -> Result<Vec<ActionEntry>, String> {
    let limit = clamp_list_limit(limit);
    let _guard = LOG_LOCK.lock().map_err(|e| e.to_string())?;
    // Reclaim is best-effort: a rewrite error must not hide rows already on disk.
    let _ = reclaim_stale_running_unlocked(Utc::now());
    let mut entries = read_all_unlocked();
    entries.reverse();
    entries.retain(visible);
    entries.truncate(limit);
    Ok(entries)
}

/// Delete `id` when `allow` is true. `stamp` copies the audit identity while the row is still stored.
///
/// Both callbacks run under the log lock and must not re-enter it.
pub(crate) fn remove_one(
    id: &str,
    allow: impl Fn(&ActionEntry) -> bool,
    stamp: impl Fn(&ActionEntry) -> ActionRef,
) -> Result<RemoveOne, String> {
    let _guard = LOG_LOCK.lock().map_err(|e| e.to_string())?;
    let mut entries = read_all_unlocked();
    let Some(pos) = entries.iter().position(|entry| entry.id == id) else {
        return Ok(RemoveOne::Missing);
    };
    let action = stamp(&entries[pos]);
    if !allow(&entries[pos]) {
        return Ok(RemoveOne::OutOfScope(action));
    }
    entries.remove(pos);
    let in_scope_remaining = entries.iter().filter(|entry| allow(entry)).count();
    rewrite_all_unlocked(&entries)?;
    Ok(RemoveOne::Removed {
        action,
        in_scope_remaining,
    })
}

/// Remove every row `remove` accepts. An empty match leaves the file untouched.
pub(crate) fn remove_matching(
    remove: impl Fn(&ActionEntry) -> bool,
    stamp: impl Fn(&ActionEntry) -> ActionRef,
) -> Result<Vec<ActionRef>, String> {
    let _guard = LOG_LOCK.lock().map_err(|e| e.to_string())?;
    let entries = read_all_unlocked();
    let mut kept = Vec::with_capacity(entries.len());
    let mut removed = Vec::new();
    for entry in entries {
        if remove(&entry) {
            removed.push(stamp(&entry));
        } else {
            kept.push(entry);
        }
    }
    if !removed.is_empty() {
        rewrite_all_unlocked(&kept)?;
    }
    Ok(removed)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    static TEST_LOCK: Mutex<()> = Mutex::new(());

    fn stamp(entry: &ActionEntry) -> ActionRef {
        ActionRef {
            id: entry.id.clone(),
            tenant_id: entry.tenant_id.clone(),
            building_id: entry.building_id.clone(),
        }
    }

    fn listed(limit: usize) -> Vec<ActionEntry> {
        list_visible(limit, |_| true).expect("list")
    }

    #[test]
    fn start_finish_list_roundtrip() {
        let _env = crate::test_env_lock::lock_env();
        let _t = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let dir = std::env::temp_dir().join(format!("openfdd-actions-{}", Uuid::new_v4()));
        let _ = fs::create_dir_all(&dir);
        let _ws = crate::test_env_lock::WorkspaceEnv::set(&dir);

        let id =
            start_action("fdd_run_all", "Run all", Some(json!({"building": "B1"}))).expect("start");
        let rows = listed(10);
        assert_eq!(rows[0].id, id);
        assert_eq!(rows[0].status, "running");

        let done = finish_action(&id, "ok", Some(json!({"rules_ok": 3}))).expect("finish");
        assert_eq!(done.status, "ok");
        assert!(done.duration_ms.is_some());
        assert_eq!(done.detail.as_ref().unwrap()["building"], "B1");
        assert_eq!(done.detail.as_ref().unwrap()["rules_ok"], 3);

        let rows = listed(10);
        assert_eq!(rows[0].status, "ok");

        remove_one(&id, |_| true, stamp).expect("delete one");
        assert!(listed(10).is_empty());

        let id2 = start_action("fdd_run_all", "Run all 2", None).expect("start2");
        assert!(!id2.is_empty());
        remove_matching(|_| true, stamp).expect("clear");
        assert!(listed(10).is_empty());

        for i in 0..55 {
            start_action("prune", &format!("n{i}"), None).expect("prune start");
        }
        let all = read_all_unlocked();
        assert!(all.len() <= JSONL_CAP, "jsonl cap {}", all.len());

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn heavy_fdd_is_single_flight() {
        let _env = crate::test_env_lock::lock_env();
        let _t = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let dir = std::env::temp_dir().join(format!("openfdd-actions-sf-{}", Uuid::new_v4()));
        let _ = fs::create_dir_all(&dir);
        let _ws = crate::test_env_lock::WorkspaceEnv::set(&dir);

        let id = start_action("fdd_run_all", "Run all", None).expect("first");
        let err = start_action("fdd_run_all", "Run all again", None).expect_err("busy");
        assert!(err.starts_with("busy:"), "{err}");
        let err2 = start_action("fdd_run_rule", "One rule", None).expect_err("busy rule");
        assert!(err2.starts_with("busy:"), "{err2}");
        finish_action(&id, "ok", None).expect("finish");
        let partial = start_action("fdd_run_rule", "One rule after", None).expect("after finish");
        let finished = finish_action(
            &partial,
            "partial",
            Some(json!({"run_status": "partial", "rules_failed": 1, "rules_skipped": 2})),
        )
        .expect("partial finish");
        assert_eq!(finished.status, "partial");
        assert_eq!(
            finished
                .detail
                .as_ref()
                .and_then(|d| d.get("rules_skipped")),
            Some(&json!(2))
        );

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn stale_running_heavy_fdd_is_reclaimed() {
        let _env = crate::test_env_lock::lock_env();
        let _t = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let dir = std::env::temp_dir().join(format!("openfdd-actions-stale-{}", Uuid::new_v4()));
        let _ = fs::create_dir_all(&dir);
        let _ws = crate::test_env_lock::WorkspaceEnv::set(&dir);

        let id = start_action("fdd_run_all", "Orphan", None).expect("start");
        // Backdate the running row beyond STALE_RUNNING_SECS.
        {
            let _guard = LOG_LOCK.lock().unwrap();
            let mut entries = read_all_unlocked();
            let entry = entries.iter_mut().find(|e| e.id == id).expect("row");
            entry.started_at = (Utc::now() - chrono::Duration::seconds(STALE_RUNNING_SECS + 60))
                .format("%Y-%m-%dT%H:%M:%S%.3fZ")
                .to_string();
            rewrite_all_unlocked(&entries).expect("rewrite");
        }
        // Next heavy start must reclaim and succeed (not busy).
        let id2 = start_action("fdd_run_all", "After reclaim", None).expect("reclaim start");
        assert_ne!(id2, id);
        let orphan = listed(10)
            .into_iter()
            .find(|row| row.id == id)
            .expect("orphan listed");
        assert_eq!(orphan.status, "fail");
        assert_eq!(orphan.detail.as_ref().expect("detail")["reclaimed"], true);

        let _ = fs::remove_dir_all(&dir);
    }
}
