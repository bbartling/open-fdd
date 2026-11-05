//! Commission proxy retired — fieldbus is the sole BACnet process.

pub fn commission_base() -> String {
    String::new()
}

pub fn should_proxy_bacnet() -> bool {
    false
}

pub fn proxy_auth_header(_headers: &[(String, String)]) -> Option<String> {
    None
}

pub fn proxy_post(_path: &str, _body: &str, _auth: Option<&str>) -> Result<String, String> {
    Err("commission proxy removed; use openfdd-fieldbus MQTTS".into())
}
