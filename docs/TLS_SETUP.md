# TLS/SSL Setup Guide

Native TLS termination is not implemented in TurboAPI's Zig HTTP runtime.

## Status

For production HTTPS, place a reverse proxy such as Caddy, nginx, Cloudflare,
or a load balancer in front of TurboAPI. That proxy should terminate TLS and
forward HTTP/1.1 to TurboAPI on a private interface.

If you also want HTTP/3/QUIC, terminate it at the same edge proxy and make sure
UDP 443 is reachable. TurboAPI itself should still receive HTTP/1.1 from the
proxy.

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
- [HTTP/3 and QUIC](./HTTP3_QUIC.md)
- [Architecture](./ARCHITECTURE.md)
