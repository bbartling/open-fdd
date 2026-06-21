//! BACnet driver facade.
//!
//! Production direction:
//! - use `rusty-bacnet` for Who-Is/I-Am, ReadProperty, ReadPropertyMultiple,
//!   WriteProperty with priority, and priority-array override scan.
//! - persist device/point registry under `workspace/data/drivers/bacnet/`.
//! - expose the registry through `/api/bacnet/driver/tree`.
//!
//! The prototype returns deterministic JSON so API agents and UI workflows are
//! fully testable without a BACnet network.

pub const DEVICES_JSON: &str = r#"[
  {"object_identifier":{"type":"device","instance":1001},"vendor_id":5,"address":"192.168.1.100:47808","label":"AHU-1 Controller","protocol":"BACnet/IP"},
  {"object_identifier":{"type":"device","instance":2002},"vendor_id":359,"address":"192.168.1.101:47808","label":"VAV Floor 2 Router","protocol":"BACnet/IP"}
]"#;

pub const POINTS_JSON: &str = r#"[
  {"mac":"c0a80164bac0","object_id":[0,1],"name":"AHU-1 SAT","kind":"sensor","unit":"°F","writable":false,"value":55.2},
  {"mac":"c0a80164bac0","object_id":[2,4],"name":"AHU-1 SAT Setpoint","kind":"setpoint","unit":"°F","writable":true,"value":55.0},
  {"mac":"c0a80164bac0","object_id":[5,8],"name":"AHU-1 Fan Command","kind":"cmd","unit":"bool","writable":true,"value":1}
]"#;

pub const DRIVER_TREE_JSON: &str = r#"{
  "site_id":"demo",
  "building_id":"rust-edge-demo",
  "drivers":[
    {
      "id":"bacnet-ip",
      "label":"BACnet/IP",
      "status":"online",
      "devices":[
        {
          "device_instance":1001,
          "name":"AHU-1 Controller",
          "address":"192.168.1.100:47808",
          "polling_enabled":true,
          "points":[
            {"id":"bacnet:1001:analog-input:1","object_id":[0,1],"name":"AHU-1 SAT","polling_enabled":true,"writable":false,"haystack_id":"point:sat"},
            {"id":"bacnet:1001:analog-value:4","object_id":[2,4],"name":"AHU-1 SAT Setpoint","polling_enabled":true,"writable":true,"haystack_id":"point:sat-sp"},
            {"id":"bacnet:1001:binary-value:8","object_id":[5,8],"name":"AHU-1 Fan Command","polling_enabled":true,"writable":true,"haystack_id":"point:fan-cmd"}
          ]
        }
      ]
    }
  ]
}"#;

pub const OVERRIDES_JSON: &str = r#"{
  "last_scan":"2026-06-21T00:20:00Z",
  "cadence":"hourly",
  "method":"ReadProperty(priority-array) for writable points",
  "overrides":[
    {"point":"AHU-1 SAT Setpoint","priority":8,"level":"operator","value":58.0,"age_minutes":143},
    {"point":"AHU-1 Fan Command","priority":5,"level":"supervisory","value":1,"age_minutes":58}
  ]
}"#;

pub fn whois_json() -> &'static str {
    DEVICES_JSON
}

pub fn points_json() -> &'static str {
    POINTS_JSON
}

pub fn driver_tree_json() -> &'static str {
    DRIVER_TREE_JSON
}

pub fn overrides_json() -> &'static str {
    OVERRIDES_JSON
}

pub fn read_present_value_json() -> &'static str {
    r#"{"point":"AHU-1 SAT","value":55.2,"unit":"°F","source":"bacnet-prototype"}"#
}

pub fn write_dry_run_json() -> &'static str {
    r#"{"ok":true,"dry_run":true,"safety":"BACnet write requires integrator JWT and approved=true; prototype never writes to the field bus"}"#
}

pub fn poll_status_json() -> &'static str {
    r#"{"ok":true,"driver":"bacnet","polling_enabled":true,"poll_interval_s":60,"points_polled":3,"last_poll":"2026-06-21T00:20:00Z","errors":0}"#
}

pub fn commission_status_json() -> &'static str {
    r#"{"ok":true,"driver":"bacnet","commissioning":"ready","whois_available":true,"read_property_available":true,"priority_array_scan_available":true}"#
}
