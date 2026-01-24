"""WebSocket support for TurboAPI.

FastAPI-compatible WebSocket handling with decorators and connection management.
"""

import asyncio
import json
from typing import Any, Callable, Optional


class WebSocketDisconnect(Exception):
    """Raised when a WebSocket connection is closed."""

    def __init__(self, code: int = 1000, reason: Optional[str] = None):
        self.code = code
        self.reason = reason


class WebSocket:
    """WebSocket connection object.

    Provides methods for sending and receiving messages over a WebSocket connection.
    """

    def __init__(self, scope: Optional[dict] = None):
        self.scope = scope or {}
        self._accepted = False
        self._closed = False
        self._send_queue: asyncio.Queue = asyncio.Queue()
        self._receive_queue: asyncio.Queue = asyncio.Queue()
        self.client_state = "connecting"
        self.path_params: dict[str, Any] = {}
        self.query_params: dict[str, str] = {}
        self.headers: dict[str, str] = {}

    async def accept(
        self,
        subprotocol: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        """Accept the WebSocket connection."""
        self._accepted = True
        self.client_state = "connected"

    async def close(self, code: int = 1000, reason: Optional[str] = None) -> None:
        """Close the WebSocket connection."""
        self._closed = True
        self.client_state = "disconnected"

    async def send_text(self, data: str) -> None:
        """Send a text message."""
        if not self._accepted or self._closed:
            raise RuntimeError("WebSocket is not connected")
        await self._send_queue.put({"type": "text", "data": data})

    async def send_bytes(self, data: bytes) -> None:
        """Send a binary message."""
        if not self._accepted or self._closed:
            raise RuntimeError("WebSocket is not connected")
        await self._send_queue.put({"type": "bytes", "data": data})

    async def send_json(self, data: Any, mode: str = "text") -> None:
        """Send a JSON message."""
        text = json.dumps(data, ensure_ascii=False)
        if mode == "text":
            await self.send_text(text)
        else:
            await self.send_bytes(text.encode("utf-8"))

    async def receive_text(self) -> str:
        """Receive a text message."""
        if self._closed:
            raise WebSocketDisconnect()
        message = await self._receive_queue.get()
        if message.get("type") == "disconnect":
            raise WebSocketDisconnect(code=message.get("code", 1000))
        return message.get("data", "")

    async def receive_bytes(self) -> bytes:
        """Receive a binary message."""
        if self._closed:
            raise WebSocketDisconnect()
        message = await self._receive_queue.get()
        if message.get("type") == "disconnect":
            raise WebSocketDisconnect(code=message.get("code", 1000))
        data = message.get("data", b"")
        if isinstance(data, str):
            return data.encode("utf-8")
        return data

    async def receive_json(self, mode: str = "text") -> Any:
        """Receive a JSON message."""
        if mode == "text":
            text = await self.receive_text()
        else:
            data = await self.receive_bytes()
            text = data.decode("utf-8")
        return json.loads(text)

    async def iter_text(self):
        """Iterate over text messages."""
        try:
            while True:
                yield await self.receive_text()
        except WebSocketDisconnect:
            pass

    async def iter_bytes(self):
        """Iterate over binary messages."""
        try:
            while True:
                yield await self.receive_bytes()
        except WebSocketDisconnect:
            pass

    async def iter_json(self):
        """Iterate over JSON messages."""
        try:
            while True:
                yield await self.receive_json()
        except WebSocketDisconnect:
            pass


class WebSocketRoute:
    """Represents a registered WebSocket route."""

    def __init__(self, path: str, handler: Callable):
        self.path = path
        self.handler = handler
