//! Minimal mock Haystack HTTP server for unit tests (Basic auth + JSON grids).

#[cfg(test)]
pub mod tests {
    use super::super::client::{about, read, test_connection};
    use super::super::config::HaystackConfig;
    use std::io::{Read, Write};
    use std::net::{TcpListener, TcpStream};
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;
    use std::thread;
    use std::time::Duration;

    static ABOUT_JSON: &str = r#"{"_kind":"grid","meta":{"ver":"3.0"},"cols":[{"name":"productName"}],"rows":[{"productName":"mock-nhaystack"}]}"#;
    static OPS_JSON: &str = r#"{"_kind":"grid","meta":{"ver":"3.0"},"cols":[{"name":"name"}],"rows":[{"name":"about"},{"name":"read"},{"name":"nav"}]}"#;
    static READ_JSON: &str = r#"{"_kind":"grid","meta":{"ver":"3.0"},"cols":[{"name":"id"},{"name":"dis"},{"name":"point"},{"name":"curVal"}],"rows":[{"id":"@point:mock-t","dis":"Mock Temp","point":"m:","curVal":70.0}]}"#;

    fn handle(mut stream: TcpStream) {
        let mut buf = [0u8; 4096];
        let n = stream.read(&mut buf).unwrap_or(0);
        let req = String::from_utf8_lossy(&buf[..n]);
        let (status, body) =
            if req.contains("GET /haystack/about") || req.contains("POST /haystack/about") {
                ("200 OK", ABOUT_JSON)
            } else if req.contains("/haystack/ops") {
                ("200 OK", OPS_JSON)
            } else if req.contains("/haystack/read") || req.contains("/haystack/nav") {
                ("200 OK", READ_JSON)
            } else {
                ("404 Not Found", r#"{"error":"not found"}"#)
            };
        let resp = format!(
            "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{}",
            body.len(),
            body
        );
        let _ = stream.write_all(resp.as_bytes());
    }

    pub fn spawn_mock_server() -> (String, Arc<AtomicBool>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind mock haystack");
        listener.set_nonblocking(true).ok();
        let addr = listener.local_addr().unwrap();
        let running = Arc::new(AtomicBool::new(true));
        let flag = running.clone();
        thread::spawn(move || {
            while flag.load(Ordering::SeqCst) {
                if let Ok((stream, _)) = listener.accept() {
                    thread::spawn(move || handle(stream));
                }
                thread::sleep(Duration::from_millis(5));
            }
        });
        (
            format!("http://127.0.0.1:{}/haystack", addr.port()),
            running,
        )
    }

    fn mock_config(base: &str) -> HaystackConfig {
        HaystackConfig {
            enabled: true,
            base_url: base.to_string(),
            auth_mode: "basic".to_string(),
            username: Some("test".to_string()),
            password: Some("test".to_string()),
            tls_verify: true,
            ..HaystackConfig::default()
        }
    }

    #[test]
    fn mock_server_about_and_read() {
        std::env::set_var("OPENFDD_HAYSTACK_FORMAT", "application/json");
        let (base, running) = spawn_mock_server();
        let cfg = mock_config(&base);
        let test = test_connection(&cfg);
        assert_eq!(test["ok"], true, "{test}");
        let ab = about(&cfg);
        assert_eq!(ab["ok"], true);
        let rd = read(&cfg, &serde_json::json!({"filter": "point"}));
        assert_eq!(rd["ok"], true);
        running.store(false, Ordering::SeqCst);
    }
}
