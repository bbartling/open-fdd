//! Device discovery table — collects IAm responses for WhoIs/WhoHas lookups.

use std::collections::HashMap;
use std::time::{Duration, Instant};

use bacnet_types::enums::Segmentation;
use bacnet_types::primitives::ObjectIdentifier;
use bacnet_types::MacAddr;

/// Information about a discovered BACnet device.
#[derive(Debug, Clone)]
pub struct DiscoveredDevice {
    /// The device's object identifier (always ObjectType::DEVICE).
    pub object_identifier: ObjectIdentifier,
    /// The MAC address from which the IAm was received.
    pub mac_address: MacAddr,
    /// Maximum APDU length the device accepts.
    pub max_apdu_length: u32,
    /// Segmentation support level.
    pub segmentation_supported: Segmentation,
    /// Maximum segments the remote device accepts (None = unlimited/unspecified).
    pub max_segments_accepted: Option<u32>,
    /// Vendor identifier.
    pub vendor_id: u16,
    /// When this entry was last updated.
    pub last_seen: Instant,
    /// If this device is behind a router, the BACnet network number it resides on.
    pub source_network: Option<u16>,
    /// If this device is behind a router, its MAC address on the remote network.
    pub source_address: Option<MacAddr>,
}

/// Thread-safe device discovery table.
///
/// Keyed by device instance number (the instance part of the DEVICE object
/// identifier). Updated whenever an IAm is received.
#[derive(Debug, Default)]
pub struct DeviceTable {
    devices: HashMap<u32, DiscoveredDevice>,
}

impl DeviceTable {
    pub fn new() -> Self {
        Self {
            devices: HashMap::new(),
        }
    }

    /// Insert or update a discovered device.
    ///
    /// The table is capped at 4096 entries. If the table is full and the
    /// device is not already present, the new entry is silently dropped.
    pub fn upsert(&mut self, device: DiscoveredDevice) {
        const MAX_DEVICE_TABLE_ENTRIES: usize = 4096;
        let key = device.object_identifier.instance_number();
        if !self.devices.contains_key(&key) && self.devices.len() >= MAX_DEVICE_TABLE_ENTRIES {
            return;
        }
        self.devices.insert(key, device);
    }

    /// Get all discovered devices as a snapshot.
    pub fn all(&self) -> Vec<DiscoveredDevice> {
        self.devices.values().cloned().collect()
    }

    /// Look up a device by instance number.
    pub fn get(&self, instance: u32) -> Option<&DiscoveredDevice> {
        self.devices.get(&instance)
    }

    /// Look up a device by its MAC address.
    pub fn get_by_mac(&self, mac: &[u8]) -> Option<&DiscoveredDevice> {
        self.devices
            .values()
            .find(|d| d.mac_address.as_slice() == mac)
    }

    /// Clear all entries.
    pub fn clear(&mut self) {
        self.devices.clear();
    }

    /// Number of discovered devices.
    pub fn len(&self) -> usize {
        self.devices.len()
    }

    /// Whether the table is empty.
    pub fn is_empty(&self) -> bool {
        self.devices.is_empty()
    }

    /// Remove entries whose `last_seen` is older than `max_age`.
    pub fn purge_stale(&mut self, max_age: Duration) {
        let cutoff = Instant::now() - max_age;
        self.devices.retain(|_, d| d.last_seen >= cutoff);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use bacnet_types::enums::ObjectType;

    fn make_device(instance: u32) -> DiscoveredDevice {
        DiscoveredDevice {
            object_identifier: ObjectIdentifier::new(ObjectType::DEVICE, instance).unwrap(),
            mac_address: MacAddr::from_slice(&[192, 168, 1, 100, 0xBA, 0xC0]),
            max_apdu_length: 1476,
            segmentation_supported: Segmentation::NONE,
            max_segments_accepted: None,
            vendor_id: 42,
            last_seen: Instant::now(),
            source_network: None,
            source_address: None,
        }
    }

    #[test]
    fn upsert_and_get() {
        let mut table = DeviceTable::new();
        table.upsert(make_device(1234));
        assert_eq!(table.len(), 1);
        let dev = table.get(1234).unwrap();
        assert_eq!(dev.vendor_id, 42);
    }

    #[test]
    fn upsert_updates_existing() {
        let mut table = DeviceTable::new();
        table.upsert(make_device(1234));
        let mut updated = make_device(1234);
        updated.vendor_id = 99;
        table.upsert(updated);
        assert_eq!(table.len(), 1);
        assert_eq!(table.get(1234).unwrap().vendor_id, 99);
    }

    #[test]
    fn all_returns_snapshot() {
        let mut table = DeviceTable::new();
        table.upsert(make_device(1));
        table.upsert(make_device(2));
        table.upsert(make_device(3));
        assert_eq!(table.all().len(), 3);
    }

    #[test]
    fn clear_empties_table() {
        let mut table = DeviceTable::new();
        table.upsert(make_device(1));
        table.clear();
        assert!(table.is_empty());
    }

    #[test]
    fn get_by_mac_finds_device() {
        let mut table = DeviceTable::new();
        table.upsert(make_device(1234));
        let mac = &[192, 168, 1, 100, 0xBA, 0xC0];
        let dev = table.get_by_mac(mac).unwrap();
        assert_eq!(dev.object_identifier.instance_number(), 1234);
    }

    #[test]
    fn get_by_mac_not_found() {
        let mut table = DeviceTable::new();
        table.upsert(make_device(1234));
        assert!(table.get_by_mac(&[10, 0, 0, 1, 0xBA, 0xC0]).is_none());
    }

    #[test]
    fn purge_stale_removes_old_entries() {
        let mut table = DeviceTable::new();
        let mut old_device = make_device(1);
        old_device.last_seen = Instant::now() - Duration::from_secs(120);
        table.upsert(old_device);
        table.upsert(make_device(2));
        assert_eq!(table.len(), 2);

        table.purge_stale(Duration::from_secs(60));
        assert_eq!(table.len(), 1);
        assert!(table.get(1).is_none());
        assert!(table.get(2).is_some());
    }

    #[test]
    fn purge_stale_keeps_all_when_fresh() {
        let mut table = DeviceTable::new();
        table.upsert(make_device(1));
        table.upsert(make_device(2));
        table.purge_stale(Duration::from_secs(60));
        assert_eq!(table.len(), 2);
    }

    #[test]
    fn purge_stale_removes_all_when_expired() {
        let mut table = DeviceTable::new();
        let mut d1 = make_device(1);
        d1.last_seen = Instant::now() - Duration::from_secs(200);
        let mut d2 = make_device(2);
        d2.last_seen = Instant::now() - Duration::from_secs(200);
        table.upsert(d1);
        table.upsert(d2);
        table.purge_stale(Duration::from_secs(60));
        assert!(table.is_empty());
    }

    #[test]
    fn upsert_refreshes_last_seen() {
        let mut table = DeviceTable::new();
        let mut old_device = make_device(1);
        old_device.last_seen = Instant::now() - Duration::from_secs(120);
        table.upsert(old_device);

        table.upsert(make_device(1));
        table.purge_stale(Duration::from_secs(60));
        assert_eq!(table.len(), 1);
        assert!(table.get(1).is_some());
    }
}
