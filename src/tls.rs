//! TLS configuration and certificate management for TurboAPI
//!
//! Supports both rustls (default) and openssl backends via feature flags.
//! Use `tls-rustls` feature for rustls (recommended) or `tls-openssl` for OpenSSL.

use std::fs::File;
use std::io::BufReader;
use std::path::Path;
use std::sync::Arc;

#[cfg(feature = "tls-rustls")]
use rustls::pki_types::{CertificateDer, PrivateKeyDer};

/// TLS configuration for the server
#[derive(Clone)]
pub struct TlsConfig {
    /// Path to the certificate file (PEM format)
    pub cert_path: String,
    /// Path to the private key file (PEM format)
    pub key_path: String,
    /// Optional ALPN protocols (e.g., ["h2", "http/1.1"])
    pub alpn_protocols: Vec<String>,
}

impl TlsConfig {
    /// Create a new TLS configuration
    pub fn new(cert_path: impl Into<String>, key_path: impl Into<String>) -> Self {
        TlsConfig {
            cert_path: cert_path.into(),
            key_path: key_path.into(),
            alpn_protocols: vec!["h2".to_string(), "http/1.1".to_string()],
        }
    }

    /// Set ALPN protocols (for HTTP/2 negotiation)
    pub fn with_alpn(mut self, protocols: Vec<String>) -> Self {
        self.alpn_protocols = protocols;
        self
    }
}

/// Error type for TLS operations
#[derive(Debug)]
pub enum TlsError {
    CertificateLoadError(String),
    KeyLoadError(String),
    ConfigurationError(String),
}

impl std::fmt::Display for TlsError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            TlsError::CertificateLoadError(msg) => write!(f, "Certificate load error: {}", msg),
            TlsError::KeyLoadError(msg) => write!(f, "Key load error: {}", msg),
            TlsError::ConfigurationError(msg) => write!(f, "TLS configuration error: {}", msg),
        }
    }
}

impl std::error::Error for TlsError {}

#[cfg(feature = "tls-rustls")]
pub mod rustls_backend {
    use super::*;
    use rustls::ServerConfig;
    use rustls_pemfile::{certs, private_key};

    /// Load certificates from a PEM file
    pub fn load_certs(path: &Path) -> Result<Vec<CertificateDer<'static>>, TlsError> {
        let file = File::open(path).map_err(|e| {
            TlsError::CertificateLoadError(format!("Failed to open {}: {}", path.display(), e))
        })?;
        let mut reader = BufReader::new(file);

        let certs: Vec<CertificateDer<'static>> = certs(&mut reader)
            .filter_map(|c| c.ok())
            .collect();

        if certs.is_empty() {
            return Err(TlsError::CertificateLoadError(
                "No valid certificates found in file".to_string(),
            ));
        }

        Ok(certs)
    }

    /// Load private key from a PEM file
    pub fn load_private_key(path: &Path) -> Result<PrivateKeyDer<'static>, TlsError> {
        let file = File::open(path).map_err(|e| {
            TlsError::KeyLoadError(format!("Failed to open {}: {}", path.display(), e))
        })?;
        let mut reader = BufReader::new(file);

        private_key(&mut reader)
            .map_err(|e| TlsError::KeyLoadError(format!("Failed to parse key: {}", e)))?
            .ok_or_else(|| TlsError::KeyLoadError("No valid private key found in file".to_string()))
    }

    /// Create a rustls ServerConfig from TlsConfig
    pub fn create_server_config(config: &TlsConfig) -> Result<Arc<ServerConfig>, TlsError> {
        let certs = load_certs(Path::new(&config.cert_path))?;
        let key = load_private_key(Path::new(&config.key_path))?;

        let mut server_config = ServerConfig::builder()
            .with_no_client_auth()
            .with_single_cert(certs, key)
            .map_err(|e| TlsError::ConfigurationError(format!("TLS config error: {}", e)))?;

        // Set ALPN protocols for HTTP/2 negotiation
        server_config.alpn_protocols = config
            .alpn_protocols
            .iter()
            .map(|s| s.as_bytes().to_vec())
            .collect();

        Ok(Arc::new(server_config))
    }

    /// Create a TLS acceptor for incoming connections
    pub fn create_acceptor(config: &TlsConfig) -> Result<tokio_rustls::TlsAcceptor, TlsError> {
        let server_config = create_server_config(config)?;
        Ok(tokio_rustls::TlsAcceptor::from(server_config))
    }
}

#[cfg(feature = "tls-openssl")]
pub mod openssl_backend {
    use super::*;
    use openssl::ssl::{SslAcceptor, SslFiletype, SslMethod};

    /// Create an OpenSSL SSL acceptor from TlsConfig
    pub fn create_ssl_acceptor(config: &TlsConfig) -> Result<SslAcceptor, TlsError> {
        let mut builder = SslAcceptor::mozilla_intermediate(SslMethod::tls())
            .map_err(|e| TlsError::ConfigurationError(format!("SSL builder error: {}", e)))?;

        builder
            .set_certificate_file(&config.cert_path, SslFiletype::PEM)
            .map_err(|e| TlsError::CertificateLoadError(format!("Certificate error: {}", e)))?;

        builder
            .set_private_key_file(&config.key_path, SslFiletype::PEM)
            .map_err(|e| TlsError::KeyLoadError(format!("Key error: {}", e)))?;

        // Set ALPN protocols for HTTP/2 negotiation
        let alpn_wire: Vec<u8> = config
            .alpn_protocols
            .iter()
            .flat_map(|p| {
                let mut v = vec![p.len() as u8];
                v.extend(p.as_bytes());
                v
            })
            .collect();

        builder
            .set_alpn_protos(&alpn_wire)
            .map_err(|e| TlsError::ConfigurationError(format!("ALPN error: {}", e)))?;

        Ok(builder.build())
    }
}

/// Generate a self-signed certificate for development/testing
/// This is NOT for production use!
#[cfg(feature = "tls-rustls")]
pub fn generate_self_signed_cert(
    _common_name: &str,
) -> Result<(Vec<u8>, Vec<u8>), TlsError> {
    // For production, use rcgen crate or external tools to generate certificates
    Err(TlsError::ConfigurationError(
        "Self-signed certificate generation not implemented. Use external tools like mkcert or openssl.".to_string(),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_tls_config_creation() {
        let config = TlsConfig::new("cert.pem", "key.pem");
        assert_eq!(config.cert_path, "cert.pem");
        assert_eq!(config.key_path, "key.pem");
        assert_eq!(config.alpn_protocols, vec!["h2", "http/1.1"]);
    }

    #[test]
    fn test_tls_config_with_alpn() {
        let config = TlsConfig::new("cert.pem", "key.pem")
            .with_alpn(vec!["h2".to_string()]);
        assert_eq!(config.alpn_protocols, vec!["h2"]);
    }
}
