//! Shared BACnet WriteProperty value normalization.
//!
//! REST validation, dry-run responses, and live writes must classify the same
//! JSON representations identically. In particular, every representation of
//! BACnet NULL is a priority release and therefore requires a valid priority.

use bacnet_encoding::primitives::encode_property_value;
use bacnet_types::primitives::PropertyValue;
use bytes::BytesMut;
use serde_json::Value;

#[derive(Debug)]
pub(crate) struct NormalizedBacnetWrite {
    pub property_value: PropertyValue,
    pub encoded_value: Vec<u8>,
    pub priority: Option<u8>,
    pub released: bool,
}

/// Normalize, validate, and encode one BACnet write exactly once.
pub(crate) fn normalize_bacnet_write(
    value: Option<&Value>,
    priority: Option<u8>,
    value_type: Option<&str>,
) -> Result<NormalizedBacnetWrite, String> {
    let value_is_null = match value {
        None | Some(Value::Null) => true,
        Some(Value::String(text)) => text.trim().eq_ignore_ascii_case("null"),
        Some(_) => false,
    };
    let type_is_null = value_type.is_some_and(|raw| raw.trim().eq_ignore_ascii_case("null"));
    let released = value_is_null || type_is_null;

    let property_value = if released {
        PropertyValue::Null
    } else {
        make_property_value(
            value
                .ok_or_else(|| "write value is required unless releasing a priority".to_string())?,
            value_type,
        )?
    };

    let priority = if released {
        let Some(priority) = priority else {
            return Err("Null requires a priority (1-16) to release override".into());
        };
        if !(1..=16).contains(&priority) {
            return Err("Null requires a priority (1-16) to release override".into());
        }
        Some(priority)
    } else {
        priority
    };

    let mut encoded_value = BytesMut::new();
    encode_property_value(&mut encoded_value, &property_value).map_err(|e| e.to_string())?;

    Ok(NormalizedBacnetWrite {
        property_value,
        encoded_value: encoded_value.to_vec(),
        priority,
        released,
    })
}

fn finite_real(value: f64) -> Result<f32, String> {
    if !value.is_finite() {
        return Err("real value must be finite".into());
    }
    let value = value as f32;
    if !value.is_finite() {
        return Err("real value is outside BACnet REAL range".into());
    }
    Ok(value)
}

fn make_property_value(value: &Value, value_type: Option<&str>) -> Result<PropertyValue, String> {
    let value_type = value_type.unwrap_or("").trim().to_ascii_lowercase();
    if !value_type.is_empty() {
        return match value_type.as_str() {
            "real" => Ok(PropertyValue::Real(finite_real(
                value
                    .as_f64()
                    .ok_or_else(|| "real value must be numeric".to_string())?,
            )?)),
            "double" => {
                let value = value
                    .as_f64()
                    .ok_or_else(|| "double value must be numeric".to_string())?;
                if !value.is_finite() {
                    return Err("double value must be finite".into());
                }
                Ok(PropertyValue::Double(value))
            }
            "unsigned" => Ok(PropertyValue::Unsigned(value.as_u64().ok_or_else(
                || "unsigned value must be a non-negative integer".to_string(),
            )?)),
            "signed" => Ok(PropertyValue::Signed(
                i32::try_from(
                    value
                        .as_i64()
                        .ok_or_else(|| "signed value must be an integer".to_string())?,
                )
                .map_err(|_| "signed value is outside BACnet SIGNED range".to_string())?,
            )),
            "enumerated" => Ok(PropertyValue::Enumerated(
                u32::try_from(value.as_u64().ok_or_else(|| {
                    "enumerated value must be a non-negative integer".to_string()
                })?)
                .map_err(|_| "enumerated value is outside BACnet ENUMERATED range".to_string())?,
            )),
            "boolean" => {
                Ok(PropertyValue::Boolean(value.as_bool().ok_or_else(
                    || "boolean value must be true or false".to_string(),
                )?))
            }
            "character_string" | "character-string" => Ok(PropertyValue::CharacterString(
                value
                    .as_str()
                    .ok_or_else(|| "character_string value must be a string".to_string())?
                    .to_string(),
            )),
            _ => Err(format!("unknown value_type {value_type}")),
        };
    }

    if let Some(value) = value.as_bool() {
        return Ok(PropertyValue::Enumerated(if value { 1 } else { 0 }));
    }
    if let Some(value) = value.as_f64() {
        return Ok(PropertyValue::Real(finite_real(value)?));
    }
    if let Some(value) = value.as_i64() {
        return Ok(PropertyValue::Real(finite_real(value as f64)?));
    }
    if let Some(value) = value.as_str() {
        return Ok(PropertyValue::CharacterString(value.to_string()));
    }
    Err("unsupported value type".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_null_representation_requires_a_valid_priority() {
        for (value, value_type) in [
            (None, None),
            (Some(Value::Null), None),
            (
                Some(Value::String(" null ".into())),
                Some("character-string"),
            ),
            (Some(Value::Number(42.into())), Some("null")),
        ] {
            assert!(normalize_bacnet_write(value.as_ref(), None, value_type).is_err());
            let normalized = normalize_bacnet_write(value.as_ref(), Some(16), value_type)
                .expect("NULL representation should normalize");
            assert!(normalized.released);
            assert!(matches!(normalized.property_value, PropertyValue::Null));
            assert_eq!(normalized.priority, Some(16));
        }
    }

    #[test]
    fn typed_numeric_overflow_and_non_finite_values_are_rejected() {
        assert!(
            normalize_bacnet_write(Some(&serde_json::json!(i64::MAX)), None, Some("signed"))
                .is_err()
        );
        assert!(normalize_bacnet_write(
            Some(&serde_json::json!(u64::MAX)),
            None,
            Some("enumerated")
        )
        .is_err());
        assert!(
            normalize_bacnet_write(Some(&serde_json::json!(1e100)), None, Some("real")).is_err()
        );
        assert!(
            normalize_bacnet_write(Some(&serde_json::json!(1e100)), None, Some("double")).is_ok()
        );
    }
}
