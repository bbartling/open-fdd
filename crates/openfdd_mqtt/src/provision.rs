//! AWS-IoT-style edge certificate kit generation.

use std::fs;
use std::path::{Path, PathBuf};

use openfdd_contracts::TopicBuilder;
use rcgen::{
    BasicConstraints, CertificateParams, DistinguishedName, DnType, IsCa, KeyPair, KeyUsagePurpose,
};
use serde::Serialize;

#[derive(Debug, Clone)]
pub struct ProvisionRequest {
    pub out_dir: PathBuf,
    pub site_id: String,
    pub edge_id: String,
    pub broker_host: String,
    pub broker_port: u16,
    /// Prefer an existing CA directory containing `ca.pem` + `ca.key.pem`.
    pub ca_dir: Option<PathBuf>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ProvisionResult {
    pub kit_dir: PathBuf,
    pub ca_pem: PathBuf,
    pub edge_cert: PathBuf,
    pub edge_key: PathBuf,
    pub central_cert: PathBuf,
    pub central_key: PathBuf,
    pub edge_config: PathBuf,
    pub mosquitto_acl: PathBuf,
}

pub fn provision_edge_kit(req: &ProvisionRequest) -> anyhow::Result<ProvisionResult> {
    let kits_root = req.out_dir.join("kits");
    fs::create_dir_all(&kits_root)?;
    let kit = kits_root.join(format!("{}__{}", req.site_id, req.edge_id));
    fs::create_dir_all(&kit)?;
    let ca_dir = req.ca_dir.clone().unwrap_or_else(|| req.out_dir.join("ca"));
    fs::create_dir_all(&ca_dir)?;

    let ca_key_path = ca_dir.join("ca.key.pem");
    let ca_cert_path = ca_dir.join("ca.pem");

    let ca_key = if ca_key_path.exists() {
        KeyPair::from_pem(&fs::read_to_string(&ca_key_path)?)?
    } else {
        let key = KeyPair::generate()?;
        fs::write(&ca_key_path, key.serialize_pem())?;
        key
    };

    let ca_cert = if ca_cert_path.exists() {
        // Re-issue from on-disk CA key: recreate self-signed CA params for signing children.
        // If cert exists we keep the PEM for clients and re-sign clients with ca_key.
        // For signing, rebuild an in-memory CA matching the key.
        let mut params = CertificateParams::new(vec!["Open-FDD MQTT CA".into()])?;
        params.is_ca = IsCa::Ca(BasicConstraints::Unconstrained);
        params.key_usages = vec![
            KeyUsagePurpose::KeyCertSign,
            KeyUsagePurpose::CrlSign,
            KeyUsagePurpose::DigitalSignature,
        ];
        let mut dn = DistinguishedName::new();
        dn.push(DnType::CommonName, "Open-FDD MQTT CA");
        params.distinguished_name = dn;
        params.self_signed(&ca_key)?
    } else {
        let mut params = CertificateParams::new(vec!["Open-FDD MQTT CA".into()])?;
        params.is_ca = IsCa::Ca(BasicConstraints::Unconstrained);
        params.key_usages = vec![
            KeyUsagePurpose::KeyCertSign,
            KeyUsagePurpose::CrlSign,
            KeyUsagePurpose::DigitalSignature,
        ];
        let mut dn = DistinguishedName::new();
        dn.push(DnType::CommonName, "Open-FDD MQTT CA");
        params.distinguished_name = dn;
        let cert = params.self_signed(&ca_key)?;
        fs::write(&ca_cert_path, cert.pem())?;
        cert
    };

    // Public CA only in the edge kit — never the CA private key.
    fs::copy(&ca_cert_path, kit.join("ca.pem"))?;
    if !ca_cert_path.exists() {
        fs::write(&ca_cert_path, ca_cert.pem())?;
    }

    let edge_cert_path = kit.join("edge.cert.pem");
    let edge_key_path = kit.join("edge.key.pem");
    issue_client_cert(
        &ca_cert,
        &ca_key,
        &format!("edge:{}:{}", req.site_id, req.edge_id),
        &edge_cert_path,
        &edge_key_path,
    )?;

    let central_cert_path = kit.join("central.cert.pem");
    let central_key_path = kit.join("central.key.pem");
    issue_client_cert(
        &ca_cert,
        &ca_key,
        &format!("central:{}", req.site_id),
        &central_cert_path,
        &central_key_path,
    )?;

    let topics = TopicBuilder::new(&req.site_id, &req.edge_id);
    let (edge_pub, edge_sub) = topics.edge_acl_patterns();
    let (central_pub, central_sub) = topics.central_acl_patterns();

    let edge_cfg = serde_json::json!({
        "site_id": req.site_id,
        "edge_id": req.edge_id,
        "broker_host": req.broker_host,
        "broker_port": req.broker_port,
        "ca_pem": "ca.pem",
        "cert_pem": "edge.cert.pem",
        "key_pem": "edge.key.pem",
        "topic_base": topics.base(),
        "note": "CA private key is NOT included. Outbound TCP 8883 only."
    });
    let edge_config = kit.join("edge.json");
    fs::write(&edge_config, serde_json::to_vec_pretty(&edge_cfg)?)?;

    let mut acl = String::new();
    acl.push_str(&format!("# Edge {}\n", req.edge_id));
    acl.push_str(&format!("user edge:{}:{}\n", req.site_id, req.edge_id));
    for t in edge_pub {
        acl.push_str(&format!("topic write {t}\n"));
    }
    for t in edge_sub {
        acl.push_str(&format!("topic read {t}\n"));
    }
    acl.push('\n');
    acl.push_str(&format!("user central:{}\n", req.site_id));
    for t in central_pub {
        acl.push_str(&format!("topic write {t}\n"));
    }
    for t in central_sub {
        acl.push_str(&format!("topic read {t}\n"));
    }
    let mosquitto_acl = kit.join("mosquitto.acl");
    fs::write(&mosquitto_acl, acl)?;

    Ok(ProvisionResult {
        kit_dir: kit,
        ca_pem: ca_cert_path,
        edge_cert: edge_cert_path,
        edge_key: edge_key_path,
        central_cert: central_cert_path,
        central_key: central_key_path,
        edge_config,
        mosquitto_acl,
    })
}

/// Filenames included in an AWS-style edge download ZIP (never CA private key).
pub const EDGE_KIT_ZIP_MEMBERS: &[&str] = &[
    "ca.pem",
    "edge.cert.pem",
    "edge.key.pem",
    "edge.json",
    "mosquitto.acl",
];

/// Members that must never appear in a downloadable edge kit ZIP.
pub const EDGE_KIT_ZIP_FORBIDDEN: &[&str] = &["ca.key.pem", "central.key.pem"];

/// Build a downloadable ZIP from an already-provisioned kit directory.
pub fn zip_edge_kit_dir(kit_dir: &Path) -> anyhow::Result<Vec<u8>> {
    use std::io::Write;

    let mut cursor = std::io::Cursor::new(Vec::new());
    {
        let mut zip = zip::ZipWriter::new(&mut cursor);
        let opts = zip::write::SimpleFileOptions::default()
            .compression_method(zip::CompressionMethod::Deflated);
        for name in EDGE_KIT_ZIP_MEMBERS {
            let path = kit_dir.join(name);
            if !path.is_file() {
                anyhow::bail!("edge kit missing required member {name}");
            }
            zip.start_file(*name, opts)?;
            zip.write_all(&fs::read(&path)?)?;
        }
        zip.finish()?;
    }
    Ok(cursor.into_inner())
}

/// Provision under `out_dir` and return ZIP bytes for the edge download bundle.
pub fn provision_edge_kit_zip(req: &ProvisionRequest) -> anyhow::Result<(String, Vec<u8>)> {
    let result = provision_edge_kit(req)?;
    let bytes = zip_edge_kit_dir(&result.kit_dir)?;
    let filename = format!("{}__{}.zip", req.site_id, req.edge_id);
    Ok((filename, bytes))
}

fn issue_client_cert(
    ca_cert: &rcgen::Certificate,
    ca_key: &KeyPair,
    cn: &str,
    cert_out: &Path,
    key_out: &Path,
) -> anyhow::Result<()> {
    let mut params = CertificateParams::new(vec![cn.to_string()])?;
    let mut dn = DistinguishedName::new();
    dn.push(DnType::CommonName, cn);
    params.distinguished_name = dn;
    params.key_usages = vec![
        KeyUsagePurpose::DigitalSignature,
        KeyUsagePurpose::KeyEncipherment,
    ];
    params.extended_key_usages = vec![rcgen::ExtendedKeyUsagePurpose::ClientAuth];
    let key = KeyPair::generate()?;
    let cert = params.signed_by(&key, ca_cert, ca_key)?;
    fs::write(cert_out, cert.pem())?;
    fs::write(key_out, key.serialize_pem())?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;

    #[test]
    fn edge_kit_zip_includes_public_pems_excludes_ca_key() {
        let tmp = tempfile::tempdir().unwrap();
        let (filename, bytes) = provision_edge_kit_zip(&ProvisionRequest {
            out_dir: tmp.path().to_path_buf(),
            site_id: "lab".into(),
            edge_id: "fieldbus-1".into(),
            broker_host: "mqtt.example.com".into(),
            broker_port: 8883,
            ca_dir: None,
        })
        .unwrap();
        assert_eq!(filename, "lab__fieldbus-1.zip");

        let mut archive = zip::ZipArchive::new(std::io::Cursor::new(bytes)).unwrap();
        let mut names = Vec::new();
        for i in 0..archive.len() {
            names.push(archive.by_index(i).unwrap().name().to_string());
        }
        for required in EDGE_KIT_ZIP_MEMBERS {
            assert!(names.iter().any(|n| n == required), "missing {required}");
        }
        for forbidden in EDGE_KIT_ZIP_FORBIDDEN {
            assert!(
                !names
                    .iter()
                    .any(|n| n == forbidden || n.ends_with(forbidden)),
                "zip must not contain {forbidden}"
            );
        }
        // CA private key lives only under ca/, never in zip members.
        assert!(tmp.path().join("ca/ca.key.pem").is_file());
        let mut edge_json = String::new();
        archive
            .by_name("edge.json")
            .unwrap()
            .read_to_string(&mut edge_json)
            .unwrap();
        assert!(edge_json.contains("mqtt.example.com"));
        assert!(edge_json.contains("fieldbus-1"));
    }
}
