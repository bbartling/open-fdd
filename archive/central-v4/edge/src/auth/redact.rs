//! Bounded, secret-scrubbed text for security audit records and crash output.
//!
//! Every string that reaches the audit sink or the panic hook goes through
//! [`bounded_text`]: credential-shaped words are replaced, control and bidi
//! format characters are escaped, and the result is cut to a fixed character
//! budget with an explicit [`TRUNCATION_MARKER`].

/// Appended to any value that was cut to its budget.
pub const TRUNCATION_MARKER: &str = "…[truncated]";
/// Replacement for a credential-shaped value.
pub const REDACTED: &str = "[redacted]";
/// Input beyond this many bytes is never scanned. Callers' budgets are far smaller.
pub const MAX_SCAN_BYTES: usize = 64 * 1024;

/// Key fragments whose `key=value` / `key:value` value is always replaced.
const SECRET_KEYS: &[&str] = &[
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "api-key",
    "access_key",
    "private_key",
    "credential",
    "cookie",
    "session",
    "signature",
    "jwt",
];

/// Words that announce a credential in the next word (`Bearer <token>`).
const AUTH_SCHEMES: &[&str] = &["bearer", "basic", "token", "digest"];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Bounded {
    pub text: String,
    pub truncated: bool,
}

/// Scrub, escape, and cut `raw` to at most `max_chars` characters
/// (marker included when cut).
pub fn bounded_text(raw: &str, max_chars: usize) -> Bounded {
    let (scan, cut_for_scan) = scan_window(raw);
    let scrubbed = scrub_secrets(scan);
    let escaped = escape_controls(&scrubbed);
    let mut out = truncate_chars(&escaped, max_chars);
    if cut_for_scan && !out.truncated {
        out = force_marker(&out.text, max_chars);
    }
    out
}

/// Convenience wrapper when the truncation flag is not needed.
pub fn bounded(raw: &str, max_chars: usize) -> String {
    bounded_text(raw, max_chars).text
}

fn scan_window(raw: &str) -> (&str, bool) {
    if raw.len() <= MAX_SCAN_BYTES {
        return (raw, false);
    }
    let mut end = MAX_SCAN_BYTES;
    while end > 0 && !raw.is_char_boundary(end) {
        end -= 1;
    }
    (&raw[..end], true)
}

fn truncate_chars(text: &str, max_chars: usize) -> Bounded {
    if text.chars().count() <= max_chars {
        return Bounded {
            text: text.to_string(),
            truncated: false,
        };
    }
    force_marker(text, max_chars)
}

fn force_marker(text: &str, max_chars: usize) -> Bounded {
    let marker_chars = TRUNCATION_MARKER.chars().count();
    let keep = max_chars.saturating_sub(marker_chars);
    let mut out: String = text.chars().take(keep).collect();
    if max_chars >= marker_chars {
        out.push_str(TRUNCATION_MARKER);
    }
    Bounded {
        text: out,
        truncated: true,
    }
}

fn is_hidden_format(c: char) -> bool {
    matches!(
        c,
        '\u{200B}'..='\u{200F}' | '\u{202A}'..='\u{202E}' | '\u{2060}'..='\u{2069}' | '\u{FEFF}'
    )
}

fn escape_controls(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for c in text.chars() {
        if c.is_control() || is_hidden_format(c) {
            out.push_str(&format!("\\u{{{:x}}}", u32::from(c)));
        } else {
            out.push(c);
        }
    }
    out
}

fn scrub_secrets(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    let mut rest = input;
    let mut redact_next = false;
    while !rest.is_empty() {
        let word_start = rest
            .find(|c: char| !c.is_whitespace())
            .unwrap_or(rest.len());
        out.push_str(&rest[..word_start]);
        rest = &rest[word_start..];
        if rest.is_empty() {
            break;
        }
        let word_end = rest.find(char::is_whitespace).unwrap_or(rest.len());
        let word = &rest[..word_end];
        rest = &rest[word_end..];
        if redact_next {
            out.push_str(REDACTED);
            redact_next = false;
            continue;
        }
        let lower = word.to_ascii_lowercase();
        let bare = lower.trim_matches(|c: char| !c.is_ascii_alphanumeric());
        redact_next = AUTH_SCHEMES.contains(&bare);
        out.push_str(&scrub_word(word));
    }
    out
}

fn is_b64url(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '-' || c == '_'
}

/// `eyJ` (base64 of `{"`) followed by at least ten base64url characters.
fn looks_like_jwt(word: &str) -> bool {
    word.match_indices("eyJ").any(|(at, _)| {
        word[at + 3..]
            .chars()
            .take_while(|c| is_b64url(*c))
            .take(10)
            .count()
            == 10
    })
}

fn scrub_word(word: &str) -> String {
    if looks_like_jwt(word) {
        return REDACTED.to_string();
    }
    let word = scrub_url(word);
    scrub_key_values(&word)
}

/// Drop URL userinfo, query, and fragment (`scheme://user:pw@host/p?q#f`).
fn scrub_url(word: &str) -> String {
    let Some(scheme_end) = word.find("://") else {
        return word.to_string();
    };
    let authority_start = scheme_end + 3;
    let after = &word[authority_start..];
    let authority_len = after.find(['/', '?', '#']).unwrap_or(after.len());
    let authority = &after[..authority_len];
    let mut out = String::with_capacity(word.len());
    out.push_str(&word[..authority_start]);
    match authority.rfind('@') {
        Some(at) => {
            out.push_str(REDACTED);
            out.push_str(&authority[at..]);
        }
        None => out.push_str(authority),
    }
    let tail = &after[authority_len..];
    match tail.find(['?', '#']) {
        Some(q) => {
            out.push_str(&tail[..q]);
            out.push_str(&tail[q..q + 1]);
            out.push_str(REDACTED);
        }
        None => out.push_str(tail),
    }
    out
}

const KEY_DELIMS: &[char] = &['?', '&', ';', ',', '{', '"', '\'', '(', '<', '[', ' '];
const VALUE_END: &[char] = &['&', ';', ',', '"', '\'', '}', ')', '>', ']'];

/// Replace the value of any `key=value` / `key:value` pair whose key names a secret.
fn scrub_key_values(word: &str) -> String {
    let mut out = String::with_capacity(word.len());
    let mut rest = word;
    while let Some(sep) = rest.find(['=', ':']) {
        let (head, tail) = rest.split_at(sep);
        let key_start = head.rfind(KEY_DELIMS).map_or(0, |i| i + 1);
        let key = head[key_start..].to_ascii_lowercase();
        out.push_str(head);
        out.push_str(&tail[..1]);
        let value = &tail[1..];
        if !key.is_empty() && SECRET_KEYS.iter().any(|k| key.contains(k)) {
            let value_len = value.find(VALUE_END).unwrap_or(value.len());
            if value_len > 0 {
                out.push_str(REDACTED);
            }
            rest = &value[value_len..];
        } else {
            rest = value;
        }
    }
    out.push_str(rest);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redacts_bearer_jwt_url_query_and_key_values() {
        let jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJjYW5hcnkifQ.c2lnbmF0dXJlLWNhbmFyeQ";
        let raw = format!(
            "Authorization: Bearer opaque-canary-123 {jwt} https://u:pw-canary@h.example/p?api_key=q-canary#frag password=pw-canary2 x"
        );
        let out = bounded(&raw, 4096);
        for canary in [
            "opaque-canary-123",
            "eyJhbGci",
            "pw-canary",
            "q-canary",
            "frag",
            "pw-canary2",
        ] {
            assert!(!out.contains(canary), "{canary} leaked in {out}");
        }
        assert!(
            out.contains("https://[redacted]@h.example/p?[redacted]"),
            "{out}"
        );
        assert!(out.ends_with(" x"), "{out}");
    }

    #[test]
    fn escapes_control_and_bidi_characters() {
        let out = bounded("a\nb\u{1b}[31m\u{202e}c\u{0}", 64);
        assert!(!out.chars().any(|c| c.is_control() || is_hidden_format(c)));
        assert!(out.contains("\\u{a}"), "{out}");
        assert!(out.contains("\\u{1b}"), "{out}");
        assert!(out.contains("\\u{202e}"), "{out}");
    }

    #[test]
    fn truncates_with_marker_and_bounds_huge_input() {
        let huge = "x".repeat(100 * 1024);
        let out = bounded_text(&huge, 128);
        assert!(out.truncated);
        assert_eq!(out.text.chars().count(), 128);
        assert!(out.text.ends_with(TRUNCATION_MARKER));

        let short = bounded_text("site-a", 128);
        assert!(!short.truncated);
        assert_eq!(short.text, "site-a");
    }

    #[test]
    fn plain_identifiers_pass_through() {
        for id in [
            "tenant-a",
            "BUILDING_100",
            "acme-ops@example.com",
            "AHU_1:sat",
        ] {
            assert_eq!(bounded(id, 128), id);
        }
    }
}
