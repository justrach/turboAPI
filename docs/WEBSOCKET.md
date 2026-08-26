# WebSocket Status in TurboAPI

TurboAPI's Zig HTTP runtime implements the RFC 6455 upgrade, text and binary
frames, ping/pong, close handling, fragmentation, and live Python handler
wiring. The transport is usable but remains alpha: native WebSocket routes are
exact-match and each long-lived connection currently occupies one HTTP worker.

The native runtime completes the HTTP 101 handshake before it invokes the
Python handler. Consequently, `await websocket.accept()` preserves the familiar
API shape but does not control the handshake. Use an authenticating edge proxy
for public endpoints; a Python handler can inspect metadata and close the
already-upgraded connection, but cannot return a pre-upgrade HTTP 401 or 403.

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
2. Server responds with 101 Switching Protocols
3. Connection upgrades to WebSocket protocol
4. Bidirectional message exchange begins
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
- the 101 response is sent before Python runs, so application code cannot reject
  an upgrade with an HTTP authentication response;
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
   proxy that rejects unauthenticated requests before the WebSocket upgrade
2. **Validate Origin**: Inspect the propagated `Origin` header and close with a
   policy-violation code when it is not allowed
3. **Rate Limiting**: Limit messages per second per client
4. **Input Validation**: Sanitize all received messages

```python
@app.websocket("/secure")
async def secure_handler(websocket):
    # This is a post-upgrade policy check, not pre-upgrade authentication.
    # Prefer an Authorization header; query tokens can leak into logs.
    token = websocket.headers.get('authorization')
    if not validate_token(token):
        await websocket.close(code=1008, reason='policy violation')
        return

    await websocket.accept()
    # ... handle messages
```

Because the 101 handshake has already completed when the handler starts, the
check above is defense in depth. Keep the TurboAPI origin private and enforce
the actual authentication decision at the edge until a native pre-upgrade guard
API is implemented.

## See Also

- [Architecture](./ARCHITECTURE.md)
- [Async Handlers](./ASYNC_HANDLERS.md)
- [RFC 6455 - WebSocket Protocol](https://datatracker.ietf.org/doc/html/rfc6455)
