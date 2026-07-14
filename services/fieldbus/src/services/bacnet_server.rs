//! Hosted BACnet server from objects.csv (mirrors `app/bacnet_server.py`).

use std::collections::HashMap;
use std::sync::Arc;

use bacnet_objects::analog::{AnalogInputObject, AnalogValueObject};
use bacnet_objects::binary::{BinaryInputObject, BinaryValueObject};
use bacnet_objects::database::ObjectDatabase;
use bacnet_objects::device::{DeviceConfig, DeviceObject};
use bacnet_objects::traits::BACnetObject;
use bacnet_objects::value_types::CharacterStringValueObject;
use bacnet_server::server::BACnetServer;
use bacnet_transport::bip::BipTransport;
use bacnet_types::enums::{ObjectType, PropertyIdentifier};
use bacnet_types::primitives::{ObjectIdentifier, PropertyValue};
use tokio::sync::Mutex;
use tracing::info;

use crate::config::{load_objects_csv, HostedObjectRow, Settings};

/// ASHRAE vendor ID for Open-FDD hosted devices (matches openfdd-bacnet-mimic).
const OPENFDD_VENDOR_ID: u16 = 999;

/// Rejection message when REST tries to write a BACnet-commandable point.
pub const API_WRITABLE_REJECT_MSG: &str =
    "rejected: commandable point is BACnet-writable (read-only via API)";

const UNITS_MAP: &[(&str, u32)] = &[
    ("degreesfahrenheit", 62),
    ("degf", 62),
    ("percent", 98),
    ("pct", 98),
    ("milesphour", 72),
    ("mph", 72),
    ("nounits", 95),
    ("status", 95),
    ("", 95),
];

fn units_code(units: &str) -> u32 {
    let key = units.replace(' ', "").to_ascii_lowercase();
    UNITS_MAP
        .iter()
        .find(|(k, _)| *k == key)
        .map(|(_, v)| *v)
        .unwrap_or(95)
}

fn parse_float(s: &str, default: f64) -> f64 {
    s.parse().unwrap_or(default)
}

pub type HostedServer = BACnetServer<BipTransport>;

pub struct BacnetServerManager {
    settings: Settings,
    server: Mutex<Option<Arc<Mutex<HostedServer>>>>,
}

impl BacnetServerManager {
    pub fn new(settings: Settings) -> Self {
        Self {
            settings,
            server: Mutex::new(None),
        }
    }

    pub fn api_writable(row: &HostedObjectRow) -> bool {
        !row.commandable
    }

    /// Guard used by REST update paths — commandable points are BACnet-only.
    pub fn reject_api_write(row: &HostedObjectRow) -> Option<String> {
        if Self::api_writable(row) {
            None
        } else {
            Some(format!("{}: {}", API_WRITABLE_REJECT_MSG, row.name))
        }
    }

    async fn server(&self) -> Result<Arc<Mutex<HostedServer>>, String> {
        self.server
            .lock()
            .await
            .clone()
            .ok_or_else(|| "BACnet server not started".into())
    }

    pub async fn start(&self) -> Result<(), String> {
        let cfg = &self.settings.bacnet_server;
        let rows = load_objects_csv(Some(&self.settings.objects_csv))?;
        let db = build_database(cfg.device_instance, &cfg.device_name, &rows)?;

        let server = BACnetServer::bip_builder()
            .interface(cfg.interface)
            .port(cfg.port)
            .broadcast_address(cfg.broadcast)
            .database(db)
            .build()
            .await
            .map_err(|e| e.to_string())?;

        apply_csv_defaults(&server, &rows).await?;

        let mac = server.local_mac();
        info!(
            "BACnet server {} ({}) listening on {}",
            cfg.device_instance,
            cfg.device_name,
            format_mac(mac)
        );

        *self.server.lock().await = Some(Arc::new(Mutex::new(server)));
        Ok(())
    }

    pub async fn stop(&self) -> Result<(), String> {
        if let Some(srv) = self.server.lock().await.take() {
            let mut guard = srv.lock().await;
            guard.stop().await.map_err(|e| e.to_string())?;
        }
        Ok(())
    }

    pub async fn list_objects(&self) -> Result<Vec<serde_json::Value>, String> {
        let rows = load_objects_csv(Some(&self.settings.objects_csv))?;
        let srv = self.server().await?;
        let srv = srv.lock().await;
        let db = srv.database();
        let db = db.read().await;

        let mut out = Vec::new();
        for row in rows {
            let oid = oid_for_point(&row.point_type, row.instance)?;
            let (value, tag) = read_pv(&db, &oid);
            let description = read_description(&db, &oid);
            out.push(serde_json::json!({
                "name": row.name,
                "object_type": row.point_type,
                "instance": row.instance,
                "units": row.units,
                "description": description,
                "commandable": row.commandable,
                "api_writable": Self::api_writable(&row),
                "present_value": value,
                "tag": tag,
            }));
        }
        Ok(out)
    }

    pub async fn list_commandable(&self) -> Result<Vec<serde_json::Value>, String> {
        let rows = load_objects_csv(Some(&self.settings.objects_csv))?;
        let srv = self.server().await?;
        let srv = srv.lock().await;
        let db = srv.database();
        let db = db.read().await;

        let mut out = Vec::new();
        for row in rows.into_iter().filter(|r| r.commandable) {
            let oid = oid_for_point(&row.point_type, row.instance)?;
            let (value, tag) = read_pv(&db, &oid);
            out.push(serde_json::json!({
                "name": row.name,
                "object_type": row.point_type,
                "instance": row.instance,
                "commandable": true,
                "api_writable": false,
                "present_value": value,
                "tag": tag,
            }));
        }
        Ok(out)
    }

    pub async fn update_points(
        &self,
        updates: HashMap<String, serde_json::Value>,
    ) -> Result<HashMap<String, String>, String> {
        let rows: HashMap<_, _> = load_objects_csv(Some(&self.settings.objects_csv))?
            .into_iter()
            .map(|r| (r.name.clone(), r))
            .collect();
        let mut result = HashMap::new();
        for (name, value) in updates {
            let Some(row) = rows.get(&name) else {
                result.insert(name, "not found".into());
                continue;
            };
            if let Some(msg) = Self::reject_api_write(row) {
                result.insert(name, msg);
                continue;
            }
            let pt = row.point_type.to_ascii_uppercase();
            let write_result = match pt.as_str() {
                "BV" | "BI" => {
                    let active = match &value {
                        serde_json::Value::Bool(b) => *b,
                        _ => value
                            .as_str()
                            .map(|s| {
                                matches!(
                                    s.trim().to_ascii_lowercase().as_str(),
                                    "1" | "true" | "active" | "on" | "yes"
                                )
                            })
                            .unwrap_or(false),
                    };
                    self.write_binary_active(row.instance, active).await
                }
                "CSV" => {
                    self.write_present_value(
                        &pt,
                        row.instance,
                        PropertyValue::CharacterString(value.as_str().unwrap_or("").to_string()),
                    )
                    .await
                }
                _ => {
                    let f = value.as_f64().unwrap_or_else(|| {
                        value.as_str().and_then(|s| s.parse().ok()).unwrap_or(0.0)
                    });
                    self.write_present_value(&pt, row.instance, PropertyValue::Real(f as f32))
                        .await
                }
            };
            match write_result {
                Ok(()) => {
                    result.insert(name, "updated".into());
                }
                Err(e) => {
                    result.insert(name, format!("error: {e}"));
                }
            }
        }
        Ok(result)
    }

    pub async fn write_description(
        &self,
        point_type: &str,
        instance: u32,
        description: &str,
    ) -> Result<(), String> {
        if description.is_empty() {
            return Ok(());
        }
        let oid = oid_for_point(point_type, instance)?;
        let srv = self.server().await?;
        let srv = srv.lock().await;
        let db = srv.database();
        let mut db = db.write().await;
        let obj = db
            .get_mut(&oid)
            .ok_or_else(|| format!("object not found: {oid}"))?;
        obj.write_property(
            PropertyIdentifier::DESCRIPTION,
            None,
            PropertyValue::CharacterString(description.to_string()),
            None,
        )
        .map_err(|e| e.to_string())
    }

    pub async fn write_present_value(
        &self,
        point_type: &str,
        instance: u32,
        pv: PropertyValue,
    ) -> Result<(), String> {
        let oid = oid_for_point(point_type, instance)?;
        let srv = self.server().await?;
        let srv = srv.lock().await;
        let db = srv.database();
        let mut db = db.write().await;
        let obj = db
            .get_mut(&oid)
            .ok_or_else(|| format!("object not found: {oid}"))?;
        obj.write_property(PropertyIdentifier::PRESENT_VALUE, None, pv, None)
            .map_err(|e| e.to_string())
    }

    pub async fn write_binary_active(&self, instance: u32, active: bool) -> Result<(), String> {
        self.write_present_value(
            "BV",
            instance,
            PropertyValue::Enumerated(if active { 1 } else { 0 }),
        )
        .await
    }
}

fn build_database(
    device_instance: u32,
    device_name: &str,
    rows: &[HostedObjectRow],
) -> Result<ObjectDatabase, String> {
    let mut db = ObjectDatabase::new();
    let device_oid =
        ObjectIdentifier::new(ObjectType::DEVICE, device_instance).map_err(|e| e.to_string())?;

    for row in rows {
        let pt = row.point_type.to_ascii_uppercase();
        let inst = row.instance;
        let name = row.name.as_str();
        let units = units_code(&row.units);
        match pt.as_str() {
            "AV" => {
                let mut av =
                    AnalogValueObject::new(inst, name, units).map_err(|e| e.to_string())?;
                apply_static_description(&mut av, row);
                av.set_present_value(parse_float(&row.default, 0.0) as f32);
                db.add(Box::new(av)).map_err(|e| e.to_string())?;
            }
            "AI" => {
                let pv = parse_float(&row.default, 0.0) as f32;
                let mut ai =
                    AnalogInputObject::new(inst, name, units).map_err(|e| e.to_string())?;
                apply_static_description(&mut ai, row);
                ai.set_present_value(pv);
                db.add(Box::new(ai)).map_err(|e| e.to_string())?;
            }
            "BI" => {
                let mut bi = BinaryInputObject::new(inst, name).map_err(|e| e.to_string())?;
                apply_static_description(&mut bi, row);
                if row.default.eq_ignore_ascii_case("active") {
                    bi.set_present_value(1);
                }
                db.add(Box::new(bi)).map_err(|e| e.to_string())?;
            }
            "BV" => {
                let mut bv = BinaryValueObject::new(inst, name).map_err(|e| e.to_string())?;
                apply_static_description(&mut bv, row);
                if !row.default.eq_ignore_ascii_case("active") {
                    bv.write_property(
                        PropertyIdentifier::PRESENT_VALUE,
                        None,
                        PropertyValue::Enumerated(0),
                        None,
                    )
                    .map_err(|e| e.to_string())?;
                }
                db.add(Box::new(bv)).map_err(|e| e.to_string())?;
            }
            "CSV" => {
                let mut csv =
                    CharacterStringValueObject::new(inst, name).map_err(|e| e.to_string())?;
                apply_static_description_csv(&mut csv, row);
                if !row.default.is_empty() {
                    csv.write_property(
                        PropertyIdentifier::PRESENT_VALUE,
                        None,
                        PropertyValue::CharacterString(row.default.clone()),
                        None,
                    )
                    .map_err(|e| e.to_string())?;
                }
                db.add(Box::new(csv)).map_err(|e| e.to_string())?;
            }
            other => return Err(format!("Unsupported PointType {other} for {name}")),
        }
    }

    let mut point_oids = db.list_objects();
    point_oids.sort_by_key(|o| (o.object_type().to_raw(), o.instance_number()));
    let mut object_list = vec![device_oid];
    object_list.extend(point_oids);

    let mut device = DeviceObject::new(DeviceConfig {
        instance: device_instance,
        name: device_name.to_string(),
        vendor_name: "Open-FDD".into(),
        vendor_id: OPENFDD_VENDOR_ID,
        model_name: "openfdd-fieldbus".into(),
        application_software_version: env!("CARGO_PKG_VERSION").into(),
        max_apdu_length: 1476,
        ..DeviceConfig::default()
    })
    .map_err(|e| e.to_string())?;
    device.set_object_list(object_list);
    device.set_description("Open-FDD field-bus gateway with Open-Meteo weather mirror");
    db.add(Box::new(device)).map_err(|e| e.to_string())?;
    Ok(db)
}

fn apply_static_description<T: HasDescription>(obj: &mut T, row: &HostedObjectRow) {
    if !row.description.is_empty() {
        obj.set_description(&row.description);
    }
}

fn apply_static_description_csv(obj: &mut CharacterStringValueObject, row: &HostedObjectRow) {
    if row.description.is_empty() {
        return;
    }
    let _ = obj.write_property(
        PropertyIdentifier::DESCRIPTION,
        None,
        PropertyValue::CharacterString(row.description.clone()),
        None,
    );
}

trait HasDescription {
    fn set_description(&mut self, desc: &str);
}

impl HasDescription for AnalogValueObject {
    fn set_description(&mut self, desc: &str) {
        AnalogValueObject::set_description(self, desc);
    }
}

impl HasDescription for AnalogInputObject {
    fn set_description(&mut self, desc: &str) {
        AnalogInputObject::set_description(self, desc);
    }
}

impl HasDescription for BinaryInputObject {
    fn set_description(&mut self, desc: &str) {
        BinaryInputObject::set_description(self, desc);
    }
}

impl HasDescription for BinaryValueObject {
    fn set_description(&mut self, desc: &str) {
        BinaryValueObject::set_description(self, desc);
    }
}

async fn apply_csv_defaults(server: &HostedServer, rows: &[HostedObjectRow]) -> Result<(), String> {
    let db = server.database();
    let mut db = db.write().await;
    for row in rows {
        let pt = row.point_type.to_ascii_uppercase();
        let oid = oid_for_point(&pt, row.instance)?;
        let obj = db.get_mut(&oid).ok_or_else(|| format!("missing {oid}"))?;
        match pt.as_str() {
            "AV" => {
                obj.write_property(
                    PropertyIdentifier::PRESENT_VALUE,
                    None,
                    PropertyValue::Real(parse_float(&row.default, 0.0) as f32),
                    None,
                )
                .map_err(|e| e.to_string())?;
            }
            "CSV" if !row.default.is_empty() => {
                obj.write_property(
                    PropertyIdentifier::PRESENT_VALUE,
                    None,
                    PropertyValue::CharacterString(row.default.clone()),
                    None,
                )
                .map_err(|e| e.to_string())?;
            }
            "BV" if row.default.eq_ignore_ascii_case("inactive") => {
                obj.write_property(
                    PropertyIdentifier::PRESENT_VALUE,
                    None,
                    PropertyValue::Enumerated(0),
                    None,
                )
                .map_err(|e| e.to_string())?;
            }
            _ => {}
        }
    }
    Ok(())
}

fn oid_for_point(point_type: &str, instance: u32) -> Result<ObjectIdentifier, String> {
    let ot = match point_type.to_ascii_uppercase().as_str() {
        "AV" => ObjectType::ANALOG_VALUE,
        "AI" => ObjectType::ANALOG_INPUT,
        "BI" => ObjectType::BINARY_INPUT,
        "BV" => ObjectType::BINARY_VALUE,
        "CSV" => ObjectType::CHARACTERSTRING_VALUE,
        other => return Err(format!("unknown point type {other}")),
    };
    ObjectIdentifier::new(ot, instance).map_err(|e| e.to_string())
}

fn read_description(db: &ObjectDatabase, oid: &ObjectIdentifier) -> String {
    match db.get(oid) {
        Some(obj) => match obj.read_property(PropertyIdentifier::DESCRIPTION, None) {
            Ok(PropertyValue::CharacterString(s)) => s,
            _ => String::new(),
        },
        None => String::new(),
    }
}

fn read_pv(db: &ObjectDatabase, oid: &ObjectIdentifier) -> (serde_json::Value, String) {
    match db.get(oid) {
        Some(obj) => match obj.read_property(PropertyIdentifier::PRESENT_VALUE, None) {
            Ok(pv) => (property_value_to_json(&pv), property_value_tag(&pv)),
            Err(e) => (serde_json::Value::Null, format!("error: {e}")),
        },
        None => (serde_json::Value::Null, "error: not found".into()),
    }
}

pub fn property_value_tag(pv: &PropertyValue) -> String {
    match pv {
        PropertyValue::Null => "null".into(),
        PropertyValue::Boolean(_) => "boolean".into(),
        PropertyValue::Unsigned(_) => "unsigned".into(),
        PropertyValue::Signed(_) => "signed".into(),
        PropertyValue::Real(_) => "real".into(),
        PropertyValue::Double(_) => "double".into(),
        PropertyValue::Enumerated(_) => "enumerated".into(),
        PropertyValue::CharacterString(_) => "character_string".into(),
        PropertyValue::ObjectIdentifier(_) => "object_identifier".into(),
        _ => "unknown".into(),
    }
}

pub fn property_value_to_json(pv: &PropertyValue) -> serde_json::Value {
    match pv {
        PropertyValue::Null => serde_json::Value::Null,
        PropertyValue::Boolean(v) => serde_json::json!(v),
        PropertyValue::Unsigned(v) => serde_json::json!(v),
        PropertyValue::Signed(v) => serde_json::json!(v),
        PropertyValue::Real(v) => serde_json::json!(v),
        PropertyValue::Double(v) => serde_json::json!(v),
        PropertyValue::Enumerated(v) => serde_json::json!(v),
        PropertyValue::CharacterString(v) => serde_json::json!(v),
        PropertyValue::ObjectIdentifier(oid) => {
            serde_json::json!(format!(
                "{},{}",
                object_type_name(oid.object_type()),
                oid.instance_number()
            ))
        }
        other => serde_json::json!(format!("{other:?}")),
    }
}

fn object_type_name(ot: ObjectType) -> String {
    format!("{ot}").to_ascii_lowercase().replace('_', "-")
}

fn format_mac(mac: &[u8]) -> String {
    if mac.len() == 6 {
        format!(
            "{:02x}:{:02x}:{:02x}:{:02x}:{:02x}:{:02x}",
            mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]
        )
    } else {
        hex::encode(mac)
    }
}

// hex helper without adding dep — use simple format
mod hex {
    pub fn encode(bytes: &[u8]) -> String {
        bytes.iter().map(|b| format!("{b:02x}")).collect()
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;
    use crate::config::{load_objects_csv, load_settings, HostedObjectRow};

    #[test]
    fn api_writable_split() {
        let row = HostedObjectRow {
            name: "x".into(),
            point_type: "AV".into(),
            units: String::new(),
            commandable: false,
            default: String::new(),
            instance: 1,
            description: String::new(),
        };
        assert!(BacnetServerManager::api_writable(&row));
        let cmd = HostedObjectRow {
            commandable: true,
            ..row
        };
        assert!(!BacnetServerManager::api_writable(&cmd));
    }

    #[tokio::test]
    async fn update_rejects_commandable_point() {
        let mgr = BacnetServerManager::new(load_settings());
        let mut updates = HashMap::new();
        updates.insert(
            "openfdd-optimization-enabled".into(),
            serde_json::json!(true),
        );
        let result = mgr.update_points(updates).await.expect("update");
        assert!(result["openfdd-optimization-enabled"].contains("rejected"));
    }

    #[tokio::test]
    async fn update_unknown_point_not_found() {
        let mgr = BacnetServerManager::new(load_settings());
        let mut updates = HashMap::new();
        updates.insert("does-not-exist".into(), serde_json::json!(1));
        let result = mgr.update_points(updates).await.expect("update");
        assert_eq!(result["does-not-exist"], "not found");
    }

    #[tokio::test]
    async fn update_mixed_rejects_only_commandable() {
        let mgr = BacnetServerManager::new(load_settings());
        let mut updates = HashMap::new();
        updates.insert(
            "openfdd-optimization-enabled".into(),
            serde_json::json!(true),
        );
        updates.insert("missing-point".into(), serde_json::json!(5));
        let result = mgr.update_points(updates).await.expect("update");
        assert!(result["openfdd-optimization-enabled"].contains("rejected"));
        assert_eq!(result["missing-point"], "not found");
    }

    #[test]
    fn server_owned_points_are_api_writable() {
        std::env::set_var(
            "OPENFDD_FIELDBUS_CONFIG_DIR",
            format!("{}/../../config/fieldbus", env!("CARGO_MANIFEST_DIR")),
        );
        let rows: HashMap<_, _> = load_objects_csv(None)
            .expect("csv")
            .into_iter()
            .map(|r| (r.name.clone(), r))
            .collect();
        assert!(BacnetServerManager::api_writable(
            &rows["outside-air-temperature"]
        ));
        assert!(BacnetServerManager::api_writable(
            &rows["openfdd-active-fault-count"]
        ));
        assert!(!BacnetServerManager::api_writable(
            &rows["openfdd-optimization-enabled"]
        ));
    }

    #[test]
    fn every_commandable_point_rejects_api_write() {
        std::env::set_var(
            "OPENFDD_FIELDBUS_CONFIG_DIR",
            format!("{}/../../config/fieldbus", env!("CARGO_MANIFEST_DIR")),
        );
        for row in load_objects_csv(None).expect("csv") {
            if row.commandable {
                assert!(
                    BacnetServerManager::reject_api_write(&row).is_some(),
                    "{} must reject REST writes",
                    row.name
                );
                assert!(!BacnetServerManager::api_writable(&row));
            } else {
                assert!(BacnetServerManager::reject_api_write(&row).is_none());
            }
        }
    }

    #[test]
    fn optimization_enabled_is_only_commandable_hosted_point() {
        std::env::set_var(
            "OPENFDD_FIELDBUS_CONFIG_DIR",
            format!("{}/../../config/fieldbus", env!("CARGO_MANIFEST_DIR")),
        );
        let commandable: Vec<_> = load_objects_csv(None)
            .expect("csv")
            .into_iter()
            .filter(|r| r.commandable)
            .collect();
        assert_eq!(commandable.len(), 1);
        assert_eq!(commandable[0].name, "openfdd-optimization-enabled");
        assert_eq!(commandable[0].instance, 9010);
    }
}
