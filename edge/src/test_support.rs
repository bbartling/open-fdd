//! Shared test helpers (also used to serialize env-mutating unit tests).

use std::fs;
use std::path::{Path, PathBuf};

pub fn workspace_env_lock() -> std::sync::MutexGuard<'static, ()> {
    static LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
    LOCK.lock().unwrap_or_else(|e| e.into_inner())
}

pub fn with_temp_workspace<F: FnOnce(&Path)>(f: F) {
    let _guard = workspace_env_lock();
    let prev = std::env::var("OPENFDD_WORKSPACE").ok();
    let dir = std::env::temp_dir().join(format!(
        "openfdd-test-ws-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    ));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    std::env::set_var("OPENFDD_WORKSPACE", &dir);
    f(&dir);
    if let Some(p) = prev {
        std::env::set_var("OPENFDD_WORKSPACE", p);
    } else {
        std::env::remove_var("OPENFDD_WORKSPACE");
    }
    let _ = fs::remove_dir_all(&dir);
}

pub fn temp_workspace_path() -> PathBuf {
    std::env::temp_dir().join(format!(
        "openfdd-test-ws-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    ))
}
