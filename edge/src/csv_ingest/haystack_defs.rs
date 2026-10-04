//! Pinned Project Haystack defs index for C3/C4 (#1123 / #1001).
//!
//! Artifact: `scripts/fixtures/haystack_rdf/defs/defs.ttl` (official normalized
//! Haystack 4.0.0 Turtle). The RDF documentation page's illustrative `4.0`
//! prefix is **not** the pin — the downloaded artifact uses `4.0.0`.

use once_cell::sync::Lazy;
use serde::Deserialize;
use std::collections::BTreeMap;

/// Pin id recorded on every strict projection / report.
pub const DEFS_PIN: &str = "haystack-defs-ttl-4.0.0";

pub const PH_BASE: &str = "https://project-haystack.org/def/ph/4.0.0#";
pub const PHIOT_BASE: &str = "https://project-haystack.org/def/phIoT/4.0.0#";
pub const PHSCIENCE_BASE: &str = "https://project-haystack.org/def/phScience/4.0.0#";
pub const PHICT_BASE: &str = "https://project-haystack.org/def/phIct/4.0.0#";
/// Documented RDF-mapping helper (not an ordinary instance-tag def).
pub const HAS_TAG_IRI: &str = "https://project-haystack.org/def/ph/4.0.0#hasTag";

const DEFS_INDEX_JSON: &str =
    include_str!("../../../scripts/fixtures/haystack_rdf/defs/defs_index.json");
const DEFS_PIN_JSON: &str =
    include_str!("../../../scripts/fixtures/haystack_rdf/defs/defs.pin.json");

#[derive(Debug, Clone, Deserialize)]
struct IndexFile {
    defs_pin: String,
    sha256: String,
    symbols: BTreeMap<String, SymbolEntry>,
}

#[derive(Debug, Clone, Deserialize)]
struct SymbolEntry {
    iri: String,
    #[serde(default)]
    owl: Option<String>,
    #[serde(default)]
    is_ref: bool,
}

#[derive(Debug, Clone, Deserialize)]
struct PinFile {
    defs_pin: String,
    sha256: String,
    source_url: String,
}

#[derive(Debug, Clone)]
pub struct DefSymbol {
    pub lib: String,
    pub symbol: String,
    pub iri: String,
    pub is_class: bool,
    pub is_ref: bool,
    pub is_value_property: bool,
}

#[derive(Debug)]
pub struct DefsIndex {
    pub defs_pin: String,
    pub sha256: String,
    pub source_url: String,
    by_symbol: BTreeMap<String, DefSymbol>,
}

impl DefsIndex {
    pub fn resolve(&self, symbol: &str) -> Option<&DefSymbol> {
        self.by_symbol.get(symbol)
    }

    pub fn contains(&self, symbol: &str) -> bool {
        self.by_symbol.contains_key(symbol)
    }
}

pub static DEFS: Lazy<DefsIndex> = Lazy::new(|| {
    let pin: PinFile = serde_json::from_str(DEFS_PIN_JSON).expect("defs.pin.json parse");
    let index: IndexFile = serde_json::from_str(DEFS_INDEX_JSON).expect("defs_index.json parse");
    assert_eq!(
        pin.defs_pin, DEFS_PIN,
        "embedded pin id mismatch with DEFS_PIN const"
    );
    assert_eq!(
        index.defs_pin, DEFS_PIN,
        "defs_index pin id mismatch with DEFS_PIN const"
    );
    assert_eq!(
        pin.sha256, index.sha256,
        "defs.pin.json sha256 must match defs_index.json"
    );

    let mut by_symbol = BTreeMap::new();
    for (key, entry) in index.symbols {
        let Some((lib, symbol)) = key.split_once(':') else {
            continue;
        };
        // Prefer first occurrence; symbols are unique across libs in this pin.
        if by_symbol.contains_key(symbol) {
            continue;
        }
        let owl = entry.owl.as_deref().unwrap_or("");
        let is_class = owl == "owl:Class";
        let is_value_property = owl == "owl:DatatypeProperty" || owl == "owl:ObjectProperty";
        by_symbol.insert(
            symbol.to_string(),
            DefSymbol {
                lib: lib.to_string(),
                symbol: symbol.to_string(),
                iri: entry.iri,
                is_class,
                is_ref: entry.is_ref,
                is_value_property,
            },
        );
    }

    DefsIndex {
        defs_pin: pin.defs_pin,
        sha256: pin.sha256,
        source_url: pin.source_url,
        by_symbol,
    }
});

pub fn defs() -> &'static DefsIndex {
    &DEFS
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pin_resolves_multi_library_terms() {
        let d = defs();
        assert_eq!(d.defs_pin, DEFS_PIN);
        assert_eq!(
            d.resolve("site").map(|s| s.iri.as_str()),
            Some("https://project-haystack.org/def/phIoT/4.0.0#site")
        );
        assert_eq!(
            d.resolve("air").map(|s| s.iri.as_str()),
            Some("https://project-haystack.org/def/phScience/4.0.0#air")
        );
        assert_eq!(
            d.resolve("hasTag").map(|s| s.iri.as_str()),
            Some(HAS_TAG_IRI)
        );
        assert_eq!(
            d.resolve("dis").map(|s| s.iri.as_str()),
            Some("https://project-haystack.org/def/ph/4.0.0#dis")
        );
        assert_eq!(
            d.resolve("heatPump").map(|s| s.symbol.as_str()),
            Some("heatPump")
        );
        assert!(d.resolve("HEATPUMP").is_none(), "case-sensitive");
        assert!(d.resolve("vendorFooTag").is_none());
    }

    #[test]
    fn pin_sha_matches_vendored_ttl() {
        use sha2::{Digest, Sha256};
        let ttl = include_bytes!("../../../scripts/fixtures/haystack_rdf/defs/defs.ttl");
        let mut h = Sha256::new();
        h.update(ttl);
        let digest = format!("{:x}", h.finalize());
        assert_eq!(digest, defs().sha256);
    }
}
