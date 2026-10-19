//! Background BACnet poll engine (mirrors `app/poll.py`).

use std::collections::{HashMap, VecDeque};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use std::sync::Arc;

use serde_json::{json, Value};
use tokio::sync::Mutex;
use tracing::info;

use crate::config::Settings;
use crate::services::bacnet_client::BacnetClientService;

pub struct PollEngine {
    settings: Settings,
    client: Arc<BacnetClientService>,
    task: Mutex<Option<tokio::task::JoinHandle<()>>>,
    stop: AtomicBool,
    samples: Mutex<VecDeque<Value>>,
    last: Mutex<HashMap<String, Value>>,
    cycles: Mutex<u64>,
    errors: Mutex<u64>,
    last_cycle_ts: Mutex<Option<f64>>,
    last_cycle_duration: Mutex<Option<f64>>,
    last_error: Mutex<Option<String>>,
}

impl PollEngine {
    pub fn new(settings: Settings, client: Arc<BacnetClientService>) -> Self {
        Self {
            settings,
            client,
            task: Mutex::new(None),
            stop: AtomicBool::new(false),
            samples: Mutex::new(VecDeque::new()),
            last: Mutex::new(HashMap::new()),
            cycles: Mutex::new(0),
            errors: Mutex::new(0),
            last_cycle_ts: Mutex::new(None),
            last_cycle_duration: Mutex::new(None),
            last_error: Mutex::new(None),
        }
    }

    pub async fn start(self: &std::sync::Arc<Self>) {
        if !self.settings.poll.enabled {
            info!("poll engine disabled (poll.enabled=false)");
            return;
        }
        let mut guard = self.task.lock().await;
        if guard.is_some() {
            return;
        }
        self.stop.store(false, Ordering::SeqCst);
        let this = std::sync::Arc::clone(self);
        *guard = Some(tokio::spawn(async move {
            this.run_loop().await;
        }));
        info!(
            "poll engine started (interval={}s)",
            self.settings.poll.interval_secs
        );
    }

    pub async fn stop(&self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(handle) = self.task.lock().await.take() {
            handle.abort();
            let _ = handle.await;
        }
    }

    async fn run_loop(self: std::sync::Arc<Self>) {
        tokio::time::sleep(std::time::Duration::from_secs_f64(
            self.settings.poll.startup_delay_secs,
        ))
        .await;

        while !self.stop.load(Ordering::SeqCst) {
            if let Err(e) = self.poll_once().await {
                *self.errors.lock().await += 1;
                *self.last_error.lock().await = Some(e);
            }
            let interval = self.settings.poll.interval_secs;
            let mut elapsed = 0.0f64;
            while elapsed < interval && !self.stop.load(Ordering::SeqCst) {
                tokio::time::sleep(std::time::Duration::from_millis(200)).await;
                elapsed += 0.2;
            }
        }
    }

    pub async fn poll_once(&self) -> Result<Value, String> {
        let started = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64();
        let rows = self.client.poll_points().await?;
        let duration = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64()
            - started;

        *self.cycles.lock().await += 1;
        *self.last_cycle_ts.lock().await = Some(started);
        *self.last_cycle_duration.lock().await = Some(duration);

        let errored = {
            let mut samples = self.samples.lock().await;
            let mut last = self.last.lock().await;
            ingest_poll_rows(
                &mut samples,
                &mut last,
                &rows,
                self.settings.poll.max_samples,
            )
        };

        Ok(json!({
            "points_polled": rows.len(),
            "points_errored": errored,
            "duration_secs": (duration * 1000.0).round() / 1000.0,
            "cycle": *self.cycles.lock().await,
        }))
    }

    pub async fn status(&self) -> Value {
        let last_values: Vec<_> = self.last.lock().await.values().cloned().collect();
        let healthy = last_values
            .iter()
            .filter(|v| v.get("error").map(|e| e.is_null()).unwrap_or(true))
            .count();
        let running = self
            .task
            .lock()
            .await
            .as_ref()
            .is_some_and(|h| !h.is_finished());
        json!({
            "enabled": self.settings.poll.enabled,
            "running": running,
            "interval_secs": self.settings.poll.interval_secs,
            "cycles_completed": *self.cycles.lock().await,
            "cycle_errors": *self.errors.lock().await,
            "last_error": self.last_error.lock().await.clone(),
            "last_cycle_ts": *self.last_cycle_ts.lock().await,
            "last_cycle_duration_secs": self.last_cycle_duration.lock().await.map(|d| (d * 1000.0).round() / 1000.0),
            "points_tracked": last_values.len(),
            "points_healthy": healthy,
            "samples_buffered": self.samples.lock().await.len(),
            "last_values": last_values,
        })
    }
}

/// Buffer poll rows into last-value map + ring buffer; returns errored count.
fn ingest_poll_rows(
    samples: &mut VecDeque<Value>,
    last: &mut HashMap<String, Value>,
    rows: &[Value],
    max_samples: usize,
) -> usize {
    let mut errored = 0usize;
    for row in rows {
        let key = format!(
            "{}:{},{}",
            row["device_instance"].as_u64().unwrap_or(0),
            row["object_type"].as_str().unwrap_or(""),
            row["object_instance"].as_u64().unwrap_or(0)
        );
        last.insert(key, row.clone());
        samples.push_back(row.clone());
        while samples.len() > max_samples {
            samples.pop_front();
        }
        if row.get("error").and_then(|v| v.as_str()).is_some() {
            errored += 1;
        }
    }
    errored
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ingest_poll_rows_tracks_and_counts_errors() {
        let rows = vec![
            json!({"device_instance": 5007, "object_type": "analog-input", "object_instance": 1173, "error": null}),
            json!({"device_instance": 5007, "object_type": "analog-input", "object_instance": 1, "error": "timeout"}),
        ];
        let mut samples = VecDeque::new();
        let mut last = HashMap::new();
        let errored = ingest_poll_rows(&mut samples, &mut last, &rows, 5000);
        assert_eq!(errored, 1);
        assert_eq!(last.len(), 2);
        assert_eq!(samples.len(), 2);
    }

    #[test]
    fn ingest_poll_rows_respects_max_samples() {
        let rows: Vec<_> = (0..5)
            .map(|i| {
                json!({"device_instance": 1, "object_type": "ai", "object_instance": i, "error": null})
            })
            .collect();
        let mut samples = VecDeque::new();
        let mut last = HashMap::new();
        ingest_poll_rows(&mut samples, &mut last, &rows, 3);
        assert_eq!(samples.len(), 3);
        assert_eq!(last.len(), 5);
    }
}
