# TLS/SSL Setup Guide

This guide explains how to configure TLS/SSL for secure HTTPS connections in TurboAPI.

## Quick Start

TurboAPI supports TLS via rustls (default) or OpenSSL backends.

### Generate Self-Signed Certificates (Development)

```bash
# Generate private key
openssl genrsa -out key.pem 2048

# Generate self-signed certificate
openssl req -new -x509 -key key.pem -out cert.pem -days 365 \
  -subj "/CN=localhost"
```

### Enable TLS (Coming Soon)

```python
from turboapi import TurboAPI

app = TurboAPI()

@app.get("/")
def hello():
    return {"message": "Hello, secure world!"}

# TLS configuration (API in development)
app.run(
    host="0.0.0.0",
    port=443,
    ssl_certfile="cert.pem",
    ssl_keyfile="key.pem"
)
```

## Backend Selection

TurboAPI supports two TLS backends:

### rustls (Default)

Pure Rust implementation, enabled by default.

```toml
# Cargo.toml
[features]
default = ["python", "tls-rustls"]
```

Advantages:
- Pure Rust, no C dependencies
- Modern TLS 1.3 support
- Secure defaults
- Easier to build

### OpenSSL (Optional)

Battle-tested OpenSSL library.

```toml
# Cargo.toml
[features]
default = ["python", "tls-openssl"]
```

Advantages:
- Wide compatibility
- Hardware acceleration on some platforms
- More cipher suites

## Certificate Formats

TurboAPI accepts PEM-encoded certificates:

### Certificate File (cert.pem)

```
-----BEGIN CERTIFICATE-----
MIIDXTCCAkWgAwIBAgIJAJC1HiIAZAiU...
-----END CERTIFICATE-----
```

### Private Key File (key.pem)

```
-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn...
-----END RSA PRIVATE KEY-----
```

## Production Certificates

For production, use certificates from a Certificate Authority:

### Let's Encrypt (Free)

```bash
# Install certbot
sudo apt install certbot

# Generate certificate
sudo certbot certonly --standalone -d yourdomain.com

# Certificates are in:
# /etc/letsencrypt/live/yourdomain.com/fullchain.pem
# /etc/letsencrypt/live/yourdomain.com/privkey.pem
```

### Commercial CA

1. Generate a CSR (Certificate Signing Request)
2. Submit to CA (DigiCert, Comodo, etc.)
3. Receive signed certificate
4. Configure with your private key

## Security Recommendations

1. **TLS 1.3**: Use TLS 1.3 for best security (default with rustls)
2. **Strong Keys**: Use 2048-bit RSA or 256-bit ECDSA
3. **Certificate Renewal**: Set up automatic renewal (Let's Encrypt: 90 days)
4. **HSTS**: Enable HTTP Strict Transport Security headers
5. **Redirect HTTP**: Redirect all HTTP to HTTPS

## Troubleshooting

### Certificate Chain Issues

If clients report certificate errors, ensure you include the full chain:

```bash
cat server.pem intermediate.pem > fullchain.pem
```

### Permission Errors

Private keys should be readable only by the application:

```bash
chmod 600 key.pem
```

### Port Binding

Port 443 requires root/admin privileges:

```bash
# Option 1: Run as root (not recommended)
sudo python app.py

# Option 2: Use higher port with reverse proxy
# Run app on 8443, nginx forwards 443 -> 8443

# Option 3: Use setcap (Linux)
sudo setcap 'cap_net_bind_service=+ep' /usr/bin/python3
```

## See Also

- [README](../README.md)
- [Architecture](./ARCHITECTURE.md)
- [rustls Documentation](https://docs.rs/rustls/)
