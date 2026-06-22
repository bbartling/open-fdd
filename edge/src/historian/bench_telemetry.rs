//! Bench 5007 telemetry stored as Apache Arrow RecordBatches.

use arrow::array::{
    Float64Array, RecordBatch, StringArray, TimestampMicrosecondArray, UInt32Array, UInt64Array,
};
use arrow::datatypes::{DataType, Field, Schema, TimeUnit};
use chrono::{DateTime, Utc};
use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};

#[derive(Clone, Debug)]
pub struct TelemetrySample {
    pub ts: DateTime<Utc>,
    pub device_instance: u32,
    pub oa_t: Option<f64>,
    pub oa_h: Option<f64>,
    pub duct_t: Option<f64>,
    pub stat_zn_t: Option<f64>,
    pub source: String,
    pub poll_cycle_id: u64,
}

pub fn fdd_input_to_column(input: &str) -> Option<&'static str> {
    match input {
        "oa-t" => Some("oa_t"),
        "oa-h" => Some("oa_h"),
        "duct-t" => Some("duct_t"),
        "stat_zn-t" => Some("stat_zn_t"),
        _ => None,
    }
}

pub fn bench_telemetry_schema() -> Schema {
    Schema::new(vec![
        Field::new(
            "ts",
            DataType::Timestamp(TimeUnit::Microsecond, None),
            false,
        ),
        Field::new("device_instance", DataType::UInt32, false),
        Field::new("oa_t", DataType::Float64, true),
        Field::new("oa_h", DataType::Float64, true),
        Field::new("duct_t", DataType::Float64, true),
        Field::new("stat_zn_t", DataType::Float64, true),
        Field::new("source", DataType::Utf8, false),
        Field::new("poll_cycle_id", DataType::UInt64, false),
    ])
}

pub fn samples_to_record_batch(samples: &[TelemetrySample]) -> Result<RecordBatch, String> {
    let schema = Arc::new(bench_telemetry_schema());
    let mut ts_vals = Vec::with_capacity(samples.len());
    let mut device_vals = Vec::with_capacity(samples.len());
    let mut oa_t = Vec::with_capacity(samples.len());
    let mut oa_h = Vec::with_capacity(samples.len());
    let mut duct_t = Vec::with_capacity(samples.len());
    let mut stat_zn_t = Vec::with_capacity(samples.len());
    let mut source = Vec::with_capacity(samples.len());
    let mut cycle = Vec::with_capacity(samples.len());

    for s in samples {
        ts_vals.push(s.ts.timestamp_micros());
        device_vals.push(s.device_instance);
        oa_t.push(s.oa_t);
        oa_h.push(s.oa_h);
        duct_t.push(s.duct_t);
        stat_zn_t.push(s.stat_zn_t);
        source.push(s.source.as_str());
        cycle.push(s.poll_cycle_id);
    }

    RecordBatch::try_new(
        schema,
        vec![
            Arc::new(TimestampMicrosecondArray::from(ts_vals)),
            Arc::new(UInt32Array::from(device_vals)),
            Arc::new(Float64Array::from(oa_t)),
            Arc::new(Float64Array::from(oa_h)),
            Arc::new(Float64Array::from(duct_t)),
            Arc::new(Float64Array::from(stat_zn_t)),
            Arc::new(StringArray::from(source)),
            Arc::new(UInt64Array::from(cycle)),
        ],
    )
    .map_err(|e| e.to_string())
}

#[derive(Default)]
pub struct TelemetryStore {
    samples: Vec<TelemetrySample>,
}

impl TelemetryStore {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn clear(&mut self) {
        self.samples.clear();
    }

    pub fn len(&self) -> usize {
        self.samples.len()
    }

    pub fn samples(&self) -> &[TelemetrySample] {
        &self.samples
    }

    pub fn append(&mut self, sample: TelemetrySample) {
        self.samples.push(sample);
    }

    pub fn record_batch(&self) -> Result<RecordBatch, String> {
        let mut sorted = self.samples.clone();
        sorted.sort_by_key(|s| s.ts);
        dedupe_timestamps(&mut sorted);
        samples_to_record_batch(&sorted)
    }

    pub fn sample_counts_by_column(&self) -> HashMap<String, u64> {
        let mut out = HashMap::new();
        for col in ["oa_t", "oa_h", "duct_t", "stat_zn_t"] {
            out.insert(col.to_string(), 0);
        }
        for s in &self.samples {
            if s.oa_t.is_some() {
                *out.get_mut("oa_t").unwrap() += 1;
            }
            if s.oa_h.is_some() {
                *out.get_mut("oa_h").unwrap() += 1;
            }
            if s.duct_t.is_some() {
                *out.get_mut("duct_t").unwrap() += 1;
            }
            if s.stat_zn_t.is_some() {
                *out.get_mut("stat_zn_t").unwrap() += 1;
            }
        }
        out
    }
}

fn dedupe_timestamps(samples: &mut Vec<TelemetrySample>) {
    if samples.len() < 2 {
        return;
    }
    let mut i = 0;
    while i + 1 < samples.len() {
        if samples[i].ts == samples[i + 1].ts {
            let next = samples[i + 1].clone();
            samples[i] = next;
            samples.remove(i + 1);
        } else {
            i += 1;
        }
    }
}

static GLOBAL: OnceLock<Mutex<TelemetryStore>> = OnceLock::new();

pub fn global_store() -> &'static Mutex<TelemetryStore> {
    GLOBAL.get_or_init(|| Mutex::new(TelemetryStore::new()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn record_batch_has_expected_columns() {
        let batch = samples_to_record_batch(&[TelemetrySample {
            ts: Utc::now(),
            device_instance: 5007,
            oa_t: Some(72.0),
            oa_h: Some(44.0),
            duct_t: Some(68.0),
            stat_zn_t: Some(71.0),
            source: "simulated".to_string(),
            poll_cycle_id: 1,
        }])
        .unwrap();
        assert_eq!(batch.num_columns(), 8);
        assert_eq!(batch.num_rows(), 1);
    }
}
