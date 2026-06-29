//! Machine-readable ingest contract for AI agents (GET /api/ingest/contract).

use crate::csv_ingest::parse::{MAX_ROWS, MAX_UPLOAD_BYTES};
use crate::fdd::execution;
use serde_json::{json, Value};

pub fn contract_json() -> Value {
    json!({
        "ok": true,
        "version": 1,
        "contract_id": "openfdd-ingest-v1",
        "dialect": "DataFusion",
        "timestamp_storage": {
            "wire_format": "RFC3339 preferred",
            "arrow_type": "Timestamp(Millisecond, None)",
            "historian_file": "telemetry_pivot.jsonl",
            "naive_local_ok": true,
            "note": "Prefer naive local timestamps + IANA timezone in import plan; RFC3339 with offset is preserved as UTC without re-localization"
        },
        "limits": {
            "max_upload_bytes": MAX_UPLOAD_BYTES,
            "max_rows": MAX_ROWS
        },
        "profiles": {
            "historian_wide_csv": historian_wide_csv_profile(),
            "import_plan": import_plan_profile(),
            "commissioning_bundle": commissioning_bundle_profile()
        },
        "agent_workflow": [
            "GET /api/ingest/contract",
            "Clean data in workspace/agent-toolshed/ (not committed to repo)",
            "POST /api/csv/import/preview",
            "POST /api/csv/import/plan",
            "POST /api/csv/import/preflight — must verdict pass before execute",
            "POST /api/csv/import/execute with confirm:true",
            "Optional POST /api/model/commissioning-import",
            "POST /api/fdd-rules/{id}/test-sql then POST /api/rules/batch",
            "POST /api/reports/from-fdd-sql-run"
        ],
        "fdd_inputs": execution::fdd_inputs_json().get("fdd_inputs").cloned().unwrap_or(json!([])),
        "allowed_sql_tables": ["telemetry", "telemetry_pivot", "hvac"]
    })
}

fn historian_wide_csv_profile() -> Value {
    json!({
        "description": "Wide pivoted time-series CSV ready for historian after agent cleaning",
        "required_columns": ["timestamp"],
        "recommended_columns": ["equipment_id", "site_id"],
        "fdd_value_columns": [
            "oa_t", "oa_h", "sat", "duct_t", "zn_t", "sat_sp", "fan_cmd", "occ", "kw"
        ],
        "equipment_id_format": "equip:<slug> e.g. equip:liberty-100-ahu-1",
        "site_id_format": "site:<slug>",
        "import_plan_mode": "single or append or join",
        "example_mapping": {
            "point_role_outside_air_temp": "oa_t",
            "point_role_zone_temp": "zn_t",
            "point_role_discharge_air_temp": "duct_t",
            "point_role_cooling_setpoint": "sat_sp"
        }
    })
}

fn import_plan_profile() -> Value {
    json!({
        "fields": {
            "mode": "single | append | join",
            "output_dataset_name": "string slug",
            "ambiguous_policy": "first | second",
            "fill_policy": "none | forward | backward | linear | constant | acknowledge_only",
            "join_alignment": "exact | floor_hour | asof_previous | resample_weather_15m | resample_kw_hourly",
            "files": [{
                "filename": "string",
                "timestamp_column": "string header name",
                "timezone": "IANA e.g. America/Chicago or UTC",
                "value_columns": ["numeric column headers"]
            }]
        }
    })
}

fn commissioning_bundle_profile() -> Value {
    json!({
        "description": "Haystack grid + FDD assignments import",
        "payload_shape": {
            "sites": [{"id": "site:…", "dis": "…", "site": "M"}],
            "equipment": [{"id": "equip:…", "site_id": "site:…", "equip": "M"}],
            "points": [{"id": "point:…", "equip_ref": "equip:…", "fdd_input": "oa_t"}],
            "assignments": [{"haystack_id": "…", "equip_ref": "…", "fdd_input": "…", "fdd_rule_ids": []}],
            "fdd_rules": [{"rule_id": "…", "name": "…", "sql": "SELECT … fault_raw …", "review_status": "approved"}]
        },
        "endpoint": "POST /api/model/commissioning-import"
    })
}
