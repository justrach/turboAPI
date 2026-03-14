# HTTP/2 Support in TurboAPI

TurboAPI includes HTTP/2 support for improved performance with modern clients.

## Overview

HTTP/2 provides several advantages over HTTP/1.1:

- **Multiplexing**: Multiple requests over a single connection
- **Header Compression**: Reduced overhead with HPACK
- **Server Push**: Proactively send resources to clients
- **Stream Prioritization**: Important requests first

## Enabling HTTP/2

HTTP/2 is automatically enabled when using TLS (HTTPS). Clients negotiate the protocol via ALPN.

```python
from turboapi import TurboAPI

app = TurboAPI()

@app.get("/")
def hello():
    return {"message": "Hello via HTTP/2!"}

# HTTP/2 is used automatically with TLS
app.run(
    host="0.0.0.0",
    port=443,
    ssl_certfile="cert.pem",
    ssl_keyfile="key.pem"
)
```

## Server Push (Experimental)

Server push allows sending resources before the client requests them:

```python
# API for server push (in development)
@app.get("/page")
async def page_with_push(push: ServerPush):
    # Push CSS and JS before sending HTML
    await push.send("/static/style.css", "text/css")
    await push.send("/static/app.js", "application/javascript")

    return HTMLResponse("<html>...</html>")
```

## Performance Benefits

| Scenario | HTTP/1.1 | HTTP/2 | Improvement |
|----------|----------|--------|-------------|
| 10 parallel requests | 10 connections | 1 connection | 90% fewer |
| Header overhead | ~800 bytes | ~20 bytes | 40x smaller |
| First contentful paint | Blocking | Multiplexed | 2-3x faster |

## When to Use HTTP/2

### Recommended

- **Multiple API calls**: Dashboard loading multiple endpoints
- **Asset-heavy pages**: Many CSS/JS files
- **Mobile applications**: Limited connection capacity
- **High-latency networks**: Connection reuse matters

### Consider HTTP/1.1

- **Single large download**: No multiplexing benefit
- **Legacy client support**: Older browsers
- **Debugging simplicity**: HTTP/1.1 is easier to inspect

## Client Support

Most modern clients support HTTP/2:

| Client | HTTP/2 Support |
|--------|----------------|
| Chrome | Yes (2015+) |
| Firefox | Yes (2015+) |
| Safari | Yes (2014+) |
| Edge | Yes (2015+) |
| curl | Yes (7.43.0+) |
| Python requests | Via httpx |
| aiohttp | Yes |

## Testing HTTP/2

### Using curl

```bash
# Check HTTP/2 support
curl -I --http2 https://localhost/

# Verbose output showing protocol
curl -v --http2 https://localhost/
```

### Using Python

```python
import httpx

async with httpx.AsyncClient(http2=True) as client:
    response = await client.get("https://localhost/")
    print(f"Protocol: {response.http_version}")  # HTTP/2
```

## Architecture

```
Client Request (HTTP/2)
        ↓
   TLS Handshake + ALPN
        ↓
   h2 Frame Parser (planned)
        ↓
   Stream Manager
        ↓
   Request Router
        ↓
   Handler Execution
        ↓
   Response Serialization
        ↓
   h2 Frame Encoder
        ↓
Client Response (HTTP/2)
```

## Limitations

1. **TLS Required**: HTTP/2 in browsers requires HTTPS
2. **Server Push**: Not all clients handle pushes efficiently
3. **Head-of-line blocking**: TCP layer still has HOL blocking

## Configuration Options

```python
# Coming soon
app.configure_http2(
    max_concurrent_streams=100,
    initial_window_size=65535,
    max_frame_size=16384,
    enable_push=True
)
```

## See Also

- [TLS Setup](./TLS_SETUP.md)
- [Architecture](./ARCHITECTURE.md)
- [RFC 9113 - HTTP/2](https://datatracker.ietf.org/doc/html/rfc9113)
