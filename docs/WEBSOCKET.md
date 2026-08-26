# WebSocket Status in TurboAPI

TurboAPI's Zig HTTP runtime implements the RFC 6455 upgrade, text and binary
frames, ping/pong, close handling, fragmentation, and live Python handler
wiring. The transport is usable but remains alpha: native WebSocket routes are
exact-match and each long-lived connection currently occupies one HTTP worker.

The native runtime can invoke a synchronous route guard before the HTTP 101
handshake. The guard can inspect request metadata and allow the upgrade or
return a bounded status-only HTTP rejection. The asynchronous WebSocket handler
still begins after 101, so `await websocket.accept()` preserves the familiar
API shape but does not control the handshake.

## Quick Start

```python
from turboapi import TurboAPI

app = TurboAPI()

@app.websocket("/ws")
async def websocket_handler(websocket):
    await websocket.accept()

    while True:
        message = await websocket.receive_text()
        await websocket.send_text(f"Echo: {message}")
```

## How It Works

WebSocket connections use HTTP upgrade:

```
1. Client sends HTTP request with Upgrade: websocket
2. Server validates RFC 6455 headers and resolves the route
3. An optional route guard evaluates Authorization, Origin, and other metadata
4. Server rejects with bounded HTTP 4xx/5xx, or reserves capacity and sends 101
5. Bidirectional message exchange begins
```

For a Zig-backed connection, request metadata is available as normalized
convenience mappings and in its ASGI-shaped raw form:

```python
tenant = websocket.headers.get("x-tenant")
repo = websocket.query_params.get("repo")
raw_query = websocket.scope["query_string"]
raw_headers = websocket.scope["headers"]
path_params = websocket.path_params  # {} for current exact-match native routes
```

## Pre-upgrade guards

Use `guard=` for a small synchronous policy that must run before the native
runtime sends 101:

```python
from turboapi import (
    TurboAPI,
    WebSocketUpgradeRejection,
    WebSocketUpgradeRequest,
)

app = TurboAPI()


def allow_chat(request: WebSocketUpgradeRequest):
    if request.headers.get("origin") not in {"https://app.example.com"}:
        return WebSocketUpgradeRejection(403)

    authorization = request.headers.get("authorization", "")
    if not validate_bearer(authorization):
        return WebSocketUpgradeRejection(401)

    return True


@app.websocket("/chat", guard=allow_chat)
async def chat(websocket):
    await websocket.accept()
    # ... handle messages
```

`WebSocketUpgradeRequest` exposes the exact route path, lowercase headers,
last-value query parameters, and raw query-string bytes. Put bearer credentials
in the `Authorization` header, not in the URL query string, where intermediaries
may log them.

Only the literal `True` allows an upgrade. `False`, `None`, invalid results,
asynchronous guards, and guard exceptions fail closed with HTTP 403. Safe
application-selected rejection statuses are `400`, `401`, `403`, `404`, `429`,
`500`, and `503`; any other native result is reduced to `403`. Rejections have
an empty body and fixed bounded headers; request metadata and exception text are
never included. A 401 rejection includes `WWW-Authenticate: Bearer`.

TurboAPI rejects duplicate `Host`, `Authorization`, `Origin`,
`Sec-WebSocket-Key`, or `Sec-WebSocket-Version` headers with HTTP 400 before
invoking the guard. Header names are compared case-insensitively, preventing an
edge and application from making different first-value/last-value decisions.
Before guard evaluation, the native core also requires the RFC 6455 handshake
fields, including a non-empty `Host`, version 13, and a canonical Base64
`Sec-WebSocket-Key` that decodes to exactly 16 bytes.

Guards run after RFC 6455 validation and exact route lookup, but before active
WebSocket capacity admission. Rejected sockets therefore do not consume an
active WebSocket slot. Keep guard work short and non-blocking.

Live route replacement is synchronized. An in-flight upgrade retains one owned
handler/guard snapshot from policy evaluation through connection handling, while
a replacement affects only subsequent upgrades. Registration is serialized per
application across both Python route dictionaries and the native route map, so
concurrent free-threaded replacements cannot split handler/guard state. If
native registration fails, the Python route dictionaries retain the previous
route.

## Handler Types

### Text Messages

```python
@app.websocket("/chat")
async def chat(websocket):
    await websocket.accept()

    while True:
        text = await websocket.receive_text()
        # Process text message
        await websocket.send_text(f"Received: {text}")
```

### Binary Messages

```python
@app.websocket("/binary")
async def binary_handler(websocket):
    await websocket.accept()

    while True:
        data = await websocket.receive_bytes()
        # Process binary data
        await websocket.send_bytes(data)
```

### JSON Messages

```python
@app.websocket("/json")
async def json_handler(websocket):
    await websocket.accept()

    while True:
        data = await websocket.receive_json()
        # Process JSON data
        await websocket.send_json({"received": data})
```

## Connection Lifecycle

```python
@app.websocket("/lifecycle")
async def lifecycle_demo(websocket):
    # 1. Accept connection
    await websocket.accept()
    print(f"Connected: {websocket.client}")

    try:
        while True:
            # 2. Receive messages
            message = await websocket.receive_text()

            # 3. Send response
            await websocket.send_text(f"Echo: {message}")

    except WebSocketDisconnect:
        # 4. Handle disconnect
        print(f"Disconnected: {websocket.client}")
```

## Broadcasting

Send messages to multiple clients:

```python
from typing import Set

connected_clients: Set[WebSocket] = set()

@app.websocket("/broadcast")
async def broadcast_handler(websocket):
    await websocket.accept()
    connected_clients.add(websocket)

    try:
        while True:
            message = await websocket.receive_text()

            # Broadcast to all connected clients
            for client in connected_clients:
                await client.send_text(message)

    except WebSocketDisconnect:
        connected_clients.remove(websocket)
```

## Zig Runtime Status

The Zig HTTP core handles real WebSocket connections. Current limitations are:

- native WebSocket routes use exact path matching; path parameters are not resolved yet;
- guards are synchronous; database or network-backed authorization should be
  performed at the edge rather than blocking a native connection worker;
- every live WebSocket currently occupies one HTTP worker;
- subprotocol negotiation and `permessage-deflate` are not implemented.

## Performance Tips

1. **Use binary for large data**: Binary messages avoid UTF-8 encoding overhead
2. **Batch small messages**: Combine multiple small updates into one message
3. **Keep payloads bounded**: Native `permessage-deflate` is not implemented
4. **Reuse connections**: Avoid reconnecting for every message

## Client Examples

### JavaScript

```javascript
const ws = new WebSocket('ws://localhost:8000/ws');

ws.onopen = () => {
    ws.send('Hello, TurboAPI!');
};

ws.onmessage = (event) => {
    console.log('Received:', event.data);
};

ws.onclose = () => {
    console.log('Connection closed');
};
```

### Python

```python
import asyncio
import websockets

async def client():
    async with websockets.connect('ws://localhost:8000/ws') as ws:
        await ws.send('Hello!')
        response = await ws.recv()
        print(f'Received: {response}')

asyncio.run(client())
```

## Security

1. **Authenticate at the edge**: Use Cloudflare Access, Caddy, nginx, or another
   proxy as the outer boundary for public endpoints
2. **Reject before upgrade**: Add a native route guard for Authorization and an
   explicit Origin allowlist
3. **Defend after upgrade**: Recheck session state and authorization when policy
   can change during a long-lived connection
4. **Rate Limiting**: Limit messages per second per client
5. **Input Validation**: Sanitize all received messages

```python
@app.websocket("/secure")
async def secure_handler(websocket):
    # Defense in depth after the pre-upgrade guard, not a replacement for it.
    token = websocket.headers.get('authorization')
    if not validate_token(token):
        await websocket.close(code=1008, reason='policy violation')
        return

    await websocket.accept()
    # ... handle messages
```

Because the 101 handshake has already completed when the handler starts, this
code can only send a WebSocket close, not an HTTP 401/403. Use the edge for the
outer boundary, the route guard for native pre-upgrade rejection, and handler
checks for post-upgrade defense in depth.

## See Also

- [Architecture](./ARCHITECTURE.md)
- [Async Handlers](./ASYNC_HANDLERS.md)
- [RFC 6455 - WebSocket Protocol](https://datatracker.ietf.org/doc/html/rfc6455)
