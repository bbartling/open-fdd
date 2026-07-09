//! CSV scanner — header inspection and timestamp health without full loads.

pub mod scan;

pub use scan::{scan_history_csv, CsvScanReport, TimestampHealth};
