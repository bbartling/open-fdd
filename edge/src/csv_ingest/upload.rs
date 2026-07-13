//! Multipart and raw upload parsing for CSV import preview.

pub type UploadFiles = Vec<(String, Vec<u8>)>;
pub type UploadParseResult = Result<(UploadFiles, Option<String>), String>;

pub fn parse_upload(content_type: &str, body: &[u8]) -> UploadParseResult {
    let ct = content_type.to_ascii_lowercase();
    if ct.contains("multipart/form-data") {
        parse_multipart(content_type, body)
    } else if ct.contains("application/json") {
        parse_json_upload(body).map(|files| (files, None))
    } else {
        Ok((vec![("upload.csv".into(), body.to_vec())], None))
    }
}

fn parse_json_upload(body: &[u8]) -> Result<Vec<(String, Vec<u8>)>, String> {
    let v: serde_json::Value =
        serde_json::from_slice(body).map_err(|e| format!("invalid json: {e}"))?;
    let mut out = Vec::new();
    if let Some(arr) = v.get("files").and_then(|f| f.as_array()) {
        for f in arr {
            let name = f
                .get("filename")
                .and_then(|n| n.as_str())
                .unwrap_or("upload.csv");
            let b64 = f
                .get("content_base64")
                .and_then(|n| n.as_str())
                .unwrap_or("");
            use base64::Engine;
            let raw = base64::engine::general_purpose::STANDARD
                .decode(b64)
                .map_err(|e| e.to_string())?;
            out.push((name.to_string(), raw));
        }
    }
    Ok(out)
}

fn parse_multipart(content_type: &str, body: &[u8]) -> UploadParseResult {
    let boundary = content_type
        .split("boundary=")
        .nth(1)
        .map(|b| b.trim().trim_matches('"').to_string())
        .ok_or("missing multipart boundary")?;
    // Always parse on bytes — UTF-8 lossy conversion corrupts ZIP/binary CSV parts.
    parse_multipart_binary(&boundary, body)
}

fn extract_form_name(line: &str, key: &str) -> Option<String> {
    let pattern = format!("{key}=\"");
    let start = line
        .find(&pattern)
        .or_else(|| line.find(&format!("{key}=")))?;
    let rest = &line[start + key.len() + 1..];
    let rest = rest
        .trim_start_matches('=')
        .trim_matches('"')
        .trim_matches('\'');
    let end = rest.find('"').unwrap_or(rest.len());
    let mut value = rest[..end].to_string();
    if key == "filename" {
        if let Some(base) = value.rsplit(['/', '\\']).next() {
            value = base.to_string();
        }
    }
    if value.is_empty() {
        None
    } else {
        Some(value)
    }
}

fn parse_multipart_binary(boundary: &str, body: &[u8]) -> UploadParseResult {
    let marker = format!("--{boundary}");
    let parts: Vec<&[u8]> = split_bytes(body, marker.as_bytes());
    let mut files = Vec::new();
    let mut session_id = None;
    for part in parts {
        if part.len() < 4 {
            continue;
        }
        let header_end = part
            .windows(4)
            .position(|w| w == b"\r\n\r\n")
            .or_else(|| part.windows(2).position(|w| w == b"\n\n"));
        let Some(he) = header_end else { continue };
        let headers = String::from_utf8_lossy(&part[..he]);
        let sep_len = if part[he..].starts_with(b"\r\n\r\n") {
            4
        } else {
            2
        };
        let mut content = part[he + sep_len..].to_vec();
        while content.ends_with(b"\r\n") {
            content.pop();
            content.pop();
        }
        let mut filename = None;
        let mut field_name = None;
        for line in headers.lines() {
            let lower = line.to_ascii_lowercase();
            if lower.contains("content-disposition") {
                if let Some(n) = extract_form_name(line, "name") {
                    field_name = Some(n);
                }
                if let Some(f) = extract_form_name(line, "filename") {
                    filename = Some(f);
                }
            }
        }
        if content.is_empty() {
            continue;
        }
        if filename.is_some() {
            files.push((
                filename.unwrap_or_else(|| "upload.csv".to_string()),
                content,
            ));
        } else if field_name.as_deref() == Some("session_id") {
            session_id = Some(String::from_utf8_lossy(&content).trim().to_string());
        }
    }
    Ok((files, session_id))
}

fn split_bytes<'a>(hay: &'a [u8], needle: &[u8]) -> Vec<&'a [u8]> {
    let mut out = Vec::new();
    let mut start = 0;
    while let Some(i) = hay[start..].windows(needle.len()).position(|w| w == needle) {
        let at = start + i;
        out.push(&hay[start..at]);
        start = at + needle.len();
    }
    out.push(&hay[start..]);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_simple_multipart() {
        let body = b"--bound\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.csv\"\r\n\r\nDate,kW\r\n1/1/2013,1\r\n--bound--";
        let ct = "multipart/form-data; boundary=bound";
        let files = parse_multipart(ct, body).unwrap();
        assert_eq!(files.0.len(), 1);
        assert_eq!(files.0[0].0, "a.csv");
    }
}
