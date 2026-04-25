# HTTP/3 and QUIC Status in TurboAPI

TurboAPI does not currently implement native QUIC or HTTP/3 in the Zig runtime.
The supported production path is to terminate HTTP/3/QUIC at an edge proxy and
forward HTTP/1.1 to TurboAPI.

## Why Native QUIC Is Separate Runtime Work

The current Zig server is an HTTP/1.1 TCP runtime:

- it listens with `std.Io.net.IpAddress.listen(...)`
- workers receive accepted `std.Io.net.Stream` TCP connections
- requests are parsed from blocking TCP `read` calls
- responses are written back through the same stream

QUIC is UDP-based and carries its own connection, stream, TLS 1.3, loss
recovery, congestion-control, and flow-control machinery. HTTP/3 then maps HTTP
semantics onto QUIC streams and uses QPACK for headers. That makes native
HTTP/3 a new transport runtime, not a flag on the current TCP listener.

## Supported Deployment Today

Use an edge proxy that supports HTTP/3/QUIC for public traffic:

```text
Client
  -> HTTPS / HTTP/3 / QUIC at Caddy, Cloudflare, nginx, or a load balancer
  -> HTTP/1.1 to TurboAPI on 127.0.0.1:8000
```

TurboAPI should still bind to a private interface:

```bash
python app.py  # listens on 127.0.0.1:8000
```

## Caddy Example

Caddy enables HTTP/3 by default for HTTPS sites when UDP 443 is reachable.

```caddyfile
api.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

If you run Caddy in Docker, expose both TCP and UDP 443:

```yaml
services:
  caddy:
    image: caddy:latest
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config

volumes:
  caddy_data:
  caddy_config:
```

The upstream from Caddy to TurboAPI remains HTTP/1.1. Do not configure Caddy to
proxy HTTP/3 to TurboAPI because TurboAPI is not an HTTP/3 upstream server.

## Cloudflare Example

Cloudflare can terminate HTTP/3/QUIC at its edge and forward to the origin
without requiring TurboAPI to speak QUIC. Keep TurboAPI behind HTTPS or a
private tunnel/load balancer according to your deployment model.

## nginx Example

nginx can be used when it is built with HTTP/3/QUIC support. The exact build and
TLS library requirements vary by distribution, so prefer your platform's
official nginx packaging notes. As with Caddy, nginx should terminate QUIC and
proxy HTTP/1.1 to TurboAPI.

## Verification

Check the public edge:

```bash
curl -I --http3 https://api.example.com/
```

Check the private TurboAPI hop:

```bash
curl -I http://127.0.0.1:8000/
```

The first command should use HTTP/3 if your client and proxy support it. The
second command is expected to use HTTP/1.1 because it talks directly to
TurboAPI.

## Native Runtime Tracking

Native HTTP/3/QUIC support is tracked in issue `#138`. Do not mark native QUIC
as supported until a runtime test proves an HTTP/3 client can connect directly
to the Zig server over UDP.

## References

- [Caddy global HTTP protocol options](https://caddyserver.com/docs/caddyfile/options)
- [Caddy Docker port guidance](https://caddyserver.com/docs/running)
- [Cloudflare HTTP/3 with QUIC](https://developers.cloudflare.com/speed/optimization/protocol/http3/)
- [nginx QUIC and HTTP/3 documentation](https://nginx.org/en/docs/quic.html)
