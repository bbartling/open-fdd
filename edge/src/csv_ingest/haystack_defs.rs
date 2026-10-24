//! Pinned Project Haystack defs index for C3/C4 (#1123 / #1001).
//!
//! Artifact: `scripts/fixtures/haystack_rdf/defs/defs.ttl` (official normalized
//! Haystack 4.0.0 Turtle). The RDF documentation page's illustrative `4.0`
//! prefix is **not** the pin — the downloaded artifact uses `4.0.0`.

use once_cell::sync::Lazy;
use serde::Deserialize;
use std::collections::{BTreeMap, BTreeSet};

/// Pin id recorded on every strict projection / report.
pub const DEFS_PIN: &str = "haystack-defs-ttl-4.0.0";

pub const PH_BASE: &str = "https://project-haystack.org/def/ph/4.0.0#";
pub const PHIOT_BASE: &str = "https://project-haystack.org/def/phIoT/4.0.0#";
pub const PHSCIENCE_BASE: &str = "https://project-haystack.org/def/phScience/4.0.0#";
pub const PHICT_BASE: &str = "https://project-haystack.org/def/phIct/4.0.0#";
/// Documented RDF-mapping helper (not an ordinary instance-tag def).
pub const HAS_TAG_IRI: &str = "https://project-haystack.org/def/ph/4.0.0#hasTag";
/// Open-FDD instance namespace. Not a Project Haystack library.
pub const OFDD_NS: &str = "urn:openfdd:ns#";
/// Literal predicate for a symbol that is not a pinned def and not an explicit extension.
pub const NATIVE_TAG_IRI: &str = "urn:openfdd:ns#nativeTag";
/// Explicit `ext:` markers. Never minted under `ph`, `phIoT`, `phScience`, or `phIct`.
pub const EXTENSION_NS: &str = "urn:openfdd:ext#";

// Embedded under edge/assets so Docker/central builds that COPY edge/ still compile.
const DEFS_INDEX_JSON: &str = include_str!("../../assets/haystack_rdf/defs/defs_index.json");
const DEFS_PIN_JSON: &str = include_str!("../../assets/haystack_rdf/defs/defs.pin.json");

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

fn empty_defs_index() -> DefsIndex {
    DefsIndex {
        defs_pin: String::new(),
        sha256: String::new(),
        source_url: String::new(),
        by_symbol: BTreeMap::new(),
    }
}

fn load_embedded_defs() -> DefsIndex {
    let pin: PinFile = match serde_json::from_str(DEFS_PIN_JSON) {
        Ok(pin) => pin,
        Err(_) => return empty_defs_index(),
    };
    let index: IndexFile = match serde_json::from_str(DEFS_INDEX_JSON) {
        Ok(index) => index,
        Err(_) => return empty_defs_index(),
    };
    if pin.defs_pin != DEFS_PIN || index.defs_pin != DEFS_PIN || pin.sha256 != index.sha256 {
        return empty_defs_index();
    }

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
}

pub static DEFS: Lazy<DefsIndex> = Lazy::new(load_embedded_defs);

pub fn defs() -> &'static DefsIndex {
    &DEFS
}

/// One published symbol after case-sensitive lookup in the pinned def index.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TagVerdict {
    /// `owl:Class`. Safe to emit as `ph:hasTag`.
    Marker {
        symbol: String,
        iri: String,
        lib: String,
    },
    /// Datatype or object property. Not a marker class.
    Value {
        symbol: String,
        iri: String,
        lib: String,
        is_ref: bool,
    },
    /// Caller-declared `ext:` token. IRI is [`EXTENSION_NS`], not a Haystack library.
    Extension { symbol: String, iri: String },
    /// Not in the pin and not an explicit extension.
    Unknown { symbol: String },
    /// Empty, `false`, `null`, `none`, or `0`. Never a present tag.
    Absent { symbol: String },
}

/// Official class or explicit extension selected for `ph:hasTag`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EmittedTag {
    pub symbol: String,
    pub iri: String,
    pub lib: String,
}

/// Why a symbol was not emitted as a pinned Haystack class.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TagDiagnostic {
    pub symbol: String,
    /// `absent`, `value_not_marker`, `unknown`, or `extension`.
    pub outcome: &'static str,
    pub detail: String,
}

/// Marker list split into pinned classes, explicit extensions, and native text.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct ResolvedTagList {
    pub markers: Vec<EmittedTag>,
    pub extensions: Vec<EmittedTag>,
    pub native: Vec<String>,
    pub diagnostics: Vec<TagDiagnostic>,
}

/// IRI of any pinned def. Does not decide whether the symbol is a marker.
pub fn pinned_iri(symbol: &str) -> Result<String, String> {
    let symbol = symbol.trim();
    defs()
        .resolve(symbol)
        .map(|def| def.iri.clone())
        .ok_or_else(|| format!("missing pinned def for {symbol}"))
}

/// Case-preserving classification. The caller does not choose the Haystack library.
pub fn resolve_published_tag(raw: &str) -> TagVerdict {
    let symbol = raw.trim();
    if absent_marker(symbol) {
        return TagVerdict::Absent {
            symbol: symbol.to_string(),
        };
    }
    if let Some(local) = explicit_extension_local(symbol) {
        return TagVerdict::Extension {
            symbol: local.to_string(),
            iri: format!("{EXTENSION_NS}{local}"),
        };
    }
    match defs().resolve(symbol) {
        Some(def) if def.is_class => TagVerdict::Marker {
            symbol: def.symbol.clone(),
            iri: def.iri.clone(),
            lib: def.lib.clone(),
        },
        Some(def) => TagVerdict::Value {
            symbol: def.symbol.clone(),
            iri: def.iri.clone(),
            lib: def.lib.clone(),
            is_ref: def.is_ref,
        },
        None => TagVerdict::Unknown {
            symbol: symbol.to_string(),
        },
    }
}

/// Resolve a marker list once for NF inventory, agent CRUD, and package projection.
pub fn resolve_marker_list(raw: &[String]) -> ResolvedTagList {
    let mut out = ResolvedTagList::default();
    let mut seen_markers = BTreeSet::new();
    let mut seen_extensions = BTreeSet::new();
    let mut seen_native = BTreeSet::new();
    for tag in raw {
        match resolve_published_tag(tag) {
            TagVerdict::Marker { symbol, iri, lib } => {
                if seen_markers.insert(symbol.clone()) {
                    out.markers.push(EmittedTag { symbol, iri, lib });
                }
            }
            TagVerdict::Extension { symbol, iri } => {
                if seen_extensions.insert(iri.clone()) {
                    out.diagnostics.push(TagDiagnostic {
                        symbol: format!("ext:{symbol}"),
                        outcome: "extension",
                        detail: "explicit Open-FDD extension; not a pinned Haystack class".into(),
                    });
                    out.extensions.push(EmittedTag {
                        symbol,
                        iri,
                        lib: "ext".into(),
                    });
                }
            }
            TagVerdict::Value { symbol, .. } => {
                out.diagnostics.push(TagDiagnostic {
                    symbol,
                    outcome: "value_not_marker",
                    detail: "def exists but is not an owl:Class marker/entity tag".into(),
                });
            }
            TagVerdict::Unknown { symbol } => {
                if seen_native.insert(symbol.clone()) {
                    out.diagnostics.push(TagDiagnostic {
                        symbol: symbol.clone(),
                        outcome: "unknown",
                        detail: format!("not in pinned defs {DEFS_PIN}"),
                    });
                    out.native.push(symbol);
                }
            }
            TagVerdict::Absent { symbol } => {
                out.diagnostics.push(TagDiagnostic {
                    symbol,
                    outcome: "absent",
                    detail: "false/null/empty markers are never present tags".into(),
                });
            }
        }
    }
    out
}

fn absent_marker(tag: &str) -> bool {
    tag.is_empty()
        || tag.eq_ignore_ascii_case("false")
        || tag.eq_ignore_ascii_case("null")
        || tag.eq_ignore_ascii_case("none")
        || tag == "0"
}

/// `ext:Local` is an explicit extension. A Haystack prefix does not select a library.
fn explicit_extension_local(tag: &str) -> Option<&str> {
    let local = tag.strip_prefix("ext:")?;
    if extension_token(local) {
        Some(local)
    } else {
        None
    }
}

fn extension_token(local: &str) -> bool {
    let mut chars = local.chars();
    match chars.next() {
        Some(c) if c.is_ascii_alphabetic() => {}
        _ => return false,
    }
    local.chars().count() <= 64
        && local
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '-'))
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
    fn resolver_keeps_library_and_case() {
        match resolve_published_tag("heatPump") {
            TagVerdict::Marker { symbol, iri, lib } => {
                assert_eq!(symbol, "heatPump");
                assert_eq!(lib, "phIoT");
                assert_eq!(iri, "https://project-haystack.org/def/phIoT/4.0.0#heatPump");
            }
            other => panic!("heatPump verdict {other:?}"),
        }
        assert!(matches!(
            resolve_published_tag("heatpump"),
            TagVerdict::Unknown { .. }
        ));
        assert!(matches!(
            resolve_published_tag("phIoT:heatPump"),
            TagVerdict::Unknown { .. }
        ));
        match resolve_published_tag("discharge") {
            TagVerdict::Marker { lib, .. } => assert_eq!(lib, "phIoT"),
            other => panic!("discharge {other:?}"),
        }
        match resolve_published_tag("air") {
            TagVerdict::Marker { lib, .. } => assert_eq!(lib, "phScience"),
            other => panic!("air {other:?}"),
        }
        match resolve_published_tag("temp") {
            TagVerdict::Marker { lib, .. } => assert_eq!(lib, "phScience"),
            other => panic!("temp {other:?}"),
        }
        match resolve_published_tag("protocol") {
            TagVerdict::Marker { lib, .. } => assert_eq!(lib, "phIct"),
            other => panic!("protocol {other:?}"),
        }
        match resolve_published_tag("unit") {
            TagVerdict::Value { is_ref, lib, .. } => {
                assert!(!is_ref);
                assert_eq!(lib, "ph");
            }
            other => panic!("unit {other:?}"),
        }
        match resolve_published_tag("equipRef") {
            TagVerdict::Value { is_ref, .. } => assert!(is_ref),
            other => panic!("equipRef {other:?}"),
        }
        match resolve_published_tag("ext:sitePolicy") {
            TagVerdict::Extension { symbol, iri } => {
                assert_eq!(symbol, "sitePolicy");
                assert_eq!(iri, format!("{EXTENSION_NS}sitePolicy"));
            }
            other => panic!("extension {other:?}"),
        }
        assert!(matches!(
            resolve_published_tag("false"),
            TagVerdict::Absent { .. }
        ));
        assert!(matches!(
            resolve_published_tag("vendorFooTag"),
            TagVerdict::Unknown { .. }
        ));
        assert_eq!(NATIVE_TAG_IRI, format!("{OFDD_NS}nativeTag"));
    }

    #[test]
    fn pin_sha_matches_vendored_ttl() {
        use sha2::{Digest, Sha256};
        let ttl = include_bytes!("../../assets/haystack_rdf/defs/defs.ttl");
        let mut h = Sha256::new();
        h.update(ttl);
        let digest = format!("{:x}", h.finalize());
        assert_eq!(digest, defs().sha256);
    }
}
