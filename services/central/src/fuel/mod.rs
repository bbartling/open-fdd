//! Utility-bill Fuel analytics (vibe20 Phase-1 parity).
//!
//! Campus JSON + monthly bill CSVs under `$OPENFDD_WORKSPACE/data/fuel/<campus_id>/`.

pub mod analytics;
pub mod bills;
pub mod campus;
pub mod eui;
pub mod import;
pub mod open_meteo;

// Re-export surface for HTTP handlers / other modules.
pub use analytics::{handle_fuel, FuelRequest};
pub use campus::{annual_summary, load_campus, Campus, KBTU_PER_KWH, KBTU_PER_MCF};
pub use eui::compare_eui;
pub use import::{fuel_root, import_fuel_zip, list_campuses};
pub use open_meteo::fetch_open_meteo_handler;
