# WebSocket Support in TurboAPI

TurboAPI provides WebSocket support for real-time bidirectional communication.

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

## Rust Integration

TurboAPI's WebSocket uses tokio-tungstenite for high performance:

```
┌─────────────────────────────────────────┐
│          Python Handler                  │
│     async def handler(websocket):        │
├─────────────────────────────────────────┤
│          PyO3 Bridge                     │
│   WebSocketConnection bindings           │
├─────────────────────────────────────────┤
│       tokio-tungstenite (Rust)          │
│   • Async message sending/receiving      │
│   • Frame encoding/decoding             │
│   • Ping/pong handling                  │
└─────────────────────────────────────────┘
```

## Performance Tips

1. **Use binary for large data**: Binary messages avoid UTF-8 encoding overhead
2. **Batch small messages**: Combine multiple small updates into one message
3. **Compress if needed**: For large JSON payloads, consider compression
4. **Connection pooling**: Reuse connections for multiple interactions

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

1. **Validate Origin**: Check Origin header to prevent CSRF
2. **Authentication**: Validate tokens before accepting connections
3. **Rate Limiting**: Limit messages per second per client
4. **Input Validation**: Sanitize all received messages

```python
@app.websocket("/secure")
async def secure_handler(websocket):
    # Check authentication
    token = websocket.query_params.get('token')
    if not validate_token(token):
        await websocket.close(code=4001)
        return

    await websocket.accept()
    # ... handle messages
```

## See Also

- [Architecture](./ARCHITECTURE.md)
- [Async Handlers](./ASYNC_HANDLERS.md)
- [hyper-tungstenite Documentation](https://docs.rs/hyper-tungstenite/)
