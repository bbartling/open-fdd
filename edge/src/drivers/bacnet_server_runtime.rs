//! Live Open-FDD BACnet/IP server (rusty-bacnet `BACnetServer`).
//!
//! Exposes diagnostic points on the local device (default instance 599999, name OpenFDD).
//! Field-bus client polls use an ephemeral UDP port so this server can bind :47808.

use super::bacnet_server;
use bacnet_objects::analog::AnalogValueObject;
use bacnet_objects::binary::BinaryValueObject;
use bacnet_objects::database::ObjectDatabase;
use bacnet_objects::device::{DeviceConfig, DeviceObject};
use bacnet_objects::traits::BACnetObject;
use bacnet_types::enums::{ObjectType, PropertyIdentifier};
use bacnet_types::primitives::{ObjectIdentifier, PropertyValue};
use rusty_bacnet_server::server::BACnetServer;
use std::env;
use std::net::Ipv4Addr;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, OnceLock};
use tokio::time::{sleep, Duration};

const UNITS_NONE: u32 = 95;
const UNITS_DEGF: u32 = 62;
const UNITS_PCT: u32 = 98;
const VENDOR_ID: u16 = 999;

static OPTIMIZATION_ENABLED: OnceLock<Arc<AtomicBool>> = OnceLock::new();

pub fn optimization_enabled() -> bool {
    OPTIMIZATION_ENABLED
        .get()
        .map(|f| f.load(Ordering::Relaxed))
        .unwrap_or(false)
}

pub fn set_optimization_enabled(enabled: bool) -> bool {
    if let Some(flag) = OPTIMIZATION_ENABLED.get() {
        flag.store(enabled, Ordering::Relaxed);
    }
    enabled
}

fn server_enabled() -> bool {
    env::var("OPENFDD_BACNET_SERVER_ENABLED")
        .map(|v| v != "0" && !v.eq_ignore_ascii_case("false"))
        .unwrap_or_else(|_| {
            env::var("OPENFDD_BACNET_ENABLED")
                .map(|v| v != "0" && !v.eq_ignore_ascii_case("false"))
                .unwrap_or(true)
        })
}

fn parse_bind() -> (Ipv4Addr, Ipv4Addr) {
    let bind = env::var("OPENFDD_BACNET_BIND").unwrap_or_else(|_| "0.0.0.0/24:47808".to_string());
    let ip_str = bind.split('/').next().unwrap_or("0.0.0.0");
    let ip: Ipv4Addr = ip_str.parse().unwrap_or(Ipv4Addr::UNSPECIFIED);
    let octets = ip.octets();
    let bcast = Ipv4Addr::new(octets[0], octets[1], octets[2], 255);
    (Ipv4Addr::UNSPECIFIED, bcast)
}

fn server_port() -> u16 {
    env::var("OPENFDD_BACNET_BIND")
        .ok()
        .and_then(|bind| bind.rsplit_once(':').and_then(|(_, p)| p.parse().ok()))
        .unwrap_or(0xBAC0)
}

pub fn build_database() -> Result<ObjectDatabase, String> {
    let inst = bacnet_server::device_instance();
    let name = bacnet_server::device_name();
    let mut db = ObjectDatabase::new();
    let device_oid = ObjectIdentifier::new(ObjectType::DEVICE, inst).map_err(|e| e.to_string())?;

    let mut fault_count = AnalogValueObject::new(9003, "openfdd-active-fault-count", UNITS_NONE)
        .map_err(|e| e.to_string())?;
    fault_count.set_description("Active FDD fault count");
    fault_count.set_present_value(0.0);
    db.add(Box::new(fault_count)).map_err(|e| e.to_string())?;

    let mut faults_present =
        BinaryValueObject::new(9004, "openfdd-faults-present").map_err(|e| e.to_string())?;
    faults_present.set_description("True when one or more FDD faults are active");
    faults_present
        .write_property(
            PropertyIdentifier::PRESENT_VALUE,
            None,
            PropertyValue::Enumerated(0),
            None,
        )
        .map_err(|e| e.to_string())?;
    db.add(Box::new(faults_present))
        .map_err(|e| e.to_string())?;

    let mut optimization =
        BinaryValueObject::new(9010, "openfdd-optimization-enabled").map_err(|e| e.to_string())?;
    optimization.set_description("Commandable optimization enable (writable via BACnet or API)");
    optimization
        .write_property(
            PropertyIdentifier::PRESENT_VALUE,
            None,
            PropertyValue::Enumerated(0),
            None,
        )
        .map_err(|e| e.to_string())?;
    db.add(Box::new(optimization)).map_err(|e| e.to_string())?;

    for (instance, point_name, desc) in [
        (
            9101,
            "outside-air-temperature",
            "Outside air temperature (placeholder)",
        ),
        (
            9102,
            "outside-air-humidity",
            "Outside air humidity (placeholder)",
        ),
        (
            9103,
            "outside-air-dewpoint",
            "Outside air dewpoint (placeholder)",
        ),
    ] {
        let units = if instance == 9102 {
            UNITS_PCT
        } else {
            UNITS_DEGF
        };
        let mut av =
            AnalogValueObject::new(instance, point_name, units).map_err(|e| e.to_string())?;
        av.set_description(desc);
        av.set_present_value(0.0);
        db.add(Box::new(av)).map_err(|e| e.to_string())?;
    }

    let mut point_oids = db.list_objects();
    point_oids.sort_by_key(|o| (o.object_type().to_raw(), o.instance_number()));
    let mut object_list = vec![device_oid];
    object_list.extend(point_oids);

    let mut device = DeviceObject::new(DeviceConfig {
        instance: inst,
        name: name.clone(),
        vendor_name: "Open-FDD".into(),
        vendor_id: VENDOR_ID,
        model_name: "open-fdd-edge".into(),
        application_software_version: env!("CARGO_PKG_VERSION").into(),
        ..DeviceConfig::default()
    })
    .map_err(|e| e.to_string())?;
    device.set_object_list(object_list);
    db.add(Box::new(device)).map_err(|e| e.to_string())?;

    Ok(db)
}

async fn sync_metrics(db: &mut ObjectDatabase) {
    let active = crate::faults::summary_json()
        .get("active_count")
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as f32;

    if let Ok(oid) = ObjectIdentifier::new(ObjectType::ANALOG_VALUE, 9003) {
        if let Some(obj) = db.get_mut(&oid) {
            let _ = obj.as_mut().write_property(
                PropertyIdentifier::PRESENT_VALUE,
                None,
                PropertyValue::Real(active),
                None,
            );
        }
    }
    if let Ok(oid) = ObjectIdentifier::new(ObjectType::BINARY_VALUE, 9004) {
        if let Some(obj) = db.get_mut(&oid) {
            let _ = obj.as_mut().write_property(
                PropertyIdentifier::PRESENT_VALUE,
                None,
                PropertyValue::Enumerated(if active > 0.0 { 1 } else { 0 }),
                None,
            );
        }
    }
    if let Ok(oid) = ObjectIdentifier::new(ObjectType::BINARY_VALUE, 9010) {
        if let Some(obj) = db.get_mut(&oid) {
            if let Ok(PropertyValue::Enumerated(v)) = obj
                .as_mut()
                .read_property(PropertyIdentifier::PRESENT_VALUE, None)
            {
                if let Some(flag) = OPTIMIZATION_ENABLED.get() {
                    flag.store(v == 1, Ordering::Relaxed);
                }
            }
        }
    }
}

async fn metrics_refresh_task(db: Arc<tokio::sync::RwLock<ObjectDatabase>>) {
    loop {
        {
            let mut guard = db.write().await;
            sync_metrics(&mut guard).await;
        }
        sleep(Duration::from_secs(30)).await;
    }
}

async fn run_server() -> Result<(), String> {
    let (_iface, bcast) = parse_bind();
    let port = server_port();
    let db = build_database()?;

    let opt_flag = Arc::new(AtomicBool::new(false));
    let _ = OPTIMIZATION_ENABLED.set(opt_flag);

    let mut server = BACnetServer::bip_builder()
        .interface(Ipv4Addr::UNSPECIFIED)
        .port(port)
        .broadcast_address(bcast)
        .database(db)
        .build()
        .await
        .map_err(|e| e.to_string())?;

    let server_db = server.database().clone();
    tokio::spawn(metrics_refresh_task(server_db));

    eprintln!(
        "Open-FDD BACnet server on UDP :{port} (device {} / {})",
        bacnet_server::device_instance(),
        bacnet_server::device_name()
    );

    loop {
        sleep(Duration::from_secs(3600)).await;
    }
}

pub fn start_background() {
    if !server_enabled() || !super::bacnet_live::is_live_mode() {
        return;
    }
    std::thread::spawn(|| {
        super::bacnet_live::block_on(async {
            if let Err(e) = run_server().await {
                eprintln!("Open-FDD BACnet server error: {e}");
            }
        });
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn build_database_has_openfdd_points() {
        let db = build_database().expect("database");
        assert!(db.len() >= 6);
    }
}
