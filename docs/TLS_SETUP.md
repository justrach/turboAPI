# TLS/SSL Setup Guide

TLS/SSL support is planned for the Zig backend. This feature is not yet available.

## Status

TurboAPI's Zig HTTP core does not currently support TLS termination. For production HTTPS, place a reverse proxy (e.g., nginx, Caddy) in front of TurboAPI.

## Workaround: Reverse Proxy

```bash
# Run TurboAPI on a local port
python app.py  # listens on 127.0.0.1:8000

# Use nginx or Caddy to terminate TLS and proxy to TurboAPI
```

## See Also

- [README](../README.md)
- [Architecture](./ARCHITECTURE.md)
