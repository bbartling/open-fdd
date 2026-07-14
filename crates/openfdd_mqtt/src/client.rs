//! MQTTS publish/subscribe wrapper (rumqttc + OpenSSL native-tls).
//!
//! Prefers native-tls so the workspace is not pinned to rumqttc's rustls 0.22 /
//! rustls-webpki 0.102.8 advisory cluster.

use std::path::PathBuf;
use std::time::Duration;

use openssl::pkcs12::Pkcs12;
use openssl::pkey::PKey;
use openssl::x509::X509;
use rumqttc::{AsyncClient, Event, Incoming, MqttOptions, QoS, TlsConfiguration, Transport};
use tokio::sync::mpsc;
use tracing::{info, warn};

#[derive(Debug, Clone)]
pub struct MqttConfig {
    pub host: String,
    pub port: u16,
    pub client_id: String,
    pub ca_pem: PathBuf,
    pub cert_pem: PathBuf,
    pub key_pem: PathBuf,
    pub keep_alive_secs: u64,
}

pub struct MqttHandle {
    client: AsyncClient,
    pub events: mpsc::UnboundedReceiver<Incoming>,
}

impl MqttHandle {
    pub async fn connect(cfg: MqttConfig) -> anyhow::Result<Self> {
        let ca_pem = tokio::fs::read(&cfg.ca_pem).await?;
        let cert_pem = tokio::fs::read(&cfg.cert_pem).await?;
        let key_pem = tokio::fs::read(&cfg.key_pem).await?;
        let (pkcs12, password) =
            tokio::task::spawn_blocking(move || pem_to_pkcs12(&cert_pem, &key_pem)).await??;

        let mut opts = MqttOptions::new(&cfg.client_id, &cfg.host, cfg.port);
        opts.set_keep_alive(Duration::from_secs(cfg.keep_alive_secs.max(10)));
        opts.set_transport(Transport::tls_with_config(TlsConfiguration::SimpleNative {
            ca: ca_pem,
            client_auth: Some((pkcs12, password)),
        }));

        let (client, mut eventloop) = AsyncClient::new(opts, 64);
        let (tx, rx) = mpsc::unbounded_channel();
        tokio::spawn(async move {
            loop {
                match eventloop.poll().await {
                    Ok(Event::Incoming(i)) => {
                        if tx.send(i).is_err() {
                            break;
                        }
                    }
                    Ok(_) => {}
                    Err(err) => {
                        warn!(%err, "mqtt eventloop error");
                        tokio::time::sleep(Duration::from_secs(2)).await;
                    }
                }
            }
        });
        info!(host = %cfg.host, port = cfg.port, "mqtts client started");
        Ok(Self { client, events: rx })
    }

    pub fn split(self) -> (AsyncClient, mpsc::UnboundedReceiver<Incoming>) {
        (self.client, self.events)
    }

    pub async fn publish_json(
        &self,
        topic: &str,
        payload: &impl serde::Serialize,
        retain: bool,
    ) -> anyhow::Result<()> {
        publish_json(&self.client, topic, payload, retain).await
    }

    pub async fn publish_bytes(
        &self,
        topic: &str,
        payload: Vec<u8>,
        retain: bool,
    ) -> anyhow::Result<()> {
        self.client
            .publish(topic, QoS::AtLeastOnce, retain, payload)
            .await?;
        Ok(())
    }

    pub async fn subscribe(&self, topic: &str) -> anyhow::Result<()> {
        self.client.subscribe(topic, QoS::AtLeastOnce).await?;
        Ok(())
    }

    pub fn raw(&self) -> &AsyncClient {
        &self.client
    }
}

pub async fn publish_json(
    client: &AsyncClient,
    topic: &str,
    payload: &impl serde::Serialize,
    retain: bool,
) -> anyhow::Result<()> {
    let body = serde_json::to_vec(payload)?;
    client
        .publish(topic, QoS::AtLeastOnce, retain, body)
        .await?;
    Ok(())
}

fn pem_to_pkcs12(cert_pem: &[u8], key_pem: &[u8]) -> anyhow::Result<(Vec<u8>, String)> {
    let key = PKey::private_key_from_pem(key_pem)?;
    let cert = X509::from_pem(cert_pem)?;
    let password = "openfdd-mqtt";
    let mut builder = Pkcs12::builder();
    builder.name("openfdd");
    builder.pkey(&key);
    builder.cert(&cert);
    let p12 = builder.build2(password)?;
    Ok((p12.to_der()?, password.to_string()))
}
