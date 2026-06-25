//! DataFusion SQL execution against Arrow telemetry tables.

use crate::fdd::confirmation;
use crate::fdd::sql_safety;
use crate::historian::{arrow_table, store};
use arrow::array::{BooleanArray, Float64Array, StringArray, TimestampMillisecondArray};
use arrow::datatypes::{DataType, Field, Schema, TimeUnit};
use arrow::record_batch::RecordBatch;
use chrono::{DateTime, Utc};
use datafusion::prelude::*;
use serde_json::{json, Value};
use std::sync::Arc;

pub fn schema_tables_json() -> Value {
    json!({
        "ok": true,
        "tables": [
            {
                "name": "telemetry",
                "description": "Normalized long-format telemetry rows",
                "columns": ["timestamp","site_id","building_id","equipment_id","point_id","fdd_input","value","unit","quality","source","source_driver","source_device","source_object","is_simulated"]
            },
            {
                "name": "telemetry_pivot",
                "description": "Wide pivoted view for rule SQL",
                "columns": ["timestamp","equipment_id","oa_t","oa_h","sat","duct_t","zn_t","sat_sp","fan_cmd","occ"]
            },
            {
                "name": "hvac",
                "description": "Legacy HVAC demo table",
                "columns": ["ts","equip","sat","sat_sp","duct_static","duct_static_sp","oat","fan_cmd"]
            }
        ]
    })
}

pub fn fdd_inputs_json() -> Value {
    json!({
        "ok": true,
        "fdd_inputs": [
            {"id":"oa_t","label":"Outside Air Temp","unit":"degF","equipment_types":["ahu","bench"]},
            {"id":"oa_h","label":"Outside Air Humidity","unit":"%RH","equipment_types":["ahu"]},
            {"id":"sat","label":"Supply Air Temp","unit":"degF","equipment_types":["ahu","vav"]},
            {"id":"duct_t","label":"Discharge/Duct Temp","unit":"degF","equipment_types":["ahu","vav"]},
            {"id":"zn_t","label":"Zone Temp","unit":"degF","equipment_types":["vav","zone"]},
            {"id":"sat_sp","label":"SAT Setpoint","unit":"degF","equipment_types":["ahu"]},
            {"id":"fan_cmd","label":"Fan Command","unit":"bool","equipment_types":["ahu"]},
            {"id":"occ","label":"Occupancy","unit":"bool","equipment_types":["ahu","zone"]}
        ]
    })
}

pub fn equipment_types_json() -> Value {
    json!({
        "ok": true,
        "equipment_types": [
            {"id":"ahu","label":"Air Handling Unit"},
            {"id":"vav","label":"VAV Box"},
            {"id":"bench","label":"Validation Controller"},
            {"id":"plant","label":"Central Plant"}
        ]
    })
}

pub fn run_rule_sql_from_historian(sql: &str, confirmation_seconds: i64, params: &Value) -> Value {
    if !sql_safety::is_sql_safe(sql) {
        return json!({
            "ok": false,
            "error": "unsafe SQL rejected",
            "validation": sql_safety::validate_sql(sql)
        });
    }

    let bound = bind_params(sql, params);
    let rt = tokio::runtime::Runtime::new().expect("tokio runtime");
    match rt.block_on(execute_query_from_historian(&bound)) {
        Ok(rows) => {
            let confirmation = confirmation::apply_confirmation(&rows, confirmation_seconds);
            json!({
                "ok": true,
                "sql": bound,
                "row_count": rows.len(),
                "rows": rows,
                "confirmation": confirmation,
                "engine": "Apache Arrow + DataFusion SQL (Rust)",
                "historian": store::bench_dir().display().to_string()
            })
        }
        Err(err) => json!({"ok": false, "error": err}),
    }
}

pub fn run_rule_sql(sql: &str, confirmation_seconds: i64, params: &Value) -> Value {
    if !sql_safety::is_sql_safe(sql) {
        return json!({
            "ok": false,
            "error": "unsafe SQL rejected",
            "validation": sql_safety::validate_sql(sql)
        });
    }

    let bound = bind_params(sql, params);
    let rt = tokio::runtime::Runtime::new().expect("tokio runtime");
    match rt.block_on(execute_query(&bound)) {
        Ok(rows) => {
            let confirmation = confirmation::apply_confirmation(&rows, confirmation_seconds);
            json!({
                "ok": true,
                "sql": bound,
                "row_count": rows.len(),
                "rows": rows,
                "confirmation": confirmation,
                "engine": "Apache Arrow + DataFusion SQL (Rust)"
            })
        }
        Err(err) => json!({"ok": false, "error": err}),
    }
}

fn bind_params(sql: &str, params: &Value) -> String {
    let mut out = sql.to_string();
    if let Some(map) = params.as_object() {
        for (k, v) in map {
            let placeholder = format!("${{{k}}}");
            let replacement = match v {
                Value::String(s) => format!("'{s}'"),
                Value::Number(n) => n.to_string(),
                Value::Bool(b) => b.to_string(),
                _ => v.to_string(),
            };
            out = out.replace(&placeholder, &replacement);
        }
    }
    out
}

async fn execute_query_from_historian(sql: &str) -> Result<Vec<Value>, String> {
    let ctx = SessionContext::new();
    register_historian_tables(&ctx).await?;
    let df = ctx.sql(sql).await.map_err(|e| e.to_string())?;
    let batches = df.collect().await.map_err(|e| e.to_string())?;
    let mut rows = Vec::new();
    for batch in batches {
        rows.extend(batch_to_json_rows(&batch)?);
    }
    Ok(rows)
}

async fn execute_query(sql: &str) -> Result<Vec<Value>, String> {
    let ctx = SessionContext::new();
    register_demo_tables(&ctx).await?;
    let df = ctx.sql(sql).await.map_err(|e| e.to_string())?;
    let batches = df.collect().await.map_err(|e| e.to_string())?;
    let mut rows = Vec::new();
    for batch in batches {
        rows.extend(batch_to_json_rows(&batch)?);
    }
    Ok(rows)
}

async fn register_historian_tables(ctx: &SessionContext) -> Result<(), String> {
    let pivot_rows = store::load_pivot_rows()?;
    if pivot_rows.is_empty() {
        return Err("historian has no rows — capture bench samples first".into());
    }
    let pivot = store::pivot_rows_to_batch(&pivot_rows).map_err(|e| e.to_string())?;
    let telemetry = historian_pivot_to_telemetry_batch(&pivot_rows).map_err(|e| e.to_string())?;
    let hvac = build_hvac_batch().map_err(|e| e.to_string())?;
    ctx.register_batch("telemetry_pivot", pivot)
        .map_err(|e| e.to_string())?;
    ctx.register_batch("telemetry", telemetry)
        .map_err(|e| e.to_string())?;
    ctx.register_batch("hvac", hvac)
        .map_err(|e| e.to_string())?;
    Ok(())
}

async fn register_demo_tables(ctx: &SessionContext) -> Result<(), String> {
    let telemetry = build_telemetry_batch().map_err(|e| e.to_string())?;
    let pivot = build_pivot_batch().map_err(|e| e.to_string())?;
    let hvac = build_hvac_batch().map_err(|e| e.to_string())?;
    ctx.register_batch("telemetry", telemetry)
        .map_err(|e| e.to_string())?;
    ctx.register_batch("telemetry_pivot", pivot)
        .map_err(|e| e.to_string())?;
    ctx.register_batch("hvac", hvac)
        .map_err(|e| e.to_string())?;
    Ok(())
}

fn historian_pivot_to_telemetry_batch(
    rows: &[Value],
) -> Result<RecordBatch, arrow::error::ArrowError> {
    let schema = Schema::new(vec![
        Field::new(
            "timestamp",
            DataType::Timestamp(TimeUnit::Millisecond, None),
            false,
        ),
        Field::new("site_id", DataType::Utf8, false),
        Field::new("building_id", DataType::Utf8, false),
        Field::new("equipment_id", DataType::Utf8, false),
        Field::new("point_id", DataType::Utf8, false),
        Field::new("fdd_input", DataType::Utf8, false),
        Field::new("value", DataType::Float64, true),
        Field::new("unit", DataType::Utf8, false),
        Field::new("quality", DataType::Utf8, false),
        Field::new("source", DataType::Utf8, false),
        Field::new("source_driver", DataType::Utf8, false),
        Field::new("source_device", DataType::Utf8, false),
        Field::new("source_object", DataType::Utf8, false),
        Field::new("is_simulated", DataType::Boolean, false),
    ]);
    let mut ts = Vec::new();
    let mut equipment = Vec::new();
    let mut fdd_input = Vec::new();
    let mut value = Vec::new();
    let mut source = Vec::new();
    let mut driver = Vec::new();
    let mut simulated = Vec::new();
    for row in rows {
        let ts_ms = store::parse_ts_ms(row.get("timestamp").and_then(|v| v.as_str()).unwrap_or(""));
        let equip = row
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or("equip:validation")
            .to_string();
        let src = row
            .get("source")
            .and_then(|v| v.as_str())
            .unwrap_or("historian")
            .to_string();
        let sim = row
            .get("is_simulated")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        for (input, key) in [
            ("oa_t", "oa_t"),
            ("oa_h", "oa_h"),
            ("duct_t", "duct_t"),
            ("zn_t", "zn_t"),
        ] {
            if row.get(key).and_then(|v| v.as_f64()).is_some() {
                ts.push(ts_ms);
                equipment.push(equip.clone());
                fdd_input.push(input.to_string());
                value.push(row.get(key).and_then(|v| v.as_f64()));
                source.push(src.clone());
                driver.push(
                    row.get("source_driver")
                        .and_then(|v| v.as_str())
                        .unwrap_or("bacnet")
                        .to_string(),
                );
                simulated.push(sim);
            }
        }
    }
    let n = ts.len();
    let site: StringArray = std::iter::repeat("site:demo")
        .take(n)
        .collect::<Vec<_>>()
        .into();
    let building: StringArray = std::iter::repeat("building:main")
        .take(n)
        .collect::<Vec<_>>()
        .into();
    let point: StringArray = std::iter::repeat("point:bench")
        .take(n)
        .collect::<Vec<_>>()
        .into();
    let unit: StringArray = std::iter::repeat("degF").take(n).collect::<Vec<_>>().into();
    let quality: StringArray = std::iter::repeat("good").take(n).collect::<Vec<_>>().into();
    let device: StringArray = std::iter::repeat("equip:validation")
        .take(n)
        .collect::<Vec<_>>()
        .into();
    let object: StringArray = std::iter::repeat("ai:bench")
        .take(n)
        .collect::<Vec<_>>()
        .into();
    RecordBatch::try_new(
        Arc::new(schema),
        vec![
            Arc::new(TimestampMillisecondArray::from(ts)),
            Arc::new(site),
            Arc::new(building),
            Arc::new(StringArray::from(equipment)),
            Arc::new(point),
            Arc::new(StringArray::from(fdd_input)),
            Arc::new(Float64Array::from(value)),
            Arc::new(unit),
            Arc::new(quality),
            Arc::new(StringArray::from(source)),
            Arc::new(StringArray::from(driver)),
            Arc::new(device),
            Arc::new(object),
            Arc::new(BooleanArray::from(simulated)),
        ],
    )
}

fn build_hvac_batch() -> Result<RecordBatch, arrow::error::ArrowError> {
    let rows: Vec<Value> = serde_json::from_str(arrow_table::demo_rows_json()).unwrap_or_default();
    let schema = Schema::new(vec![
        Field::new("ts", DataType::Utf8, false),
        Field::new("equip", DataType::Utf8, false),
        Field::new("sat", DataType::Float64, true),
        Field::new("sat_sp", DataType::Float64, true),
        Field::new("duct_static", DataType::Float64, true),
        Field::new("duct_static_sp", DataType::Float64, true),
        Field::new("oat", DataType::Float64, true),
        Field::new("fan_cmd", DataType::Float64, true),
    ]);
    let ts: StringArray = rows
        .iter()
        .map(|r| r.get("ts").and_then(|v| v.as_str()).unwrap_or(""))
        .collect::<Vec<_>>()
        .into();
    let equip: StringArray = rows
        .iter()
        .map(|r| r.get("equip").and_then(|v| v.as_str()).unwrap_or(""))
        .collect::<Vec<_>>()
        .into();
    let f64 = |key: &str| -> Float64Array {
        rows.iter()
            .map(|r| r.get(key).and_then(|v| v.as_f64()))
            .collect::<Float64Array>()
    };
    RecordBatch::try_new(
        Arc::new(schema),
        vec![
            Arc::new(ts),
            Arc::new(equip),
            Arc::new(f64("sat")),
            Arc::new(f64("sat_sp")),
            Arc::new(f64("duct_static")),
            Arc::new(f64("duct_static_sp")),
            Arc::new(f64("oat")),
            Arc::new(f64("fan_cmd")),
        ],
    )
}

fn build_telemetry_batch() -> Result<RecordBatch, arrow::error::ArrowError> {
    let rows: Vec<Value> = serde_json::from_str(arrow_table::demo_rows_json()).unwrap_or_default();
    let schema = Schema::new(vec![
        Field::new(
            "timestamp",
            DataType::Timestamp(TimeUnit::Millisecond, None),
            false,
        ),
        Field::new("site_id", DataType::Utf8, false),
        Field::new("building_id", DataType::Utf8, false),
        Field::new("equipment_id", DataType::Utf8, false),
        Field::new("point_id", DataType::Utf8, false),
        Field::new("fdd_input", DataType::Utf8, false),
        Field::new("value", DataType::Float64, true),
        Field::new("unit", DataType::Utf8, false),
        Field::new("quality", DataType::Utf8, false),
        Field::new("source", DataType::Utf8, false),
        Field::new("source_driver", DataType::Utf8, false),
        Field::new("source_device", DataType::Utf8, false),
        Field::new("source_object", DataType::Utf8, false),
        Field::new("is_simulated", DataType::Boolean, false),
    ]);
    let mut ts = Vec::new();
    let mut equipment = Vec::new();
    let mut fdd_input = Vec::new();
    let mut value = Vec::new();
    for row in &rows {
        let t = row.get("ts").and_then(|v| v.as_str()).unwrap_or("");
        let ts_ms = parse_ts_ms(t);
        let equip = row
            .get("equip")
            .and_then(|v| v.as_str())
            .unwrap_or("equip:validation")
            .to_string();
        for (input, key) in [
            ("sat", "sat"),
            ("sat_sp", "sat_sp"),
            ("fan_cmd", "fan_cmd"),
            ("oat", "oa_t"),
        ] {
            ts.push(ts_ms);
            equipment.push(equip.clone());
            fdd_input.push(input.to_string());
            value.push(row.get(key).and_then(|v| v.as_f64()));
        }
    }
    let n = ts.len();
    let site: StringArray = std::iter::repeat("site:demo")
        .take(n)
        .collect::<Vec<_>>()
        .into();
    let building: StringArray = std::iter::repeat("building:main")
        .take(n)
        .collect::<Vec<_>>()
        .into();
    let equip_arr: StringArray = equipment.into();
    let point: StringArray = std::iter::repeat("point:demo")
        .take(n)
        .collect::<Vec<_>>()
        .into();
    let fdd_arr: StringArray = fdd_input.into();
    let val_arr: Float64Array = value.into();
    let unit: StringArray = std::iter::repeat("degF").take(n).collect::<Vec<_>>().into();
    let quality: StringArray = std::iter::repeat("good").take(n).collect::<Vec<_>>().into();
    let source: StringArray = std::iter::repeat("simulated")
        .take(n)
        .collect::<Vec<_>>()
        .into();
    let driver: StringArray = std::iter::repeat("bacnet")
        .take(n)
        .collect::<Vec<_>>()
        .into();
    let device: StringArray = std::iter::repeat("equip:validation")
        .take(n)
        .collect::<Vec<_>>()
        .into();
    let object: StringArray = std::iter::repeat("ai:1001")
        .take(n)
        .collect::<Vec<_>>()
        .into();
    let simulated = BooleanArray::from(vec![true; n]);
    let ts_arr = TimestampMillisecondArray::from(ts);
    RecordBatch::try_new(
        Arc::new(schema),
        vec![
            Arc::new(ts_arr),
            Arc::new(site),
            Arc::new(building),
            Arc::new(equip_arr),
            Arc::new(point),
            Arc::new(fdd_arr),
            Arc::new(val_arr),
            Arc::new(unit),
            Arc::new(quality),
            Arc::new(source),
            Arc::new(driver),
            Arc::new(device),
            Arc::new(object),
            Arc::new(simulated),
        ],
    )
}

fn build_pivot_batch() -> Result<RecordBatch, arrow::error::ArrowError> {
    let rows: Vec<Value> = serde_json::from_str(arrow_table::demo_rows_json()).unwrap_or_default();
    let schema = Schema::new(vec![
        Field::new(
            "timestamp",
            DataType::Timestamp(TimeUnit::Millisecond, None),
            false,
        ),
        Field::new("equipment_id", DataType::Utf8, false),
        Field::new("oa_t", DataType::Float64, true),
        Field::new("oa_h", DataType::Float64, true),
        Field::new("sat", DataType::Float64, true),
        Field::new("duct_t", DataType::Float64, true),
        Field::new("zn_t", DataType::Float64, true),
        Field::new("sat_sp", DataType::Float64, true),
        Field::new("fan_cmd", DataType::Float64, true),
        Field::new("occ", DataType::Float64, true),
    ]);
    let mut ts = Vec::new();
    let mut equip = Vec::new();
    let mut sat = Vec::new();
    let mut sat_sp = Vec::new();
    let mut fan = Vec::new();
    let mut oat = Vec::new();
    for row in &rows {
        ts.push(parse_ts_ms(
            row.get("ts").and_then(|v| v.as_str()).unwrap_or(""),
        ));
        equip.push(
            row.get("equip")
                .and_then(|v| v.as_str())
                .unwrap_or("equip:validation")
                .to_string(),
        );
        sat.push(row.get("sat").and_then(|v| v.as_f64()));
        sat_sp.push(row.get("sat_sp").and_then(|v| v.as_f64()));
        fan.push(row.get("fan_cmd").and_then(|v| v.as_f64()));
        oat.push(row.get("oat").and_then(|v| v.as_f64()));
    }
    RecordBatch::try_new(
        Arc::new(schema),
        vec![
            Arc::new(TimestampMillisecondArray::from(ts)),
            Arc::new(StringArray::from(equip)),
            Arc::new(Float64Array::from(oat)),
            Arc::new(Float64Array::from(vec![None; rows.len()])),
            Arc::new(Float64Array::from(sat)),
            Arc::new(Float64Array::from(vec![None; rows.len()])),
            Arc::new(Float64Array::from(vec![None; rows.len()])),
            Arc::new(Float64Array::from(sat_sp)),
            Arc::new(Float64Array::from(fan)),
            Arc::new(Float64Array::from(vec![Some(1.0); rows.len()])),
        ],
    )
}

fn parse_ts_ms(s: &str) -> i64 {
    DateTime::parse_from_rfc3339(s)
        .map(|dt| dt.with_timezone(&Utc).timestamp_millis())
        .unwrap_or(0)
}

fn batch_to_json_rows(batch: &RecordBatch) -> Result<Vec<Value>, String> {
    let mut out = Vec::new();
    for row_idx in 0..batch.num_rows() {
        let mut obj = serde_json::Map::new();
        for (col_idx, field) in batch.schema().fields().iter().enumerate() {
            let col = batch.column(col_idx);
            let val = json_cell(col, row_idx, field.data_type());
            obj.insert(field.name().clone(), val);
        }
        out.push(Value::Object(obj));
    }
    Ok(out)
}

fn json_cell(col: &Arc<dyn arrow::array::Array>, idx: usize, dtype: &DataType) -> Value {
    if col.is_null(idx) {
        return Value::Null;
    }
    match dtype {
        DataType::Utf8 => {
            let arr = col.as_any().downcast_ref::<StringArray>().unwrap();
            json!(arr.value(idx))
        }
        DataType::Float64 => {
            let arr = col.as_any().downcast_ref::<Float64Array>().unwrap();
            json!(arr.value(idx))
        }
        DataType::Boolean => {
            let arr = col.as_any().downcast_ref::<BooleanArray>().unwrap();
            json!(arr.value(idx))
        }
        DataType::Timestamp(_, _) => {
            let arr = col
                .as_any()
                .downcast_ref::<TimestampMillisecondArray>()
                .unwrap();
            let ms = arr.value(idx);
            let dt = DateTime::<Utc>::from_timestamp_millis(ms).unwrap_or_else(Utc::now);
            json!(dt.to_rfc3339())
        }
        _ => json!(null),
    }
}

pub fn builder_to_sql(builder: &Value) -> String {
    let input = builder
        .get("input")
        .and_then(|v| v.as_str())
        .unwrap_or("oa_t");
    let op = builder
        .get("operator")
        .and_then(|v| v.as_str())
        .unwrap_or(">");
    let value = builder
        .get("value")
        .and_then(|v| v.as_f64())
        .unwrap_or(100.0);
    let equipment = builder
        .get("equipment_id")
        .and_then(|v| v.as_str())
        .unwrap_or("equip:validation");
    format!(
        "SELECT timestamp, equipment_id, {input}, CASE WHEN {input} IS NULL THEN false WHEN {input} {op} {value} THEN true ELSE false END AS fault_raw FROM telemetry_pivot WHERE equipment_id = '{equipment}'"
    )
}
