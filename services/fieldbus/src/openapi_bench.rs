//! Swagger Try-it-out examples — bench targets vs generic production placeholders.

use std::collections::BTreeMap;

use serde_json::{json, Value};
use utoipa::openapi::{OpenApi, RefOr, Schema};

/// Default bench API key when env is unset (local/docker demo only).
pub const DEFAULT_BENCH_API_KEY: &str = "bench-demo-key-1234567890";

/// True when Swagger should show bench IPs, device IDs, and demo-key hints.
///
/// Default **on**. Set `OPENFDD_FIELDBUS_SWAGGER_BENCH=0` to disable.
pub fn swagger_bench_enabled() -> bool {
    if let Ok(v) = std::env::var("OPENFDD_FIELDBUS_SWAGGER_BENCH") {
        let t = v.trim().to_ascii_lowercase();
        return !matches!(t.as_str(), "0" | "false" | "no" | "off");
    }
    true
}

/// Whether OpenAPI text may include the literal demo API key hint.
pub fn swagger_may_reveal_demo_key() -> bool {
    swagger_bench_enabled()
}

// --- Bench examples (192.168.204.x test hardware) ---

pub fn bacnet_read_bench() -> Value {
    json!({
        "device_instance": 5007,
        "object_type": "analog-input",
        "object_instance": 1173,
        "property_id": "present-value"
    })
}

pub fn bacnet_rpm_bench() -> Value {
    json!({
        "device_instance": 5007,
        "objects": [{
            "object_type": "analog-input",
            "object_instance": 1173,
            "properties": [{ "property_id": "present-value" }]
        }, {
            "object_type": "analog-output",
            "object_instance": 2466,
            "properties": [{ "property_id": "present-value" }]
        }]
    })
}

pub fn bacnet_whois_bench() -> Value {
    json!({})
}

pub fn bacnet_write_bench() -> Value {
    json!({
        "device_instance": 5007,
        "object_type": "analog-output",
        "object_instance": 2466,
        "property_id": "present-value",
        "value": 42.0,
        "priority": 10,
        "approved": true
    })
}

#[allow(dead_code)]
pub fn bacnet_write_dry_run_bench() -> Value {
    json!({
        "device_instance": 5007,
        "object_type": "analog-output",
        "object_instance": 2466,
        "property_id": "present-value",
        "value": null,
        "priority": 10,
        "approved": false
    })
}

pub fn bacnet_discover_bench() -> Value {
    json!({ "device_instance": 5007 })
}

pub fn bacnet_priority_array_bench() -> Value {
    json!({
        "device_instance": 5007,
        "object_type": "analog-output",
        "object_instance": 2466
    })
}

pub fn bacnet_server_update_bench() -> Value {
    json!({
        "updates": {
            "openfdd-active-fault-count": 0.0,
            "outside-air-temperature": 72.0
        }
    })
}

pub fn modbus_read_bench() -> Value {
    json!({
        "host": "192.168.204.14",
        "port": 1502,
        "unit_id": 1,
        "timeout": 5.0,
        "registers": [{
            "address": 0,
            "count": 1,
            "function": "input",
            "decode": "uint16",
            "label": "bench-reg-0"
        }]
    })
}

pub fn haystack_read_bench() -> Value {
    json!({ "filter": "point and temp" })
}

pub fn haystack_nav_bench() -> Value {
    json!({ "nav_id": null })
}

pub fn haystack_his_read_bench() -> Value {
    json!({
        "ids": ["@demo:point"],
        "range_start": "yesterday",
        "range_end": "today"
    })
}

// --- Generic examples (no internal IPs or bench device IDs) ---

pub fn bacnet_read_generic() -> Value {
    json!({
        "device_instance": 1001,
        "object_type": "analog-input",
        "object_instance": 1,
        "property_id": "present-value"
    })
}

pub fn bacnet_rpm_generic() -> Value {
    json!({
        "device_instance": 1001,
        "objects": [{
            "object_type": "analog-input",
            "object_instance": 1,
            "properties": [{ "property_id": "present-value" }]
        }]
    })
}

/// Empty body → defaults scan all BACnet device instances (0–4194303).
pub fn bacnet_whois_generic() -> Value {
    json!({})
}

pub fn bacnet_write_generic() -> Value {
    json!({
        "device_instance": 1001,
        "object_type": "analog-output",
        "object_instance": 1,
        "property_id": "present-value",
        "value": 0.0,
        "priority": 16,
        "approved": true
    })
}

pub fn bacnet_discover_generic() -> Value {
    json!({ "device_instance": 1001 })
}

pub fn bacnet_priority_array_generic() -> Value {
    json!({
        "device_instance": 1001,
        "object_type": "analog-output",
        "object_instance": 1
    })
}

pub fn bacnet_server_update_generic() -> Value {
    json!({
        "updates": {
            "outside-air-temperature": 72.0
        }
    })
}

pub fn modbus_read_generic() -> Value {
    json!({
        "host": "modbus-host.example",
        "port": 502,
        "unit_id": 1,
        "timeout": 5.0,
        "registers": [{
            "address": 0,
            "count": 1,
            "function": "holding",
            "decode": "uint16"
        }]
    })
}

pub fn haystack_read_generic() -> Value {
    json!({ "filter": "point" })
}

pub fn haystack_nav_generic() -> Value {
    json!({ "nav_id": null })
}

pub fn haystack_his_read_generic() -> Value {
    json!({
        "ids": ["@pointRef"],
        "range_start": "yesterday",
        "range_end": "today"
    })
}

/// Patch component schemas so Swagger UI pre-fills Try-it-out bodies.
pub fn apply_swagger_examples(openapi: &mut OpenApi) {
    if swagger_bench_enabled() {
        apply_examples(openapi, true);
    } else {
        apply_examples(openapi, false);
    }
}

fn apply_examples(openapi: &mut OpenApi, bench: bool) {
    let Some(components) = openapi.components.as_mut() else {
        return;
    };

    let (read, rpm, whois, write, prio, discover, server_upd, modbus, hs_read, hs_nav, hs_his) =
        if bench {
            (
                bacnet_read_bench(),
                bacnet_rpm_bench(),
                bacnet_whois_bench(),
                bacnet_write_bench(),
                bacnet_priority_array_bench(),
                bacnet_discover_bench(),
                bacnet_server_update_bench(),
                modbus_read_bench(),
                haystack_read_bench(),
                haystack_nav_bench(),
                haystack_his_read_bench(),
            )
        } else {
            (
                bacnet_read_generic(),
                bacnet_rpm_generic(),
                bacnet_whois_generic(),
                bacnet_write_generic(),
                bacnet_priority_array_generic(),
                bacnet_discover_generic(),
                bacnet_server_update_generic(),
                modbus_read_generic(),
                haystack_read_generic(),
                haystack_nav_generic(),
                haystack_his_read_generic(),
            )
        };

    set_schema_example(&mut components.schemas, "BacnetReadRequest", read);
    set_schema_example(&mut components.schemas, "BacnetRpmRequest", rpm);
    set_schema_example(&mut components.schemas, "BacnetWhoisRequest", whois);
    set_schema_example(&mut components.schemas, "BacnetWriteRequest", write);
    set_schema_example(&mut components.schemas, "BacnetObjectRef", prio);
    set_schema_example(&mut components.schemas, "DeviceInstanceRequest", discover);
    set_schema_example(
        &mut components.schemas,
        "ServerUpdatePointsRequest",
        server_upd,
    );
    set_schema_example(&mut components.schemas, "ModbusReadRequest", modbus);
    set_schema_example(&mut components.schemas, "HaystackReadRequest", hs_read);
    set_schema_example(&mut components.schemas, "HaystackNavRequest", hs_nav);
    set_schema_example(&mut components.schemas, "HaystackHisReadRequest", hs_his);
}

fn set_schema_example(schemas: &mut BTreeMap<String, RefOr<Schema>>, name: &str, example: Value) {
    let Some(RefOr::T(Schema::Object(obj))) = schemas.get_mut(name) else {
        return;
    };
    obj.example = Some(example);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::openapi::ApiDoc;
    use utoipa::openapi::Object;
    use utoipa::OpenApi;

    fn with_env(key: &str, value: Option<&str>, f: impl FnOnce()) {
        let prev = std::env::var(key).ok();
        match value {
            Some(v) => std::env::set_var(key, v),
            None => std::env::remove_var(key),
        }
        f();
        match prev {
            Some(v) => std::env::set_var(key, v),
            None => std::env::remove_var(key),
        }
    }

    #[test]
    fn bench_examples_use_device_5007() {
        let mut doc = ApiDoc::openapi();
        apply_examples(&mut doc, true);
        let schemas = doc.components.as_ref().unwrap();
        let read = schemas.schemas.get("BacnetReadRequest").unwrap();
        if let RefOr::T(Schema::Object(Object {
            example: Some(ex), ..
        })) = read
        {
            assert_eq!(ex["device_instance"], 5007);
        } else {
            panic!("missing BacnetReadRequest example");
        }
    }

    #[test]
    fn generic_whois_example_is_empty_object() {
        assert!(bacnet_whois_generic().as_object().unwrap().is_empty());
    }

    #[test]
    fn generic_modbus_uses_placeholder_host() {
        let ex = modbus_read_generic();
        assert_eq!(ex["host"], "modbus-host.example");
    }

    #[test]
    fn swagger_bench_on_by_default() {
        with_env("OPENFDD_FIELDBUS_SWAGGER_BENCH", None, || {
            assert!(swagger_bench_enabled());
        });
    }

    #[test]
    fn swagger_bench_forced_off_with_env() {
        with_env("OPENFDD_FIELDBUS_SWAGGER_BENCH", Some("0"), || {
            assert!(!swagger_bench_enabled());
        });
    }

    #[test]
    fn demo_key_revealed_when_bench_on() {
        with_env("OPENFDD_FIELDBUS_SWAGGER_BENCH", Some("1"), || {
            assert!(swagger_may_reveal_demo_key());
        });
    }
}
