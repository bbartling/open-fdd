//! Transaction State Machine (TSM) per ASHRAE 135-2020 Clause 5.4.
//!
//! Tracks in-flight confirmed requests. Each request gets a unique invoke_id
//! (0-255) scoped per destination MAC. Responses are delivered via oneshot channels.

use bacnet_types::MacAddr;
use bytes::Bytes;
use std::collections::HashMap;
use tokio::sync::oneshot;

/// TSM configuration.
#[derive(Debug, Clone)]
pub struct TsmConfig {
    /// APDU timeout in milliseconds (default 6000).
    pub apdu_timeout_ms: u64,
    /// APDU segment timeout in milliseconds (default = apdu_timeout_ms).
    pub apdu_segment_timeout_ms: u64,
    /// Number of APDU retries (default 3).
    pub apdu_retries: u8,
}

impl Default for TsmConfig {
    fn default() -> Self {
        Self {
            apdu_timeout_ms: 6000,
            apdu_segment_timeout_ms: 6000,
            apdu_retries: 3,
        }
    }
}

/// Response types that complete a transaction.
#[derive(Debug)]
pub enum TsmResponse {
    /// SimpleACK — confirmed service completed with no return data.
    SimpleAck,
    /// ComplexACK — confirmed service returned data.
    ComplexAck { service_data: Bytes },
    /// Error PDU.
    Error { class: u32, code: u32 },
    /// Reject PDU.
    Reject { reason: u8 },
    /// Abort PDU.
    Abort { reason: u8 },
}

/// Invoke ID allocator scoped to a single destination MAC.
struct InvokeIdAllocator {
    next_id: u8,
    in_use: [bool; 256],
}

impl InvokeIdAllocator {
    fn new() -> Self {
        Self {
            next_id: 0,
            in_use: [false; 256],
        }
    }

    fn allocate(&mut self) -> Option<u8> {
        let start = self.next_id;
        loop {
            let id = self.next_id;
            self.next_id = self.next_id.wrapping_add(1);
            if !self.in_use[id as usize] {
                self.in_use[id as usize] = true;
                return Some(id);
            }
            if self.next_id == start {
                return None;
            }
        }
    }

    fn release(&mut self, id: u8) {
        self.in_use[id as usize] = false;
    }

    fn all_free(&self) -> bool {
        !self.in_use.iter().any(|&used| used)
    }
}

/// Maximum number of distinct destination MACs tracked by the TSM.
/// Prevents unbounded memory growth from spoofed source addresses.
const MAX_TSM_DESTINATIONS: usize = 1024;

/// Transaction State Machine.
///
/// Tracks pending confirmed requests and correlates responses by
/// `(destination_mac, invoke_id)`.
pub struct Tsm {
    config: TsmConfig,
    allocators: HashMap<MacAddr, InvokeIdAllocator>,
    pending: HashMap<(MacAddr, u8), oneshot::Sender<TsmResponse>>,
}

impl Tsm {
    pub fn new(config: TsmConfig) -> Self {
        Self {
            config,
            allocators: HashMap::new(),
            pending: HashMap::new(),
        }
    }

    pub fn config(&self) -> &TsmConfig {
        &self.config
    }

    /// Allocate an invoke ID for the given destination MAC.
    /// Returns `None` if all 256 IDs are in use for this destination,
    /// or if the maximum number of tracked destinations has been reached.
    pub fn allocate_invoke_id(&mut self, destination_mac: &[u8]) -> Option<u8> {
        let key = MacAddr::from_slice(destination_mac);
        if !self.allocators.contains_key(&key) && self.allocators.len() >= MAX_TSM_DESTINATIONS {
            return None;
        }
        let allocator = self
            .allocators
            .entry(key)
            .or_insert_with(InvokeIdAllocator::new);
        allocator.allocate()
    }

    /// Release an invoke ID back to the pool for the given destination.
    /// Removes the allocator entry if all IDs are now free (prevents unbounded growth).
    pub fn release_invoke_id(&mut self, destination_mac: &[u8], invoke_id: u8) {
        let key = MacAddr::from_slice(destination_mac);
        if let Some(allocator) = self.allocators.get_mut(&key) {
            allocator.release(invoke_id);
            if allocator.all_free() {
                self.allocators.remove(&key);
            }
        }
    }

    /// Register a pending transaction. Returns a receiver that will deliver
    /// the response when it arrives.
    pub fn register_transaction(
        &mut self,
        destination_mac: MacAddr,
        invoke_id: u8,
    ) -> oneshot::Receiver<TsmResponse> {
        let (tx, rx) = oneshot::channel();
        debug_assert!(
            !self
                .pending
                .contains_key(&(destination_mac.clone(), invoke_id)),
            "duplicate TSM registration for invoke_id {}",
            invoke_id
        );
        self.pending.insert((destination_mac, invoke_id), tx);
        rx
    }

    /// Deliver a response to a pending transaction. Returns `true` if found.
    pub fn complete_transaction(
        &mut self,
        source_mac: &[u8],
        invoke_id: u8,
        response: TsmResponse,
    ) -> bool {
        let key = (MacAddr::from_slice(source_mac), invoke_id);
        if let Some(tx) = self.pending.remove(&key) {
            self.release_invoke_id(source_mac, invoke_id);
            let _ = tx.send(response);
            true
        } else {
            false
        }
    }

    /// Cancel a pending transaction. Returns `true` if found.
    pub fn cancel_transaction(&mut self, destination_mac: &[u8], invoke_id: u8) -> bool {
        let key = (MacAddr::from_slice(destination_mac), invoke_id);
        if self.pending.remove(&key).is_some() {
            self.release_invoke_id(destination_mac, invoke_id);
            true
        } else {
            false
        }
    }

    pub fn pending_count(&self) -> usize {
        self.pending.len()
    }
}

/// Drop guard that cleans up invoke IDs if a confirmed request task is cancelled.
///
/// Uses `try_lock` in Drop — best-effort cleanup. If the mutex is contended
/// at drop time, the invoke ID leaks (acceptable: blocking in Drop is worse).
pub(crate) struct TsmGuard {
    tsm: std::sync::Arc<tokio::sync::Mutex<Tsm>>,
    mac: MacAddr,
    invoke_id: u8,
    completed: bool,
}

impl TsmGuard {
    pub(crate) fn new(
        tsm: std::sync::Arc<tokio::sync::Mutex<Tsm>>,
        mac: MacAddr,
        invoke_id: u8,
    ) -> Self {
        Self {
            tsm,
            mac,
            invoke_id,
            completed: false,
        }
    }

    /// Mark the transaction as completed (prevents cleanup on drop).
    pub(crate) fn mark_completed(&mut self) {
        self.completed = true;
    }
}

impl Drop for TsmGuard {
    fn drop(&mut self) {
        if !self.completed {
            if let Ok(mut tsm) = self.tsm.try_lock() {
                tsm.cancel_transaction(&self.mac, self.invoke_id);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allocate_invoke_id_sequential() {
        let mut tsm = Tsm::new(TsmConfig::default());
        let mac = [127, 0, 0, 1, 0xBA, 0xC0];
        let id1 = tsm.allocate_invoke_id(&mac);
        let id2 = tsm.allocate_invoke_id(&mac);
        assert_eq!(id1, Some(0));
        assert_eq!(id2, Some(1));
    }

    #[test]
    fn allocate_invoke_id_per_destination() {
        let mut tsm = Tsm::new(TsmConfig::default());
        let mac_a = [10, 0, 0, 1, 0xBA, 0xC0];
        let mac_b = [10, 0, 0, 2, 0xBA, 0xC0];
        let id_a = tsm.allocate_invoke_id(&mac_a);
        let id_b = tsm.allocate_invoke_id(&mac_b);
        assert_eq!(id_a, Some(0));
        assert_eq!(id_b, Some(0));
    }

    #[test]
    fn allocate_invoke_id_wraps() {
        let mut tsm = Tsm::new(TsmConfig::default());
        let mac = [127, 0, 0, 1, 0xBA, 0xC0];
        for i in 0..256 {
            assert_eq!(tsm.allocate_invoke_id(&mac), Some(i as u8));
        }
        assert_eq!(tsm.allocate_invoke_id(&mac), None);
    }

    #[test]
    fn release_makes_id_available() {
        let mut tsm = Tsm::new(TsmConfig::default());
        let mac = [127, 0, 0, 1, 0xBA, 0xC0];
        let id0 = tsm.allocate_invoke_id(&mac).unwrap();
        let id1 = tsm.allocate_invoke_id(&mac).unwrap();
        assert_eq!(id0, 0);
        assert_eq!(id1, 1);
        tsm.release_invoke_id(&mac, id0);
        let id2 = tsm.allocate_invoke_id(&mac).unwrap();
        assert_eq!(id2, 2);
        tsm.release_invoke_id(&mac, id1);
        tsm.release_invoke_id(&mac, id2);
        let id3 = tsm.allocate_invoke_id(&mac).unwrap();
        assert_eq!(id3, 0);
    }

    #[tokio::test]
    async fn register_and_complete_transaction() {
        let mut tsm = Tsm::new(TsmConfig::default());
        let mac = MacAddr::from_slice(&[127, 0, 0, 1, 0xBA, 0xC0]);
        let invoke_id = tsm.allocate_invoke_id(&mac).unwrap();

        let rx = tsm.register_transaction(mac.clone(), invoke_id);

        let response = TsmResponse::ComplexAck {
            service_data: Bytes::from_static(&[0xDE, 0xAD]),
        };
        let completed = tsm.complete_transaction(&mac, invoke_id, response);
        assert!(completed);

        let result = rx.await.unwrap();
        match result {
            TsmResponse::ComplexAck { service_data } => {
                assert_eq!(service_data, vec![0xDE, 0xAD]);
            }
            _ => panic!("Expected ComplexAck"),
        }
    }

    #[tokio::test]
    async fn complete_unknown_transaction_returns_false() {
        let mut tsm = Tsm::new(TsmConfig::default());
        let mac = MacAddr::from_slice(&[127, 0, 0, 1, 0xBA, 0xC0]);
        let completed = tsm.complete_transaction(&mac, 42, TsmResponse::SimpleAck);
        assert!(!completed);
    }

    #[test]
    fn cancel_transaction() {
        let mut tsm = Tsm::new(TsmConfig::default());
        let mac = MacAddr::from_slice(&[127, 0, 0, 1, 0xBA, 0xC0]);
        let invoke_id = tsm.allocate_invoke_id(&mac).unwrap();
        let _rx = tsm.register_transaction(mac.clone(), invoke_id);
        assert_eq!(tsm.pending_count(), 1);

        let cancelled = tsm.cancel_transaction(&mac, invoke_id);
        assert!(cancelled);
        assert_eq!(tsm.pending_count(), 0);
    }
}
