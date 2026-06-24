//! Self-signed TLS certificate generation for Caddy/local edge deployments.

use rcgen::{CertificateParams, DnType, SanType};
use std::fs;
use std::net::IpAddr;
use std::path::{Path, PathBuf};

pub struct TlsGenerateOptions {
    pub cn: String,
    pub out_dir: PathBuf,
    pub lan_ip: Option<String>,
}

pub struct TlsGenerateResult {
    pub cert_path: PathBuf,
    pub key_path: PathBuf,
}

pub fn default_cert_dir() -> PathBuf {
    std::env::var("OPENFDD_CADDY_CERT_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            std::env::var("OPENFDD_WORKSPACE")
                .map(PathBuf::from)
                .unwrap_or_else(|_| PathBuf::from("workspace"))
                .join("deploy/caddy/certs")
        })
}

pub fn generate_self_signed(opts: &TlsGenerateOptions) -> Result<TlsGenerateResult, String> {
    fs::create_dir_all(&opts.out_dir).map_err(|e| e.to_string())?;

    let mut params = CertificateParams::new(vec![opts.cn.clone()]).map_err(|e| e.to_string())?;
    params.distinguished_name.push(DnType::CommonName, &opts.cn);
    params.subject_alt_names.push(SanType::DnsName(
        "localhost".try_into().map_err(|e| format!("{e}"))?,
    ));
    params
        .subject_alt_names
        .push(SanType::IpAddress("127.0.0.1".parse::<IpAddr>().unwrap()));
    if let Some(ip) = &opts.lan_ip {
        if let Ok(parsed) = ip.parse::<IpAddr>() {
            params.subject_alt_names.push(SanType::IpAddress(parsed));
        }
    }

    let key_pair = rcgen::KeyPair::generate().map_err(|e| e.to_string())?;
    let cert = params.self_signed(&key_pair).map_err(|e| e.to_string())?;
    let cert_pem = cert.pem();
    let key_pem = key_pair.serialize_pem();

    let cert_path = opts.out_dir.join("cert.pem");
    let key_path = opts.out_dir.join("key.pem");
    fs::write(&cert_path, cert_pem).map_err(|e| e.to_string())?;
    fs::write(&key_path, key_pem).map_err(|e| e.to_string())?;
    chmod_600_unix(&key_path);

    Ok(TlsGenerateResult {
        cert_path,
        key_path,
    })
}

fn chmod_600_unix(path: &Path) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Ok(meta) = fs::metadata(path) {
            let mut perms = meta.permissions();
            perms.set_mode(0o600);
            let _ = fs::set_permissions(path, perms);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn generates_cert_and_key_with_sans() {
        let dir = std::env::temp_dir().join(format!(
            "openfdd-tls-{}",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let result = generate_self_signed(&TlsGenerateOptions {
            cn: "openfdd.local".into(),
            out_dir: dir.clone(),
            lan_ip: Some("192.168.1.10".into()),
        })
        .unwrap();
        assert!(result.cert_path.exists());
        assert!(result.key_path.exists());
        let cert = fs::read_to_string(result.cert_path).unwrap();
        assert!(cert.contains("BEGIN CERTIFICATE"));
        let _ = fs::remove_dir_all(dir);
    }
}
