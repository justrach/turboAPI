# TLS/SSL Setup Guide

Native TLS termination is not implemented in TurboAPI's Zig HTTP runtime.

## Status

For production HTTPS, place a reverse proxy such as Caddy, nginx, Cloudflare,
or a load balancer in front of TurboAPI. That proxy should terminate TLS and
forward HTTP/1.1 to TurboAPI on a private interface.

This is the intended current deployment stance: TLS stays out-of-process until
the runtime has a tested native TLS design.

## Workaround: Reverse Proxy

```bash
# Run TurboAPI on a local port
python app.py  # listens on 127.0.0.1:8000

# Use nginx or Caddy to terminate TLS and proxy to TurboAPI
```

Example Caddy shape:

```caddyfile
api.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

## See Also

- [README](../README.md)
- [HTTP/2 Status](./HTTP2.md)
- [Architecture](./ARCHITECTURE.md)
