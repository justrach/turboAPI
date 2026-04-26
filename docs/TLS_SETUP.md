# TLS/SSL Setup Guide

Native TLS termination is not implemented in TurboAPI's Zig HTTP runtime.

## Status

For production HTTPS, place a reverse proxy such as Caddy, nginx, Cloudflare, a
`cloudflared` tunnel, or a load balancer in front of TurboAPI. That proxy should
terminate TLS and forward HTTP/1.1 to TurboAPI on a private interface.

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

Example Caddy shape with automatic ACME certificates:

```caddyfile
{
    email ops@example.com
}

api.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

For Cloudflare Tunnel, publish the hostname to TurboAPI's local HTTP listener:

```yaml
ingress:
  - hostname: api.example.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

## See Also

- [README](../README.md)
- [HTTP/2 Status](./HTTP2.md)
- [HTTP/3 and QUIC](./HTTP3_QUIC.md)
- [Architecture](./ARCHITECTURE.md)
