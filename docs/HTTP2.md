# HTTP/2 Status in TurboAPI

TurboAPI's Zig HTTP runtime currently speaks HTTP/1.1 only. Native HTTP/2
connection handling, ALPN negotiation, HPACK, multiplexed streams, and server
push are not implemented in the live runtime.

## Recommended Deployment

Terminate TLS and HTTP/2 at a reverse proxy, then proxy HTTP/1.1 to TurboAPI.
Use the same edge-termination model for HTTP/3/QUIC:

```text
Client
  -> HTTPS / HTTP/2 or HTTP/3 at Caddy, nginx, Cloudflare, or another edge proxy
  -> HTTP/1.1 to TurboAPI on 127.0.0.1:8000
```

TurboAPI should run on a private interface or behind a trusted proxy:

```bash
python app.py  # listens on 127.0.0.1:8000
```

Example Caddy shape:

```caddyfile
api.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Caddy handles certificate management, TLS termination, and HTTP/2/HTTP/3 negotiation.
TurboAPI receives normal HTTP/1.1 requests from the proxy.

## Runtime Stance

- Native TLS termination is intentionally kept out-of-process for the current
  runtime. Use Caddy, nginx, Cloudflare, or a load balancer for HTTPS.
- Native HTTP/2 should be revisited with the broader runtime/event-loop work.
  The current blocking connection model is not the right long-term base for
  multiplexed HTTP/2 streams.
- Native HTTP/3/QUIC is separate UDP transport work and is tracked in issue
  `#138`.
- `ssl_certfile`, `ssl_keyfile`, `configure_http2()`, and server push APIs are
  not available in the current Zig server path.

## How To Verify Your Deployment

Check HTTP/2 at the proxy:

```bash
curl -I --http2 https://api.example.com/
```

Check the private TurboAPI hop:

```bash
curl -I http://127.0.0.1:8000/
```

The first command should negotiate HTTP/2 with the proxy. The second command is
expected to be HTTP/1.1 because it talks directly to TurboAPI.

## Tracking

This document records the current issue `#115` resolution for this runtime:
terminate TLS and HTTP/2 out-of-process. Future native HTTP/2/TLS work should
start from a fresh runtime design issue with tests for the then-current server
architecture.

## See Also

- [TLS Setup](./TLS_SETUP.md)
- [HTTP/3 and QUIC](./HTTP3_QUIC.md)
- [Architecture](./ARCHITECTURE.md)
- [RFC 9113 - HTTP/2](https://datatracker.ietf.org/doc/html/rfc9113)
