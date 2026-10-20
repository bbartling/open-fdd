//! Canonical live-historian flush. Portal and CSV samples share this writer.
//! MQTT subscribe, edge shadow, and broker receipts live under
//! `archive/ot-edge/unmaintained/services/central/src/ingest.rs`.

use std::sync::Arc;
use std::time::Duration;

use tokio::sync::watch;
use tokio::task::JoinHandle;
use tracing::warn;

use crate::state::AppState;

pub fn spawn_live_historian_flush_with_shutdown(
    state: Arc<AppState>,
    mut shutdown: watch::Receiver<bool>,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        let mut tick = tokio::time::interval(Duration::from_secs(1));
        tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            tokio::select! {
                _ = tick.tick() => {
                    if let Err(error) = state.flush_live(false).await {
                        warn!(%error, "canonical live historian time flush failed; buffered rows retained for retry");
                    }
                }
                changed = shutdown.changed() => {
                    if changed.is_err() || *shutdown.borrow() {
                        if let Err(error) = state.flush_live(true).await {
                            warn!(%error, "canonical live historian graceful flush failed");
                        }
                        return;
                    }
                }
            }
        }
    })
}
